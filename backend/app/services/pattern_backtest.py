"""
On-demand pattern backtest: forward returns vs stored candles (MVP, no persistence).

- Entry reference: candle **close** at the pattern bar (via CandleFeature → Candle).
- Horizons: +1, +3, +5, +10 **candles** ahead in the same (exchange, symbol, timeframe) series.
- **Bullish / neutral**: long return % = (close_fwd − close_entry) / close_entry × 100; win if > 0.
- **Bearish**: short return % = (close_entry − close_fwd) / close_entry × 100; win if > 0 (price fell).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeframes import ALLOWED_TIMEFRAMES
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

# Per-timeframe cap per run_pattern_backtest. Con 5000 righe per timeframe si ottengono
# aggregati affidabili su tutti i timeframe senza che 5m inonde il budget condiviso.
# Problema precedente: limit=5000 senza filtro TF → 5m occupa ~88% del campione recente
# (arriva 12× più velocemente di 1h e 78× di 1d) → 1h e 1d non raggiungevano n>=30.
PATTERN_QUALITY_AGGREGATE_LIMIT = 5000

# Finestra temporale per la ricerca dei pattern nel backtest.
# 6 mesi offre campione statistico adeguato per tutti i timeframe (inclusi 1d e 1h)
# mantenendo i benefici del chunk pruning di TimescaleDB sull'hypertable CandlePattern.
# Usato solo quando dt_from non è esplicitamente impostato (evita conflitti con backtest OOS).
_BACKTEST_WINDOW_DAYS = 180


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
    Aggregati (pattern_name, timeframe) keyed per lo scoring delle opportunità.

    Quando ``timeframe`` è specificato: singola query ottimizzata per quel TF.

    Quando ``timeframe`` è None: esegue una query per ciascun TF in ALLOWED_TIMEFRAMES e
    unisce i risultati. Questo è necessario per evitare che i pattern 5m — più frequenti
    di 12-78× rispetto a 1h/1d — saturino il limit e impediscano la costruzione degli
    aggregati per i timeframe a minore frequenza.

    ``dt_from`` / ``dt_to``: se impostati, solo righe ``CandlePattern`` con timestamp in
    quell'intervallo (utile per OOS: lookup solo su train pre-cutoff).
    """
    if timeframe is not None:
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

    # timeframe=None → query sequenziale per TF con la sessione passata.
    # Con il chunk pruning TimescaleDB (timestamp filter), ogni query impiega ~0.04s:
    # 5 TF × 0.04s = 0.2s totale — la parallelizzazione non è più necessaria e
    # creerebbe sessioni extra che esauriscono il connection pool durante i picchi
    # (pipeline parallelismo=12 + prewarm + cache recompute = >45 sessioni simultanee).
    merged: dict[tuple[str, str], PatternBacktestAggregateRow] = {}
    for tf in ALLOWED_TIMEFRAMES:
        resp = await run_pattern_backtest(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=tf,
            pattern_name=None,
            limit=PATTERN_QUALITY_AGGREGATE_LIMIT,
            dt_from=dt_from,
            dt_to=dt_to,
        )
        for a in resp.aggregates:
            merged[(a.pattern_name, a.timeframe)] = a
    return merged


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


def _compute_atr14(candles: list[Candle], idx: int) -> float | None:
    """Simple 14-period ATR at bar idx. None se meno di 2 barre disponibili."""
    start = max(0, idx - 14)
    trs: list[float] = []
    for i in range(start + 1, idx + 1):
        hi = _f(candles[i].high)
        lo = _f(candles[i].low)
        pc = _f(candles[i - 1].close)
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return (sum(trs) / len(trs)) if trs else None


