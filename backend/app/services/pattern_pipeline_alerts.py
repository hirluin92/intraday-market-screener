"""
Alert su nuovi pattern dopo extract_patterns (1h/5m, whitelist, trade plan + qualità).
Non blocca il pipeline: errori solo in log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.trade_plan_variant_constants import (
    VALIDATED_PATTERNS_1H,
    VALIDATED_PATTERNS_5M,
)
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.alert_service import send_alert_deduped
from app.services.indicator_query import get_indicator_for_candle_timestamp
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.regime_filter_service import load_regime_filter
from app.services.trade_plan_backtest import (
    build_trade_plan_v1_for_stored_pattern,
    trade_plan_eligible_for_simulation,
)

logger = logging.getLogger(__name__)

# Fonte unica di verità: importata da trade_plan_variant_constants (stessa lista usata
# dal validator e dallo screener). Precedentemente hardcodata qui con solo 2 pattern,
# causando mancato invio di alert per double_bottom/top, divergenze MACD/RSI, ecc.
VALID_PATTERNS_1H = VALIDATED_PATTERNS_1H
VALID_PATTERNS_5M = VALIDATED_PATTERNS_5M


def _f_dec(x: Decimal | None) -> float | None:
    if x is None:
        return None
    return float(x)


async def maybe_send_pattern_alerts_after_pipeline(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> None:
    if not settings.alert_pattern_signals_enabled:
        return
    if not (
        (settings.telegram_bot_token and settings.telegram_chat_id)
        or settings.discord_webhook_url
    ):
        return

    # Solo refresh su una serie precisa (no grid scheduler senza symbol/timeframe).
    if not body.symbol or not body.timeframe:
        return

    if body.timeframe not in ("1h", "5m"):
        return

    valid_patterns = VALID_PATTERNS_1H if body.timeframe == "1h" else VALID_PATTERNS_5M

    try:
        ts_stmt = (
            select(Candle.timestamp)
            .where(
                Candle.exchange == body.exchange,
                Candle.symbol == body.symbol,
                Candle.timeframe == body.timeframe,
                Candle.provider == body.provider,
            )
            .order_by(Candle.timestamp.desc())
            .limit(2)
        )
        ts_result = await session.execute(ts_stmt)
        recent_ts = [row[0] for row in ts_result.all()]
        if not recent_ts:
            return

        stmt = (
            select(CandlePattern, Candle, CandleContext)
            .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
            .join(Candle, CandleFeature.candle_id == Candle.id)
            .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
            .where(
                CandlePattern.exchange == body.exchange,
                CandlePattern.symbol == body.symbol,
                CandlePattern.timeframe == body.timeframe,
                CandlePattern.provider == body.provider,
                CandlePattern.pattern_name.in_(valid_patterns),
                CandlePattern.timestamp.in_(recent_ts),
            )
        )
        pat_result = await session.execute(stmt)
        rows = list(pat_result.all())
        if not rows:
            return

        # dt_to: limita il lookup al timestamp della barra piu' recente nel batch.
        # Evita che la quality_score usi dati "futuri" rispetto al segnale valutato
        # (stesso meccanismo anti-leakage di OOS/walk-forward).
        alert_dt_to: datetime | None = None
        if rows:
            ts_vals = [pat.timestamp for pat, _c, _ctx in rows if pat.timestamp]
            if ts_vals:
                alert_dt_to = max(ts_vals)
                if alert_dt_to.tzinfo is None:
                    alert_dt_to = alert_dt_to.replace(tzinfo=UTC)

        pq_lookup = await pattern_quality_lookup_by_name_tf(
            session,
            symbol=body.symbol,
            exchange=body.exchange,
            provider=body.provider,
            asset_type=None,
            timeframe=body.timeframe,
            dt_to=alert_dt_to,
        )

        regime_filter = await load_regime_filter(session, provider=body.provider)

        for pat, candle, ctx in rows:
            agg = pq_lookup.get((pat.pattern_name, pat.timeframe))
            if agg is None or agg.pattern_quality_score is None:
                continue
            if agg.pattern_quality_score < settings.alert_min_quality_score:
                continue

            plan = build_trade_plan_v1_for_stored_pattern(pat, candle, ctx, pq_lookup)
            if not trade_plan_eligible_for_simulation(plan):
                continue

            st = float(pat.pattern_strength or 0)
            if st < settings.alert_min_strength:
                continue

            regime_label = "neutral"
            if regime_filter:
                regime_label = regime_filter.get_regime_label(pat.timestamp)

            ind = await get_indicator_for_candle_timestamp(
                session,
                symbol=pat.symbol,
                exchange=pat.exchange,
                provider=pat.provider,
                timeframe=pat.timeframe,
                timestamp=pat.timestamp,
            )
            cvd_trend = ind.cvd_trend if ind else None
            funding_bias = ind.funding_bias if ind else None

            await send_alert_deduped(
                symbol=pat.symbol,
                timeframe=pat.timeframe,
                provider=pat.provider,
                pattern_name=pat.pattern_name,
                direction=pat.direction or "bullish",
                strength=st,
                quality_score=float(agg.pattern_quality_score),
                entry_price=_f_dec(plan.entry_price),
                stop_loss=_f_dec(plan.stop_loss),
                take_profit_1=_f_dec(plan.take_profit_1),
                take_profit_2=_f_dec(plan.take_profit_2),
                regime_label=regime_label,
                cvd_trend=cvd_trend,
                funding_bias=funding_bias,
                timestamp=pat.timestamp,
                exchange=pat.exchange,
            )
    except Exception:
        logger.exception(
            "pattern pipeline alerts failed (non-blocking): %s %s %s",
            body.provider,
            body.symbol,
            body.timeframe,
        )
