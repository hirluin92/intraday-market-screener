"""
Integrazione live: applica la best variant (backtest) al trade plan quando le regole prudenziali lo consentono.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE_FOR_LIVE,
)
from app.schemas.backtest import TradePlanVariantBestRow
from app.schemas.trade_plan import TradePlanV1
from app.services.trade_plan_engine import (
    EntryStrategy,
    StopProfile,
    build_trade_plan_v1,
    build_trade_plan_v1_with_execution_variant,
)
from app.services.trade_plan_variant_backtest import TP_PROFILES, run_trade_plan_variant_backtest
from app.services.trade_plan_variant_best import build_best_rows_from_variant_rows

LIVE_VARIANT_BACKTEST_PATTERN_LIMIT = 300

TradePlanFallbackReasonCode = Literal[
    "no_pattern",
    "no_variant_bucket",
    "variant_rejected",
    "watchlist_insufficient_sample",
]


def should_apply_best_variant_live(b: TradePlanVariantBestRow) -> bool:
    """Promossa sempre; watchlist solo con campione sufficiente; rejected mai."""
    if b.operational_status == "promoted":
        return True
    if b.operational_status == "watchlist":
        return b.sample_size >= TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE_FOR_LIVE
    return False


def compute_trade_plan_fallback_reason(
    *,
    has_pattern: bool,
    best_row: TradePlanVariantBestRow | None,
    applied_variant: bool,
) -> TradePlanFallbackReasonCode | None:
    """Motivo uso motore standard; None se i livelli usano variant_backtest."""
    if applied_variant:
        return None
    if not has_pattern:
        return "no_pattern"
    if best_row is None:
        return "no_variant_bucket"
    if best_row.operational_status == "rejected":
        return "variant_rejected"
    if best_row.operational_status == "watchlist":
        return "watchlist_insufficient_sample"
    return "variant_rejected"


async def load_best_variant_lookup_for_live(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None,
    asset_type: str | None,
    timeframe: str | None,
    limit: int = LIVE_VARIANT_BACKTEST_PATTERN_LIMIT,
    cost_rate: float = BACKTEST_TOTAL_COST_RATE_DEFAULT,
) -> dict[tuple[str, str, str, str], TradePlanVariantBestRow]:
    """Mappa bucket → riga best variant (stesso universo del trade plan variant backtest)."""
    v = await run_trade_plan_variant_backtest(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=None,
        limit=limit,
        cost_rate=cost_rate,
    )
    best_rows = build_best_rows_from_variant_rows(v.rows)
    return {
        (r.pattern_name, r.timeframe, r.provider, r.asset_type): r for r in best_rows
    }


def _tp_mults(tp_profile: str) -> tuple[Decimal, Decimal]:
    return TP_PROFILES.get(tp_profile, (Decimal("1.5"), Decimal("2.5")))


def _entry_strat(s: str) -> EntryStrategy:
    x = (s or "").lower()
    if x in ("breakout", "retest", "close"):
        return cast(EntryStrategy, x)
    return "close"


def _stop_prof(s: str) -> StopProfile:
    x = (s or "").lower()
    if x in ("tighter", "structural", "wider"):
        return cast(StopProfile, x)
    return "structural"


def build_live_trade_plan_for_opportunity(
    *,
    final_opportunity_label: str,
    final_opportunity_score: float,
    score_direction: str,
    latest_pattern_direction: str | None,
    latest_pattern_name: str | None,
    candle_expansion: str,
    pattern_timeframe_gate_label: str,
    volatility_regime: str,
    market_regime: str,
    candle_high: Decimal | None,
    candle_low: Decimal | None,
    candle_close: Decimal | None,
    best_row: TradePlanVariantBestRow | None,
    symbol: str = "",
    exchange: str = "",
) -> tuple[
    TradePlanV1,
    str | None,
    str | None,
    int | None,
    float | None,
    Literal["variant_backtest", "default_fallback"],
    TradePlanFallbackReasonCode | None,
]:
    """
    Restituisce il piano e i metadati variant. Se c'è best_row, i campi selected_* riflettono
    il bucket; trade_plan_source è variant_backtest solo se i livelli usano la variante.
    """
    has_pattern = latest_pattern_name is not None and bool(str(latest_pattern_name).strip())

    if best_row is None:
        plan = build_trade_plan_v1(
            final_opportunity_label=final_opportunity_label,
            final_opportunity_score=final_opportunity_score,
            score_direction=score_direction,
            latest_pattern_direction=latest_pattern_direction,
            latest_pattern_name=latest_pattern_name,
            candle_expansion=candle_expansion,
            pattern_timeframe_gate_label=pattern_timeframe_gate_label,
            volatility_regime=volatility_regime,
            market_regime=market_regime,
            candle_high=candle_high,
            candle_low=candle_low,
            candle_close=candle_close,
            symbol=symbol,
            exchange=exchange,
        )
        reason = compute_trade_plan_fallback_reason(
            has_pattern=has_pattern,
            best_row=None,
            applied_variant=False,
        )
        return plan, None, None, None, None, "default_fallback", reason

    meta_label = best_row.best_variant_label
    meta_status = best_row.operational_status
    meta_n = best_row.sample_size
    meta_exp = best_row.expectancy_r

    if should_apply_best_variant_live(best_row):
        t1, t2 = _tp_mults(best_row.tp_profile)
        plan = build_trade_plan_v1_with_execution_variant(
            final_opportunity_label=final_opportunity_label,
            final_opportunity_score=final_opportunity_score,
            score_direction=score_direction,
            latest_pattern_direction=latest_pattern_direction,
            pattern_timeframe_gate_label=pattern_timeframe_gate_label,
            volatility_regime=volatility_regime,
            market_regime=market_regime,
            candle_high=candle_high,
            candle_low=candle_low,
            candle_close=candle_close,
            entry_strategy=_entry_strat(best_row.entry_strategy),
            stop_profile=_stop_prof(best_row.stop_profile),
            tp1_r_mult=t1,
            tp2_r_mult=t2,
            symbol=symbol,
            exchange=exchange,
        )
        return plan, meta_label, meta_status, meta_n, meta_exp, "variant_backtest", None

    plan = build_trade_plan_v1(
        final_opportunity_label=final_opportunity_label,
        final_opportunity_score=final_opportunity_score,
        score_direction=score_direction,
        latest_pattern_direction=latest_pattern_direction,
        latest_pattern_name=latest_pattern_name,
        candle_expansion=candle_expansion,
        pattern_timeframe_gate_label=pattern_timeframe_gate_label,
        volatility_regime=volatility_regime,
        market_regime=market_regime,
        candle_high=candle_high,
        candle_low=candle_low,
        candle_close=candle_close,
        symbol=symbol,
        exchange=exchange,
    )
    reason = compute_trade_plan_fallback_reason(
        has_pattern=has_pattern,
        best_row=best_row,
        applied_variant=False,
    )
    return plan, meta_label, meta_status, meta_n, meta_exp, "default_fallback", reason