def _stop_hit_path(
    candles: list[Candle],
    idx: int,
    h: int,
    entry: float,
    direction: str,
    atr: float | None,
) -> bool:
    """
    True se lo stop tipico (entry ± 1.5×ATR, fallback 1.5%) viene toccato
    da qualsiasi barra tra idx+1 e idx+h incluso.
    Long: colpito se low <= stop_level. Short: colpito se high >= stop_level.
    """
    stop_dist = (1.5 * atr) if (atr is not None and atr > 0) else (entry * 0.015)
    if direction == "bearish":
        stop_level = entry + stop_dist
    else:
        stop_level = entry - stop_dist
    end = min(idx + h + 1, len(candles))
    for k in range(idx + 1, end):
        lo = _f(candles[k].low)
        hi = _f(candles[k].high)
        if direction == "bearish":
            if hi >= stop_level:
                return True
        else:
            if lo <= stop_level:
                return True
    return False


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
    # Finestra temporale: abilita chunk pruning su TUTTI gli hypertable nella JOIN.
    # Candle è l'ipertabella più grande (7M+ righe): senza filtro timestamp, il planner
    # esegue un full scan di tutti i chunk (Parallel Seq Scan su ~50 chunk = bottleneck).
    # _ts_cutoff è SEMPRE impostato: a dt_from (se OOS) oppure al default _BACKTEST_WINDOW_DAYS.
    # Nota: dt_to non disabilita il cutoff inferiore — è solo un limite superiore.
    _ts_cutoff: datetime = dt_from if dt_from is not None else datetime.now(UTC) - timedelta(days=_BACKTEST_WINDOW_DAYS)

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
    if _ts_cutoff is not None:
        conds.append(CandlePattern.timestamp >= _ts_cutoff)
        # Pruning anche sugli altri hypertable nella JOIN: il planner altrimenti scansiona
        # tutti i loro chunk indipendentemente dal filtro su CandlePattern.
        conds.append(CandleFeature.timestamp >= _ts_cutoff)
        conds.append(Candle.timestamp >= _ts_cutoff)
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

    # Raccoglie serie come (provider, exchange, symbol, timeframe) per filtrare anche
    # per provider nella candle forward query → usa ix_candles_provider_exchange_symbol_tf_ts.
    series_keys: set[tuple[str, str, str, str]] = set()
    oldest_ts: datetime | None = None
    for p, _, _ in rows:
        series_keys.add((p.provider, p.exchange, p.symbol, p.timeframe))
        if oldest_ts is None or p.timestamp < oldest_ts:
            oldest_ts = p.timestamp

    # Limite temporale: carichiamo solo candle a partire dal pattern più vecchio
    # meno un buffer (2 giorni), così evitiamo di caricare l'intero storico per le
    # forward simulation sui soli HORIZONS = (1, 3, 5, 10) barre.
    candle_since: datetime | None = None
    if oldest_ts is not None:
        candle_since = oldest_ts - timedelta(days=2)

    or_parts = [
        and_(Candle.provider == prov, Candle.exchange == ex, Candle.symbol == sym, Candle.timeframe == tf)
        for prov, ex, sym, tf in series_keys
    ]
    c_stmt = select(Candle).where(or_(*or_parts))
    if candle_since is not None:
        c_stmt = c_stmt.where(Candle.timestamp >= candle_since)
    c_stmt = c_stmt.order_by(
        Candle.provider,
        Candle.exchange,
        Candle.symbol,
        Candle.timeframe,
        Candle.timestamp.asc(),
    )
    c_result = await session.execute(c_stmt)
    all_candles = list(c_result.scalars().all())

    # Chiave serie include provider (per evitare confusione tra provider diversi con
    # stesso symbol/exchange/timeframe) ma id_to_index usa la chiave senza provider
    # perché il pattern.candle_id punta al candle specifico già del provider corretto.
    by_series: dict[tuple[str, str, str, str], list[Candle]] = defaultdict(list)
    for c in all_candles:
        by_series[(c.provider, c.exchange, c.symbol, c.timeframe)].append(c)

    id_to_index: dict[tuple[str, str, str, str], dict[int, int]] = {}
    for key, clist in by_series.items():
        id_to_index[key] = {c.id: i for i, c in enumerate(clist)}

    # (pattern_name, timeframe) -> horizon -> rets / wins / wins_stop_aware
    acc: dict[tuple[str, str], dict[int, dict[str, list]]] = defaultdict(
        lambda: {h: {"rets": [], "wins": [], "wins_stop_aware": []} for h in HORIZONS},
    )

    for pat, entry_close, candle_id in rows:
        key_s = (pat.provider, pat.exchange, pat.symbol, pat.timeframe)
        clist = by_series.get(key_s)
        idx_map = id_to_index.get(key_s)
        if not clist or not idx_map:
            continue
        idx = idx_map.get(candle_id)
        if idx is None:
            continue
        ec = _f(entry_close)
        atr = _compute_atr14(clist, idx)

        for h in HORIZONS:
            j = idx + h
            if j >= len(clist):
                continue
            fut_close = _f(clist[j].close)
            ret = _signed_return_pct(ec, fut_close, pat.direction)
            is_win = _is_win(ret)
            stop_hit = _stop_hit_path(clist, idx, h, ec, pat.direction, atr)
            gk = (pat.pattern_name, pat.timeframe)
            acc[gk][h]["rets"].append(ret)
            acc[gk][h]["wins"].append(is_win)
            acc[gk][h]["wins_stop_aware"].append(is_win and not stop_hit)

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
        wr3_sa = _win_rate(hdata[3]["wins_stop_aware"])
        wr5_sa = _win_rate(hdata[5]["wins_stop_aware"])
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
                win_rate_stop_aware_3=wr3_sa,
                win_rate_stop_aware_5=wr5_sa,
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
