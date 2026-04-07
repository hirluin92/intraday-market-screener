"""
On-demand pattern backtest: forward returns vs stored candles (MVP, no persistence).

- Entry reference: candle **close** at the pattern bar (via CandleFeature → Candle).
- Horizons: +1, +3, +5, +10 **candles** ahead in the same (exchange, symbol, timeframe) series.
- **Bullish / neutral**: long return % = (close_fwd − close_entry) / close_entry × 100; win if > 0.
- **Bearish**: short return % = (close_entry − close_fwd) / close_entry × 100; win if > 0 (price fell).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import PatternBacktestAggregateRow, PatternBacktestResponse
from app.services.pattern_quality import (
    binomial_test_vs_50pct,
    compute_pattern_quality_score,
    pattern_forward_win_rate_wilson_ci,
    pattern_primary_horizon_wins_rets,
    significance_label,
    ttest_expectancy_vs_zero,
)

HORIZONS = (1, 3, 5, 10)

# Same cap as GET /backtest/patterns — enough rows to build (pattern_name, timeframe) aggregates.
PATTERN_QUALITY_AGGREGATE_LIMIT = 5000


async def pattern_quality_lookup_by_name_tf(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
) -> dict[tuple[str, str], PatternBacktestAggregateRow]:
    """
    Reuses ``run_pattern_backtest`` aggregates keyed by (pattern_name, timeframe).
    Filters align with screener list filters so quality matches the evaluated universe.

    ``dt_from`` / ``dt_to``: se impostati, solo righe ``CandlePattern`` con timestamp in
    quell'intervallo (utile per OOS: lookup solo su train pre-cutoff).
    """
    resp = await run_pattern_backtest(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=None,
        limit=PATTERN_QUALITY_AGGREGATE_LIMIT,
        dt_from=dt_from,
        dt_to=dt_to,
    )
    return {(a.pattern_name, a.timeframe): a for a in resp.aggregates}


def _f(x: Any) -> float:
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


def _signed_return_pct(
    entry_close: float,
    future_close: float,
    direction: str,
) -> float:
    if entry_close <= 0:
        return 0.0
    if direction == "bearish":
        return (entry_close - future_close) / entry_close * 100.0
    return (future_close - entry_close) / entry_close * 100.0


def _is_win(signed_return: float) -> bool:
    return signed_return > 0


def _mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return sum(xs) / len(xs)


def _win_rate(wins: list[bool]) -> float | None:
    if not wins:
        return None
    return sum(1 for w in wins if w) / len(wins)


async def run_pattern_backtest(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    pattern_name: str | None,
    limit: int,
    dt_from: datetime | None = None,
    dt_to: datetime | None = None,
) -> PatternBacktestResponse:
    stmt = (
        select(CandlePattern, Candle.close, CandleFeature.candle_id)
        .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
        .join(Candle, CandleFeature.candle_id == Candle.id)
    )
    conds = []
    if exchange is not None:
        conds.append(CandlePattern.exchange == exchange)
    if provider is not None:
        conds.append(CandlePattern.provider == provider)
    if asset_type is not None:
        conds.append(CandlePattern.asset_type == asset_type)
    if symbol is not None:
        conds.append(CandlePattern.symbol == symbol)
    if timeframe is not None:
        conds.append(CandlePattern.timeframe == timeframe)
    if pattern_name is not None:
        conds.append(CandlePattern.pattern_name == pattern_name)
    if dt_from is not None:
        conds.append(CandlePattern.timestamp >= dt_from)
    if dt_to is not None:
        conds.append(CandlePattern.timestamp <= dt_to)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(CandlePattern.timestamp.desc()).limit(limit)

    result = await session.execute(stmt)
    rows = list(result.all())
    patterns_evaluated = len(rows)
    if not rows:
        return PatternBacktestResponse(aggregates=[], patterns_evaluated=0)

    series_keys: set[tuple[str, str, str]] = set()
    for p, _, _ in rows:
        series_keys.add((p.exchange, p.symbol, p.timeframe))

    or_parts = [
        and_(Candle.exchange == ex, Candle.symbol == sym, Candle.timeframe == tf)
        for ex, sym, tf in series_keys
    ]
    c_stmt = select(Candle).where(or_(*or_parts)).order_by(
        Candle.exchange,
        Candle.symbol,
        Candle.timeframe,
        Candle.timestamp.asc(),
    )
    c_result = await session.execute(c_stmt)
    all_candles = list(c_result.scalars().all())

    by_series: dict[tuple[str, str, str], list[Candle]] = defaultdict(list)
    for c in all_candles:
        by_series[(c.exchange, c.symbol, c.timeframe)].append(c)

    id_to_index: dict[tuple[str, str, str], dict[int, int]] = {}
    for key, clist in by_series.items():
        id_to_index[key] = {c.id: i for i, c in enumerate(clist)}

    # (pattern_name, timeframe) -> horizon -> rets / wins
    acc: dict[tuple[str, str], dict[int, dict[str, list]]] = defaultdict(
        lambda: {h: {"rets": [], "wins": []} for h in HORIZONS},
    )

    for pat, entry_close, candle_id in rows:
        key_s = (pat.exchange, pat.symbol, pat.timeframe)
        clist = by_series.get(key_s)
        idx_map = id_to_index.get(key_s)
        if not clist or not idx_map:
            continue
        idx = idx_map.get(candle_id)
        if idx is None:
            continue
        ec = _f(entry_close)

        for h in HORIZONS:
            j = idx + h
            if j >= len(clist):
                continue
            fut_close = _f(clist[j].close)
            ret = _signed_return_pct(ec, fut_close, pat.direction)
            gk = (pat.pattern_name, pat.timeframe)
            acc[gk][h]["rets"].append(ret)
            acc[gk][h]["wins"].append(_is_win(ret))

    aggregates: list[PatternBacktestAggregateRow] = []
    for (pn, tf) in sorted(acc.keys()):
        hdata = acc[(pn, tf)]
        n1 = len(hdata[1]["rets"])
        n3 = len(hdata[3]["rets"])
        n5 = len(hdata[5]["rets"])
        n10 = len(hdata[10]["rets"])
        avg3 = _mean(hdata[3]["rets"])
        avg5 = _mean(hdata[5]["rets"])
        wr3 = _win_rate(hdata[3]["wins"])
        wr5 = _win_rate(hdata[5]["wins"])
        pq = compute_pattern_quality_score(
            sample_size_3=n3,
            sample_size_5=n5,
            avg_return_3=avg3,
            avg_return_5=avg5,
            win_rate_3=wr3,
            win_rate_5=wr5,
        )
        ci_lo, ci_hi, rel = pattern_forward_win_rate_wilson_ci(
            hdata=hdata,
            n3=n3,
            n5=n5,
        )
        wins_h, n_h, rets_h = pattern_primary_horizon_wins_rets(hdata)
        win_p: float | None = None
        win_sig: str | None = None
        exp_p: float | None = None
        exp_sig: str | None = None
        if n_h > 0:
            win_p = binomial_test_vs_50pct(wins_h, n_h)
            win_sig = significance_label(win_p)
        if n_h >= 2:
            _, exp_p_raw = ttest_expectancy_vs_zero(rets_h)
            exp_p = exp_p_raw
            exp_sig = significance_label(exp_p_raw)
        aggregates.append(
            PatternBacktestAggregateRow(
                pattern_name=pn,
                timeframe=tf,
                sample_size=n1,
                sample_size_3=n3,
                sample_size_5=n5,
                sample_size_10=n10,
                avg_return_1=_mean(hdata[1]["rets"]),
                avg_return_3=avg3,
                avg_return_5=avg5,
                avg_return_10=_mean(hdata[10]["rets"]),
                win_rate_1=_win_rate(hdata[1]["wins"]),
                win_rate_3=wr3,
                win_rate_5=wr5,
                win_rate_10=_win_rate(hdata[10]["wins"]),
                pattern_quality_score=pq,
                win_rate_ci_lower=ci_lo,
                win_rate_ci_upper=ci_hi,
                sample_reliability=rel,
                win_rate_pvalue=win_p,
                win_rate_significance=win_sig,
                expectancy_r_pvalue=exp_p,
                expectancy_r_significance=exp_sig,
            )
        )

    return PatternBacktestResponse(
        aggregates=aggregates,
        patterns_evaluated=patterns_evaluated,
    )
