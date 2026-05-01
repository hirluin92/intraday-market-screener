"""
Trade Plan Variant Backtest v1 — confronto di profili di esecuzione sugli stessi bucket storici.

Per ogni (pattern_name, timeframe, provider, asset_type) e per ogni variante:
entry_strategy × stop_profile × tp_profile, simula forward come trade_plan_backtest v1.

Non modifica lo screener live; solo analisi on-demand.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import product
from typing import cast

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    PATTERN_QUALITY_MIN_SAMPLE,
    TP_PROFILE_CONFIGS,
)
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import (
    PatternBacktestAggregateRow,
    TradePlanVariantBacktestResponse,
    TradePlanVariantRow,
)
from app.services.opportunity_final_score import (
    compute_final_opportunity_score,
    final_opportunity_label_from_score,
)
from app.services.pattern_quality import (
    binomial_test_vs_50pct,
    pattern_quality_label_from_score,
    sample_reliability_label,
    significance_label,
    ttest_expectancy_vs_zero,
    wilson_confidence_interval,
)
from app.services.pattern_timeframe_policy import apply_pattern_timeframe_policy
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.screener_scoring import SnapshotForScoring, score_snapshot
from app.services.trade_plan_backtest import (
    simulate_trade_plan_forward,
    trade_plan_eligible_for_simulation,
)
from app.services.trade_plan_engine import (
    EntryStrategy,
    StopProfile,
    build_trade_plan_v1_with_execution_variant,
)

ENTRY_STRATEGIES: tuple[str, ...] = ("breakout", "retest", "close")
STOP_PROFILES: tuple[str, ...] = ("tighter", "structural", "wider")
_BACKTEST_WINDOW_DAYS = 180  # chunk pruning TimescaleDB: stessa finestra degli altri backtest
TP_PROFILES: dict[str, tuple[Decimal, Decimal]] = {
    label: (Decimal(str(a)), Decimal(str(b))) for label, a, b in TP_PROFILE_CONFIGS
}


def _variant_label(entry_strategy: str, stop_profile: str, tp_key: str) -> str:
    return f"{entry_strategy}|{stop_profile}|{tp_key}"


def iter_execution_variants() -> list[tuple[str, str, str, str, Decimal, Decimal]]:
    """(label, entry_strategy, stop_profile, tp_key, tp1_mult, tp2_mult)."""
    out: list[tuple[str, str, str, str, Decimal, Decimal]] = []
    for es, sp, tp_key in product(ENTRY_STRATEGIES, STOP_PROFILES, TP_PROFILES.keys()):
        t1, t2 = TP_PROFILES[tp_key]
        out.append((_variant_label(es, sp, tp_key), es, sp, tp_key, t1, t2))
    return out


def _pattern_quality_pair(
    lookup: dict[tuple[str, str], PatternBacktestAggregateRow],
    pattern_name: str | None,
    timeframe: str,
) -> tuple[float | None, str]:
    if not pattern_name:
        return None, "unknown"
    agg = lookup.get((pattern_name, timeframe))
    if agg is None:
        return None, "unknown"
    score = agg.pattern_quality_score
    return score, pattern_quality_label_from_score(score)


async def run_trade_plan_variant_backtest(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    pattern_name: str | None,
    limit: int,
    cost_rate: float = BACKTEST_TOTAL_COST_RATE_DEFAULT,
) -> TradePlanVariantBacktestResponse:
    variants = iter_execution_variants()
    execution_variant_count = len(variants)

    _ts_cutoff = datetime.now(UTC) - timedelta(days=_BACKTEST_WINDOW_DAYS)

    stmt = (
        select(CandlePattern, Candle, CandleContext)
        .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
        .join(Candle, CandleFeature.candle_id == Candle.id)
        .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
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
    # Filtro temporale su tutti gli hypertable nella JOIN: abilita chunk pruning su
    # CandlePattern, CandleFeature, Candle e CandleContext.
    conds.append(CandlePattern.timestamp >= _ts_cutoff)
    conds.append(CandleFeature.timestamp >= _ts_cutoff)
    conds.append(Candle.timestamp >= _ts_cutoff)
    conds.append(CandleContext.timestamp >= _ts_cutoff)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(CandlePattern.timestamp.desc()).limit(limit)

    result = await session.execute(stmt)
    rows = list(result.all())
    patterns_evaluated = len(rows)
    if not rows:
        return TradePlanVariantBacktestResponse(
            rows=[],
            execution_variant_count=execution_variant_count,
            patterns_evaluated=0,
            backtest_cost_rate_rt=cost_rate,
        )

    pq_lookup = await pattern_quality_lookup_by_name_tf(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )

    series_keys: set[tuple[str, str, str, str]] = set()
    oldest_ts: datetime | None = None
    for p, _, _ in rows:
        series_keys.add((p.provider, p.exchange, p.symbol, p.timeframe))
        if oldest_ts is None or p.timestamp < oldest_ts:
            oldest_ts = p.timestamp

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

    by_series: dict[tuple[str, str, str, str], list[Candle]] = defaultdict(list)
    for c in all_candles:
        by_series[(c.provider, c.exchange, c.symbol, c.timeframe)].append(c)

    id_to_index: dict[tuple[str, str, str, str], dict[int, int]] = {}
    for key, clist in by_series.items():
        id_to_index[key] = {c.id: i for i, c in enumerate(clist)}

    # (pn, tf, prov, at, variant_label) -> acc
    bucket: dict[
        tuple[str, str, str, str, str],
        dict[str, list],
    ] = defaultdict(
        lambda: {
            "r_list": [],
            "r_per_signal": [],
            "entry_touch": 0,
            "stop": 0,
            "tp1": 0,
            "tp2": 0,
            "timeout": 0,
            "sample": 0,
            "es": "",
            "sp": "",
            "tpk": "",
        },
    )

    for _pat_idx, (pat, candle, ctx) in enumerate(rows):
        # Yield ogni 5 pattern: la simulazione è CPU-heavy (45 varianti × 68 candle
        # con aritmetica Decimal → ~3.4ms/sim × 45 = 153ms per pattern). Con 5 pattern
        # tra yield: max ~765ms di blocco, ben sotto il timeout health di 5s.
        if _pat_idx % 5 == 0:
            await asyncio.sleep(0)
        key_s = (pat.provider, pat.exchange, pat.symbol, pat.timeframe)
        clist = by_series.get(key_s)
        idx_map = id_to_index.get(key_s)
        if not clist or not idx_map:
            continue
        idx = idx_map.get(candle.id)
        if idx is None:
            continue

        snap = SnapshotForScoring(
            exchange=ctx.exchange,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            timestamp=ctx.timestamp,
            market_regime=ctx.market_regime,
            volatility_regime=ctx.volatility_regime,
            candle_expansion=ctx.candle_expansion,
            direction_bias=ctx.direction_bias,
        )
        scored = score_snapshot(snap)
        pq_score, pq_label = _pattern_quality_pair(pq_lookup, pat.pattern_name, pat.timeframe)
        base_final = compute_final_opportunity_score(
            screener_score=scored.screener_score,
            score_direction=scored.score_direction,
            latest_pattern_direction=pat.direction,
            pattern_quality_score=pq_score,
            pattern_quality_label=pq_label,
            latest_pattern_strength=pat.pattern_strength,
        )
        final, _tf_ok, tf_gate, _tf_f = apply_pattern_timeframe_policy(
            has_pattern=True,
            pattern_quality_score=pq_score,
            _pattern_quality_label=pq_label,
            base_final_opportunity_score=base_final,
        )
        final_lbl = final_opportunity_label_from_score(final)

        for vlabel, es, sp, tp_key, t1, t2 in variants:
            plan = build_trade_plan_v1_with_execution_variant(
                final_opportunity_label=final_lbl,
                final_opportunity_score=final,
                score_direction=scored.score_direction,
                latest_pattern_direction=pat.direction,
                pattern_timeframe_gate_label=tf_gate,
                volatility_regime=ctx.volatility_regime,
                market_regime=ctx.market_regime,
                candle_high=candle.high,
                candle_low=candle.low,
                candle_close=candle.close,
                entry_strategy=cast(EntryStrategy, es),
                stop_profile=cast(StopProfile, sp),
                tp1_r_mult=t1,
                tp2_r_mult=t2,
            )

            bkey = (pat.pattern_name, pat.timeframe, pat.provider, pat.asset_type, vlabel)
            if not trade_plan_eligible_for_simulation(plan):
                continue

            bucket[bkey]["sample"] += 1
            bucket[bkey]["es"] = es
            bucket[bkey]["sp"] = sp
            bucket[bkey]["tpk"] = tp_key

            entry_ok, outcome, r_mult = simulate_trade_plan_forward(
                clist, idx, plan, cost_rate=cost_rate
            )
            if not entry_ok:
                bucket[bkey]["r_per_signal"].append(0.0)
                continue
            bucket[bkey]["entry_touch"] += 1
            assert outcome is not None and r_mult is not None
            bucket[bkey]["r_list"].append(r_mult)
            bucket[bkey]["r_per_signal"].append(r_mult)
            if outcome == "stop":
                bucket[bkey]["stop"] += 1
            elif outcome == "tp1":
                bucket[bkey]["tp1"] += 1
            elif outcome == "tp2":
                bucket[bkey]["tp2"] += 1
            else:
                bucket[bkey]["timeout"] += 1

    out_rows: list[TradePlanVariantRow] = []
    for key in sorted(bucket.keys()):
        pn, tf, prov, at, vlabel = key
        data = bucket[key]
        n = data["sample"]
        et = data["entry_touch"]
        rlist: list[float] = data["r_list"]
        r_per_signal: list[float] = data["r_per_signal"]
        sum_r = sum(rlist)
        avg_r = sum_r / et if et else None
        expectancy_per_signal = sum_r / n if n else None
        tp1_or_tp2 = data["tp1"] + data["tp2"]
        sh = data["stop"]

        tpb_rel = sample_reliability_label(et)
        if et < PATTERN_QUALITY_MIN_SAMPLE:
            ci_lo = ci_hi = None
        else:
            ci_lo, ci_hi = wilson_confidence_interval(tp1_or_tp2, et)

        win_p = binomial_test_vs_50pct(tp1_or_tp2, et) if et > 0 else None
        win_sig = significance_label(win_p) if win_p is not None else None
        exp_p: float | None = None
        exp_sig: str | None = None
        if len(r_per_signal) >= 2:
            _, exp_p = ttest_expectancy_vs_zero(r_per_signal)
            exp_sig = significance_label(exp_p)

        out_rows.append(
            TradePlanVariantRow(
                pattern_name=pn,
                timeframe=tf,
                provider=prov,
                asset_type=at,
                variant_label=vlabel,
                entry_strategy=data["es"],
                stop_profile=data["sp"],
                tp_profile=data["tpk"],
                sample_size=n,
                entry_triggered=et,
                stop_hits=sh,
                tp1_hits=data["tp1"],
                tp2_hits=data["tp2"],
                tp1_or_tp2_hits=tp1_or_tp2,
                timed_out=data["timeout"],
                entry_trigger_rate=(et / n) if n else None,
                stop_rate_given_entry=(sh / et) if et else None,
                tp1_or_tp2_rate_given_entry=(tp1_or_tp2 / et) if et else None,
                avg_r=round(avg_r, 4) if avg_r is not None else None,
                expectancy_r=round(expectancy_per_signal, 4) if expectancy_per_signal is not None else None,
                win_rate_ci_lower=ci_lo,
                win_rate_ci_upper=ci_hi,
                sample_reliability=tpb_rel,
                win_rate_pvalue=win_p,
                win_rate_significance=win_sig,
                expectancy_r_pvalue=exp_p,
                expectancy_r_significance=exp_sig,
            )
        )

    return TradePlanVariantBacktestResponse(
        rows=out_rows,
        execution_variant_count=execution_variant_count,
        patterns_evaluated=patterns_evaluated,
        backtest_cost_rate_rt=cost_rate,
    )
