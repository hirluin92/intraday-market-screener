"""
Combine latest context snapshots with latest stored pattern per series (MVP, no persistence).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import PatternBacktestAggregateRow
from app.schemas.opportunities import OpportunityRow
from app.schemas.screener import RankedScreenerRow
from app.services.context_query import list_latest_context_per_series
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.pattern_query import list_latest_pattern_per_series
from app.services.opportunity_final_score import (
    compute_final_opportunity_score,
    final_opportunity_label_from_score,
)
from app.services.alert_candidates import compute_alert_candidate_fields
from app.services.pattern_timeframe_policy import apply_pattern_timeframe_policy
from app.services.pattern_quality import pattern_quality_label_from_score
from app.services.screener_scoring import SnapshotForScoring, score_snapshot
from app.services.candle_query import fetch_latest_candles_by_series_keys
from app.services.trade_plan_backtest import trade_plan_backtest_lookup_by_bucket
from app.services.trade_plan_live_adjustment import adjust_final_score_for_trade_plan_backtest
from app.services.trade_plan_live_variant import (
    build_live_trade_plan_for_opportunity,
    load_best_variant_lookup_for_live,
)
from app.services.operational_decision import (
    compute_operational_decision_and_rationale,
    map_decision_filter_param,
)

logger = logging.getLogger(__name__)


def _pattern_key(p: CandlePattern) -> tuple[str, str, str]:
    return (p.exchange, p.symbol, p.timeframe)


def _pattern_quality_pair(
    lookup: dict[tuple[str, str], PatternBacktestAggregateRow],
    pattern_name: str | None,
    timeframe: str,
) -> tuple[float | None, str]:
    """Match (latest_pattern_name, timeframe) to on-demand backtest aggregates."""
    if not pattern_name:
        return None, "unknown"
    agg = lookup.get((pattern_name, timeframe))
    if agg is None:
        return None, "unknown"
    score = agg.pattern_quality_score
    return score, pattern_quality_label_from_score(score)


def _pre_enrich_sort(rows: list[OpportunityRow]) -> list[OpportunityRow]:
    """Ordinamento prima dell’arricchimento trade plan (solo score + recency)."""

    def key(r: OpportunityRow) -> tuple:
        ts = r.context_timestamp.timestamp()
        return (-r.final_opportunity_score, -ts)

    return sorted(rows, key=key)


def _decision_sort_priority(r: OpportunityRow) -> int:
    """Operabile > Da monitorare > Scartare."""
    d = r.operational_decision or "monitor"
    if d == "operable":
        return 0
    if d == "monitor":
        return 1
    return 2


def _alert_level_priority(r: OpportunityRow) -> int:
    """Alta priorità > media > nessun alert."""
    a = (r.alert_level or "").lower()
    if a == "alta_priorita":
        return 0
    if a == "media_priorita":
        return 1
    return 2


def _post_enrich_sort(rows: list[OpportunityRow]) -> list[OpportunityRow]:
    """Decisione (operabile > monitor > scarta), poi tier alert, poi score finale, poi recency."""

    def key(r: OpportunityRow) -> tuple:
        ts = r.context_timestamp.timestamp()
        return (
            _decision_sort_priority(r),
            _alert_level_priority(r),
            -r.final_opportunity_score,
            -ts,
        )

    return sorted(rows, key=key)


def _sort_ranked(rows: list[RankedScreenerRow]) -> list[RankedScreenerRow]:
    def key(r: RankedScreenerRow) -> tuple:
        ts = r.timestamp.timestamp()
        pq = r.pattern_quality_score
        pq_key = float("inf") if pq is None else -pq
        return (
            0 if r.latest_pattern_name is not None else 1,
            -r.screener_score,
            pq_key,
            -ts,
        )

    return sorted(rows, key=key)


async def list_opportunities(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
    decision: str | None = None,
) -> list[OpportunityRow]:
    contexts: list[CandleContext] = await list_latest_context_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )
    latest_patterns: list[CandlePattern] = await list_latest_pattern_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )
    by_series: dict[tuple[str, str, str], CandlePattern] = {
        _pattern_key(p): p for p in latest_patterns
    }

    pq_lookup = await pattern_quality_lookup_by_name_tf(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )
    tpb_lookup = await trade_plan_backtest_lookup_by_bucket(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )

    out: list[OpportunityRow] = []
    for ctx in contexts:
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
        p = by_series.get((ctx.exchange, ctx.symbol, ctx.timeframe))
        pn = p.pattern_name if p is not None else None
        pq_score, pq_label = _pattern_quality_pair(pq_lookup, pn, ctx.timeframe)
        pat_dir = p.direction if p is not None else None
        pat_strength = p.pattern_strength if p is not None else None
        base_final = compute_final_opportunity_score(
            screener_score=scored.screener_score,
            score_direction=scored.score_direction,
            latest_pattern_direction=pat_dir,
            pattern_quality_score=pq_score,
            pattern_quality_label=pq_label,
            latest_pattern_strength=pat_strength,
        )
        has_pat = pn is not None
        final, tf_ok, tf_gate, tf_filtered = apply_pattern_timeframe_policy(
            has_pattern=has_pat,
            pattern_quality_score=pq_score,
            _pattern_quality_label=pq_label,
            base_final_opportunity_score=base_final,
        )
        score_before_tpb = float(final)
        if not has_pat or pn is None:
            adjusted = score_before_tpb
            tpb_delta = 0.0
            tpb_label = "no_pattern"
            tpb_exp = None
            tpb_n = None
            tpb_conf = "unknown"
        else:
            bucket = tpb_lookup.get((pn, ctx.timeframe, ctx.provider, ctx.asset_type))
            adjusted, tpb_delta, tpb_label, tpb_exp, tpb_n, tpb_conf = (
                adjust_final_score_for_trade_plan_backtest(score_before_tpb, bucket)
            )
        final = adjusted
        final_lbl = final_opportunity_label_from_score(final)
        # Alert: soglie sullo score **prima** del soft TPB — il backtest trade plan non deve
        # sopprimere da solo le candidature (indicatore di cautela, non giudice finale).
        alert_candidate, alert_level = compute_alert_candidate_fields(
            score_direction=scored.score_direction,
            latest_pattern_direction=pat_dir,
            final_opportunity_score=score_before_tpb,
            pattern_quality_label=pq_label,
            pattern_timeframe_quality_ok=tf_ok,
        )
        out.append(
            OpportunityRow(
                asset_type=ctx.asset_type,
                provider=ctx.provider,
                exchange=ctx.exchange,
                symbol=ctx.symbol,
                timeframe=ctx.timeframe,
                market_metadata=ctx.market_metadata,
                timestamp=ctx.timestamp,
                context_timestamp=ctx.timestamp,
                pattern_timestamp=p.timestamp if p is not None else None,
                market_regime=ctx.market_regime,
                volatility_regime=ctx.volatility_regime,
                candle_expansion=ctx.candle_expansion,
                direction_bias=ctx.direction_bias,
                screener_score=scored.screener_score,
                score_label=scored.score_label,
                score_direction=scored.score_direction,
                latest_pattern_name=pn,
                latest_pattern_strength=pat_strength,
                latest_pattern_direction=pat_dir,
                pattern_quality_score=pq_score,
                pattern_quality_label=pq_label,
                final_opportunity_score=final,
                final_opportunity_label=final_lbl,
                pattern_timeframe_quality_ok=tf_ok,
                pattern_timeframe_gate_label=tf_gate,
                pattern_timeframe_filtered_candidate=tf_filtered,
                alert_candidate=alert_candidate,
                alert_level=alert_level,
                trade_plan=None,
                final_opportunity_score_before_trade_plan_backtest=score_before_tpb,
                trade_plan_backtest_score_delta=tpb_delta,
                trade_plan_backtest_adjustment_label=tpb_label,
                trade_plan_backtest_expectancy_r=tpb_exp,
                trade_plan_backtest_sample_size=tpb_n,
                operational_confidence=tpb_conf,
                selected_trade_plan_variant=None,
                selected_trade_plan_variant_status=None,
                selected_trade_plan_variant_sample_size=None,
                selected_trade_plan_variant_expectancy_r=None,
                trade_plan_source="default_fallback",
                trade_plan_fallback_reason=None,
            )
        )

    ranked = _pre_enrich_sort(out)
    candle_keys = [
        (r.provider, r.exchange, r.symbol, r.timeframe) for r in ranked
    ]
    candle_map = await fetch_latest_candles_by_series_keys(session, keys=candle_keys)

    try:
        variant_lookup = await load_best_variant_lookup_for_live(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=timeframe,
            limit=300,
        )
    except Exception:
        logger.exception(
            "list_opportunities: load_best_variant_lookup_for_live failed; default trade plans only",
        )
        variant_lookup = {}

    enriched: list[OpportunityRow] = []
    for r in ranked:
        c = candle_map.get((r.provider, r.exchange, r.symbol, r.timeframe))
        best_row = None
        if r.latest_pattern_name:
            best_row = variant_lookup.get(
                (r.latest_pattern_name, r.timeframe, r.provider, r.asset_type),
            )
        plan, sv, st, ss, se, src, fbr = build_live_trade_plan_for_opportunity(
            final_opportunity_label=r.final_opportunity_label,
            final_opportunity_score=r.final_opportunity_score,
            score_direction=r.score_direction,
            latest_pattern_direction=r.latest_pattern_direction,
            latest_pattern_name=r.latest_pattern_name,
            candle_expansion=r.candle_expansion,
            pattern_timeframe_gate_label=r.pattern_timeframe_gate_label,
            volatility_regime=r.volatility_regime,
            market_regime=r.market_regime,
            candle_high=c.high if c is not None else None,
            candle_low=c.low if c is not None else None,
            candle_close=c.close if c is not None else None,
            best_row=best_row,
        )
        row_with_plan = r.model_copy(
            update={
                "trade_plan": plan,
                "selected_trade_plan_variant": sv,
                "selected_trade_plan_variant_status": st,
                "selected_trade_plan_variant_sample_size": ss,
                "selected_trade_plan_variant_expectancy_r": se,
                "trade_plan_source": src,
                "trade_plan_fallback_reason": fbr,
            },
        )
        dec, rationale_lines = compute_operational_decision_and_rationale(row_with_plan)
        enriched.append(
            row_with_plan.model_copy(
                update={
                    "operational_decision": dec,
                    "decision_rationale": rationale_lines,
                },
            ),
        )
    decision_code = map_decision_filter_param(decision)
    if decision_code is not None:
        enriched = [x for x in enriched if x.operational_decision == decision_code]
    ordered = _post_enrich_sort(enriched)
    return ordered[:limit]


async def list_ranked_screener(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
) -> list[RankedScreenerRow]:
    contexts: list[CandleContext] = await list_latest_context_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )
    latest_patterns: list[CandlePattern] = await list_latest_pattern_per_series(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )
    by_series: dict[tuple[str, str, str], CandlePattern] = {
        _pattern_key(p): p for p in latest_patterns
    }
    pq_lookup = await pattern_quality_lookup_by_name_tf(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        timeframe=timeframe,
    )

    out: list[RankedScreenerRow] = []
    for ctx in contexts:
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
        p = by_series.get((ctx.exchange, ctx.symbol, ctx.timeframe))
        pn = p.pattern_name if p is not None else None
        pq_score, pq_label = _pattern_quality_pair(pq_lookup, pn, ctx.timeframe)
        out.append(
            RankedScreenerRow(
                asset_type=ctx.asset_type,
                provider=ctx.provider,
                exchange=ctx.exchange,
                symbol=ctx.symbol,
                timeframe=ctx.timeframe,
                market_metadata=ctx.market_metadata,
                timestamp=ctx.timestamp,
                market_regime=ctx.market_regime,
                volatility_regime=ctx.volatility_regime,
                candle_expansion=ctx.candle_expansion,
                direction_bias=ctx.direction_bias,
                screener_score=scored.screener_score,
                score_label=scored.score_label,
                score_direction=scored.score_direction,
                latest_pattern_name=pn,
                pattern_quality_score=pq_score,
                pattern_quality_label=pq_label,
            )
        )

    ranked = _sort_ranked(out)
    return ranked[:limit]
