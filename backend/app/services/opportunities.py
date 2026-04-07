"""
Combine latest context snapshots with latest stored pattern per series (MVP, no persistence).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    opportunity_lookup_key,
    pattern_quality_cache,
    trade_plan_backtest_cache,
    variant_best_cache,
)
from app.core.config import settings
from app.core.trade_plan_variant_constants import BACKTEST_TOTAL_COST_RATE_DEFAULT
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
from app.services.pattern_operational_ui import (
    pattern_is_validated_for_ui,
    pattern_operational_status_for_ui,
)
from app.services.pattern_quality import pattern_quality_label_from_score
from app.services.screener_scoring import SnapshotForScoring, score_snapshot
from app.services.candle_query import fetch_latest_candles_by_series_keys
from app.services.trade_plan_backtest import trade_plan_backtest_lookup_by_bucket
from app.services.trade_plan_live_adjustment import adjust_final_score_for_trade_plan_backtest
from app.services.trade_plan_live_variant import (
    LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
    build_live_trade_plan_for_opportunity,
    load_best_variant_lookup_for_live,
)
from app.services.operational_decision import map_decision_filter_param
from app.services.opportunity_validator import validate_opportunity
from app.services.regime_filter_service import RegimeFilter, load_regime_filter
from app.services.pattern_staleness import (
    compute_pattern_staleness_fields,
    stale_threshold_bars,
)

logger = logging.getLogger(__name__)


def _trade_plan_price_float(value: object | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _price_stale_fields(
    current_price: float,
    entry_price: float,
    direction: str,
    threshold_pct: float,
    stop_loss: float | None,
) -> tuple[bool, float, str | None]:
    """
    Ritorna (is_stale, distance_pct, motivo IT).
    Long: scaduto se prezzo > soglia % sopra entry o <= stop.
    Short: scaduto se prezzo > soglia % sotto entry (move già avvenuto) o >= stop.
    """
    if entry_price <= 0:
        return False, 0.0, None
    distance_pct = (current_price - entry_price) / entry_price * 100.0
    dist_round = round(distance_pct, 2)
    d = direction.lower()
    if d in ("bullish", "long"):
        if stop_loss is not None and current_price <= stop_loss:
            return True, dist_round, "Prezzo a o sotto lo stop — segnale invalidato"
        if distance_pct > threshold_pct:
            return (
                True,
                dist_round,
                f"Prezzo salito {distance_pct:.1f}% sopra entry — momento ottimale passato",
            )
        return False, dist_round, None
    if d in ("bearish", "short"):
        if stop_loss is not None and current_price >= stop_loss:
            return True, dist_round, "Prezzo a o sopra lo stop — segnale invalidato"
        if distance_pct < -threshold_pct:
            return (
                True,
                dist_round,
                f"Prezzo sceso {abs(distance_pct):.1f}% sotto entry — momento ottimale passato",
            )
        return False, dist_round, None
    return False, dist_round, None


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
    if d == "execute":
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

    pq_key = opportunity_lookup_key(
        "pq",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
    )

    async def _compute_pq() -> dict[tuple[str, str], PatternBacktestAggregateRow]:
        return await pattern_quality_lookup_by_name_tf(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=timeframe,
        )

    pq_lookup = await pattern_quality_cache.get_or_compute(key=pq_key, compute=_compute_pq)

    tpb_key = opportunity_lookup_key(
        "tpb",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
    )

    async def _compute_tpb():
        return await trade_plan_backtest_lookup_by_bucket(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=timeframe,
            cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        )

    tpb_lookup = await trade_plan_backtest_cache.get_or_compute(key=tpb_key, compute=_compute_tpb)

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
        pat_ts = p.timestamp if p is not None else None
        age_bars, pat_stale = compute_pattern_staleness_fields(
            ctx.timestamp,
            pat_ts,
            ctx.timeframe,
        )
        pat_stale_thresh = stale_threshold_bars(ctx.timeframe)
        pat_val = pattern_is_validated_for_ui(pn, ctx.timeframe)
        pat_op = pattern_operational_status_for_ui(pn, ctx.timeframe, pq_label)
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
                pattern_timestamp=pat_ts,
                pattern_age_bars=age_bars,
                pattern_stale=pat_stale,
                pattern_stale_threshold_bars=pat_stale_thresh,
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
                pattern_is_validated=pat_val,
                pattern_operational_status=pat_op,
            )
        )

    ranked = _pre_enrich_sort(out)
    candle_keys = [
        (r.provider, r.exchange, r.symbol, r.timeframe) for r in ranked
    ]
    candle_map = await fetch_latest_candles_by_series_keys(session, keys=candle_keys)

    var_key = opportunity_lookup_key(
        "var",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        limit=LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
    )

    async def _compute_var():
        return await load_best_variant_lookup_for_live(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=asset_type,
            timeframe=timeframe,
            limit=LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
            cost_rate=BACKTEST_TOTAL_COST_RATE_DEFAULT,
        )

    try:
        variant_lookup = await variant_best_cache.get_or_compute(
            key=var_key,
            compute=_compute_var,
        )
    except Exception:
        logger.exception(
            "list_opportunities: load_best_variant_lookup_for_live failed; default trade plans only",
        )
        variant_lookup = {}

    regime_filter_yahoo: RegimeFilter | None = None
    try:
        regime_filter_yahoo = await load_regime_filter(session, provider="yahoo_finance")
    except Exception:
        logger.exception("list_opportunities: load_regime_filter (yahoo) failed; regime fields degraded")

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
        ts_ref = row_with_plan.pattern_timestamp or row_with_plan.context_timestamp
        if row_with_plan.provider == "binance":
            regime_spy = "n/a"
            regime_direction_ok = True
        elif regime_filter_yahoo is not None:
            regime_spy = regime_filter_yahoo.get_regime_label(ts_ref)
            if row_with_plan.provider == "yahoo_finance":
                allowed = regime_filter_yahoo.get_allowed_directions(ts_ref)
                d = (row_with_plan.latest_pattern_direction or "").strip().lower()
                regime_direction_ok = d in allowed if d in ("bullish", "bearish") else False
            else:
                regime_direction_ok = True
        else:
            regime_spy = "unknown"
            regime_direction_ok = True

        pat_str = row_with_plan.latest_pattern_strength
        pat_str_f = float(pat_str) if pat_str is not None else None
        _rf_val = (
            None
            if row_with_plan.provider == "binance"
            else regime_filter_yahoo
        )
        v_dec, v_rationale = validate_opportunity(
            symbol=row_with_plan.symbol,
            timeframe=row_with_plan.timeframe,
            provider=row_with_plan.provider,
            pattern_name=row_with_plan.latest_pattern_name,
            direction=row_with_plan.latest_pattern_direction,
            regime_filter=_rf_val,
            timestamp=ts_ref,
            pattern_strength=pat_str_f,
        )

        threshold_pct = settings.opportunity_price_staleness_pct
        current_price: float | None = None
        price_distance_pct: float | None = None
        price_stale = False
        price_stale_reason: str | None = None

        if c is not None:
            current_price = float(c.close)

        tp = row_with_plan.trade_plan
        entry_f = _trade_plan_price_float(tp.entry_price) if tp else None
        stop_f = _trade_plan_price_float(tp.stop_loss) if tp else None
        direction = (row_with_plan.latest_pattern_direction or "bullish").strip().lower()

        if current_price is not None and entry_f is not None and entry_f > 0:
            is_stale, dist_pct, stale_reason = _price_stale_fields(
                current_price,
                entry_f,
                direction,
                threshold_pct,
                stop_f,
            )
            price_distance_pct = dist_pct
            if is_stale:
                price_stale = True
                price_stale_reason = stale_reason
            if v_dec == "execute" and is_stale:
                reason_line = stale_reason or "Prezzo lontano dall'entry."
                v_dec = "monitor"
                v_rationale = [
                    reason_line,
                    "Attendere retest dell'entry o nuovo segnale.",
                    *list(v_rationale),
                ]

        enriched.append(
            row_with_plan.model_copy(
                update={
                    "operational_decision": v_dec,
                    "decision_rationale": v_rationale,
                    "regime_spy": regime_spy,
                    "regime_direction_ok": regime_direction_ok,
                    "current_price": current_price,
                    "price_distance_pct": price_distance_pct,
                    "price_stale": price_stale,
                    "price_stale_reason": price_stale_reason,
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
    pq_key_ranked = opportunity_lookup_key(
        "pq",
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=None,
        timeframe=timeframe,
    )

    async def _compute_pq_ranked() -> dict[tuple[str, str], PatternBacktestAggregateRow]:
        return await pattern_quality_lookup_by_name_tf(
            session,
            symbol=symbol,
            exchange=exchange,
            provider=provider,
            asset_type=None,
            timeframe=timeframe,
        )

    pq_lookup = await pattern_quality_cache.get_or_compute(
        key=pq_key_ranked,
        compute=_compute_pq_ranked,
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
