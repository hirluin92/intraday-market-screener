"""
MVP pattern engine v1: detects simple intraday labels from CandleFeature + CandleContext.

Heuristics are explicit, threshold-based, and ordered for readability — no ML.
Processing is per (exchange, symbol, timeframe), timestamp ascending, with optional
look-back at the previous bar's context for transition-style patterns.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.patterns import PatternExtractRequest, PatternExtractResponse


def _f(x: Any) -> float:
    if x is None:
        return 0.0
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


def _body_ratio(feat: CandleFeature) -> float:
    r = _f(feat.range_size)
    if r <= 0:
        return 0.0
    return _f(feat.body_size) / r


def _direction_from_bias_and_bar(ctx: CandleContext, feat: CandleFeature) -> str:
    """Map stored direction_bias + bar color to a single directional label."""
    if ctx.direction_bias == "bullish":
        return "bullish"
    if ctx.direction_bias == "bearish":
        return "bearish"
    return "bullish" if feat.is_bullish else "bearish"


def _detect_impulsive_bullish(feat: CandleFeature, ctx: CandleContext) -> tuple[float, str] | None:
    """
    Large real body, close near the high: classic impulsive buy-side bar.
    Uses body/range (via body_ratio), close_position_in_range, is_bullish; boosts strength
    when volatility_regime is high (larger participation in the move).
    """
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if br < 0.55 or cp < 0.65:
        return None
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    strength = min(1.0, 0.45 * br + 0.55 * cp + vol_bonus)
    if feat.volume_ratio_vs_prev is not None and _f(feat.volume_ratio_vs_prev) > 1.15:
        strength = min(1.0, strength + 0.05)
    return (strength, "bullish")


def _detect_impulsive_bearish(feat: CandleFeature, ctx: CandleContext) -> tuple[float, str] | None:
    """Large real body, close near the low; strength boosted under high volatility_regime."""
    if feat.is_bullish:
        return None
    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if br < 0.55 or cp > 0.35:
        return None
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    strength = min(1.0, 0.45 * br + 0.55 * (1.0 - cp) + vol_bonus)
    if feat.volume_ratio_vs_prev is not None and _f(feat.volume_ratio_vs_prev) > 1.15:
        strength = min(1.0, strength + 0.05)
    return (strength, "bearish")


def _detect_range_expansion_breakout_candidate(
    feat: CandleFeature,
    ctx: CandleContext,
) -> tuple[float, str] | None:
    """
    Range regime but this bar expands in range vs its rolling window — potential
    pre-breakout / volatility expansion from a quiet background.
    """
    if ctx.market_regime != "range":
        return None
    if ctx.candle_expansion != "expansion":
        return None
    if ctx.volatility_regime not in ("normal", "high"):
        return None
    direction = _direction_from_bias_and_bar(ctx, feat)
    # Slightly stronger if bias is not neutral (context engine already set it).
    bias_bonus = 0.1 if ctx.direction_bias in ("bullish", "bearish") else 0.0
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    cp = _f(feat.close_position_in_range)
    # Reward closes near the extreme in the direction we label.
    if direction == "bullish":
        extreme_score = cp
    else:
        extreme_score = 1.0 - cp
    strength = min(1.0, 0.45 + bias_bonus + vol_bonus + 0.25 * extreme_score)
    return (strength, direction)


def _detect_compression_to_expansion_transition(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_ctx: CandleContext | None,
) -> tuple[float, str] | None:
    """Prior bar classified as compression; this bar as expansion — regime shift."""
    if prev_ctx is None:
        return None
    if prev_ctx.candle_expansion != "compression":
        return None
    if ctx.candle_expansion != "expansion":
        return None
    direction = _direction_from_bias_and_bar(ctx, feat)
    # Stronger if volatility picks up.
    vol_bonus = 0.15 if ctx.volatility_regime == "high" else 0.0
    strength = min(1.0, 0.55 + vol_bonus)
    return (strength, direction)


def _run_detectors(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_ctx: CandleContext | None,
) -> list[tuple[str, float, str]]:
    """Return list of (pattern_name, strength, direction) for this bar."""
    out: list[tuple[str, float, str]] = []

    r = _detect_impulsive_bullish(feat, ctx)
    if r:
        out.append(("impulsive_bullish_candle", r[0], r[1]))

    r = _detect_impulsive_bearish(feat, ctx)
    if r:
        out.append(("impulsive_bearish_candle", r[0], r[1]))

    r = _detect_range_expansion_breakout_candidate(feat, ctx)
    if r:
        out.append(("range_expansion_breakout_candidate", r[0], r[1]))

    r = _detect_compression_to_expansion_transition(feat, ctx, prev_ctx)
    if r:
        out.append(("compression_to_expansion_transition", r[0], r[1]))

    return out


async def _distinct_series(
    session: AsyncSession,
    *,
    exchange: str | None,
    symbol: str | None,
    timeframe: str | None,
) -> list[tuple[str, str, str]]:
    stmt = select(CandleFeature.exchange, CandleFeature.symbol, CandleFeature.timeframe).distinct()
    conditions = []
    if exchange is not None:
        conditions.append(CandleFeature.exchange == exchange)
    if symbol is not None:
        conditions.append(CandleFeature.symbol == symbol)
    if timeframe is not None:
        conditions.append(CandleFeature.timeframe == timeframe)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(CandleFeature.exchange, CandleFeature.symbol, CandleFeature.timeframe)
    result = await session.execute(stmt)
    return [(r[0], r[1], r[2]) for r in result.all()]


async def extract_patterns(
    session: AsyncSession,
    request: PatternExtractRequest,
) -> PatternExtractResponse:
    series = await _distinct_series(
        session,
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
    )

    rows_to_upsert: list[dict[str, Any]] = []
    rows_read = 0
    patterns_detected = 0

    for ex, sym, tf in series:
        stmt = (
            select(CandleFeature, CandleContext)
            .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
            .where(
                CandleFeature.exchange == ex,
                CandleFeature.symbol == sym,
                CandleFeature.timeframe == tf,
            )
            .order_by(CandleFeature.timestamp.asc())
            .limit(request.limit)
        )
        result = await session.execute(stmt)
        pairs = list(result.all())
        rows_read += len(pairs)

        prev_ctx: CandleContext | None = None
        for feat, ctx in pairs:
            detected = _run_detectors(feat, ctx, prev_ctx)
            prev_ctx = ctx
            for pattern_name, strength, direction in detected:
                patterns_detected += 1
                rows_to_upsert.append(
                    {
                        "candle_feature_id": feat.id,
                        "candle_context_id": ctx.id,
                        "symbol": feat.symbol,
                        "exchange": feat.exchange,
                        "timeframe": feat.timeframe,
                        "timestamp": feat.timestamp,
                        "pattern_name": pattern_name,
                        "pattern_strength": Decimal(str(round(strength, 8))),
                        "direction": direction,
                    }
                )

    if not rows_to_upsert:
        return PatternExtractResponse(
            series_processed=len(series),
            rows_read=rows_read,
            patterns_upserted=0,
            patterns_detected=patterns_detected,
        )

    stmt_ins = insert(CandlePattern).values(rows_to_upsert)
    excluded = stmt_ins.excluded
    stmt_ins = stmt_ins.on_conflict_do_update(
        constraint="uq_candle_patterns_feature_pattern",
        set_={
            "candle_context_id": excluded.candle_context_id,
            "symbol": excluded.symbol,
            "exchange": excluded.exchange,
            "timeframe": excluded.timeframe,
            "timestamp": excluded.timestamp,
            "pattern_strength": excluded.pattern_strength,
            "direction": excluded.direction,
        },
    )
    result = await session.execute(stmt_ins)
    await session.commit()

    rc = result.rowcount
    patterns_upserted = int(rc) if rc is not None and rc >= 0 else 0

    return PatternExtractResponse(
        series_processed=len(series),
        rows_read=rows_read,
        patterns_upserted=patterns_upserted,
        patterns_detected=patterns_detected,
    )
