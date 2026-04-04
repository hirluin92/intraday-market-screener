"""
MVP pattern engine v1: detects simple intraday labels from CandleFeature + CandleContext.

Heuristics are explicit, threshold-based, and ordered for readability — no ML.
Processing is per (exchange, symbol, timeframe), timestamp ascending, with optional
look-back at the previous bar's context for transition-style patterns.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_pattern import CandlePattern
from app.schemas.patterns import PatternExtractRequest, PatternExtractResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern refinement v1 — tune thresholds here (explicit, no ML).
# Goals: fewer weak/contradictory labels; require cleaner bodies, closes at extremes,
# alignment with direction_bias where it matters, and avoid dead-low-volatility chop.
# ---------------------------------------------------------------------------

# Impulsive candles: stricter body vs range and close at candle extreme.
_IMPULSIVE_MIN_BODY_RATIO = 0.62  # was 0.55
_IMPULSIVE_BULL_MIN_CLOSE_POS = 0.72  # was 0.65 — close nearer to high
_IMPULSIVE_BEAR_MAX_CLOSE_POS = 0.28  # was 0.35 — close nearer to low
_IMPULSIVE_MIN_VOL_RATIO_BONUS = 1.22  # was 1.15 — volume confirmation slightly stronger

# Reject impulsive signals in very quiet vol (often noise / mean-reversion chop).
_IMPULSIVE_ALLOWED_VOLATILITY = frozenset({"normal", "high"})

# Range expansion breakout: require a real body, close in the trade direction, and no bias clash.
_RE_BREAKOUT_MIN_BODY_RATIO = 0.38
_RE_BREAKOUT_BULL_MIN_CP = 0.55  # bullish breakout closes in upper half
_RE_BREAKOUT_BEAR_MAX_CP = 0.45

# Compression → expansion: expansion bar must show commitment + not low vol; optional bias alignment.
_CT_EXP_MIN_BODY_RATIO = 0.42
_CT_EXP_ALLOWED_VOLATILITY = frozenset({"normal", "high"})
_CT_EXP_ALLOWED_MARKET = frozenset({"trend", "range"})


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

    Refinement v1: tighter body/close thresholds; skip bearish context bias (contradictory);
    skip low-volatility regimes (weak participation); slightly higher volume bar for bonus.
    """
    if not feat.is_bullish:
        return None
    # Bullish impulse against explicit bearish bias is usually noise for this MVP label.
    if ctx.direction_bias == "bearish":
        return None
    if ctx.volatility_regime not in _IMPULSIVE_ALLOWED_VOLATILITY:
        return None
    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if br < _IMPULSIVE_MIN_BODY_RATIO or cp < _IMPULSIVE_BULL_MIN_CLOSE_POS:
        return None
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    # Small boost when context already leans bullish (less contradictory).
    bias_bonus = 0.05 if ctx.direction_bias == "bullish" else 0.0
    strength = min(1.0, 0.45 * br + 0.55 * cp + vol_bonus + bias_bonus)
    if feat.volume_ratio_vs_prev is not None and _f(feat.volume_ratio_vs_prev) > _IMPULSIVE_MIN_VOL_RATIO_BONUS:
        strength = min(1.0, strength + 0.05)
    return (strength, "bullish")


def _detect_impulsive_bearish(feat: CandleFeature, ctx: CandleContext) -> tuple[float, str] | None:
    """
    Large real body, close near the low.

    Refinement v1: symmetric to bullish — tighter thresholds, no bullish-bias contradiction,
    no low-vol chop, slightly stricter volume bonus.
    """
    if feat.is_bullish:
        return None
    if ctx.direction_bias == "bullish":
        return None
    if ctx.volatility_regime not in _IMPULSIVE_ALLOWED_VOLATILITY:
        return None
    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if br < _IMPULSIVE_MIN_BODY_RATIO or cp > _IMPULSIVE_BEAR_MAX_CLOSE_POS:
        return None
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    bias_bonus = 0.05 if ctx.direction_bias == "bearish" else 0.0
    strength = min(1.0, 0.45 * br + 0.55 * (1.0 - cp) + vol_bonus + bias_bonus)
    if feat.volume_ratio_vs_prev is not None and _f(feat.volume_ratio_vs_prev) > _IMPULSIVE_MIN_VOL_RATIO_BONUS:
        strength = min(1.0, strength + 0.05)
    return (strength, "bearish")


def _detect_range_expansion_breakout_candidate(
    feat: CandleFeature,
    ctx: CandleContext,
) -> tuple[float, str] | None:
    """
    Range regime but this bar expands in range vs its rolling window — potential
    pre-breakout / volatility expansion from a quiet background.

    Refinement v1: require meaningful body (not wick-only), close in the breakout direction,
    and do not label when direction_bias clearly opposes the breakout side.
    """
    if ctx.market_regime != "range":
        return None
    if ctx.candle_expansion != "expansion":
        return None
    if ctx.volatility_regime not in ("normal", "high"):
        return None
    br = _body_ratio(feat)
    if br < _RE_BREAKOUT_MIN_BODY_RATIO:
        return None
    direction = _direction_from_bias_and_bar(ctx, feat)
    cp = _f(feat.close_position_in_range)
    # Bias conflict: e.g. bearish bias but long breakout bar — skip (noisy).
    if direction == "bullish":
        if ctx.direction_bias == "bearish":
            return None
        if cp < _RE_BREAKOUT_BULL_MIN_CP:
            return None
    else:
        if ctx.direction_bias == "bullish":
            return None
        if cp > _RE_BREAKOUT_BEAR_MAX_CP:
            return None
    bias_bonus = 0.1 if ctx.direction_bias in ("bullish", "bearish") else 0.0
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
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
    """
    Prior bar classified as compression; this bar as expansion — regime shift.

    Refinement v1: gate on market + volatility regime, minimum body on the expansion bar,
    and coarse alignment between bar color / close and direction_bias to reduce contradictory
    transition labels.
    """
    if prev_ctx is None:
        return None
    if prev_ctx.candle_expansion != "compression":
        return None
    if ctx.candle_expansion != "expansion":
        return None
    if ctx.market_regime not in _CT_EXP_ALLOWED_MARKET:
        return None
    if ctx.volatility_regime not in _CT_EXP_ALLOWED_VOLATILITY:
        return None
    br = _body_ratio(feat)
    if br < _CT_EXP_MIN_BODY_RATIO:
        return None
    cp = _f(feat.close_position_in_range)
    direction = _direction_from_bias_and_bar(ctx, feat)
    # When bias is directional, require the expansion candle to agree (bar + close quadrant).
    if ctx.direction_bias == "bullish":
        if not feat.is_bullish or cp < 0.52:
            return None
    elif ctx.direction_bias == "bearish":
        if feat.is_bullish or cp > 0.48:
            return None
    else:
        # Neutral bias: still require a decisive close (avoid doji-like transitions).
        if not (cp >= 0.58 or cp <= 0.42):
            return None
    vol_bonus = 0.15 if ctx.volatility_regime == "high" else 0.0
    align = 0.08 if (
        (direction == "bullish" and feat.is_bullish) or (direction == "bearish" and not feat.is_bullish)
    ) else 0.0
    strength = min(1.0, 0.52 + vol_bonus + align)
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
    provider: str | None,
    symbol: str | None,
    timeframe: str | None,
) -> list[tuple[str, str, str]]:
    stmt = select(CandleFeature.exchange, CandleFeature.symbol, CandleFeature.timeframe).distinct()
    conditions = []
    if exchange is not None:
        conditions.append(CandleFeature.exchange == exchange)
    if provider is not None:
        conditions.append(CandleFeature.provider == provider)
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
        provider=request.provider,
        symbol=request.symbol,
        timeframe=request.timeframe,
    )

    rows_to_upsert: list[dict[str, Any]] = []
    rows_read = 0
    patterns_detected = 0
    features_skipped_no_context = 0

    for ex, sym, tf in series:
        stmt_feats = (
            select(CandleFeature)
            .where(
                CandleFeature.exchange == ex,
                CandleFeature.symbol == sym,
                CandleFeature.timeframe == tf,
            )
            .order_by(CandleFeature.timestamp.asc())
            .limit(request.limit)
        )
        result_f = await session.execute(stmt_feats)
        features = list(result_f.scalars().all())
        if not features:
            continue

        ids = [f.id for f in features]
        stmt_ctx = select(CandleContext).where(CandleContext.candle_feature_id.in_(ids))
        result_c = await session.execute(stmt_ctx)
        ctx_by_feature_id: dict[int, CandleContext] = {
            c.candle_feature_id: c for c in result_c.scalars().all()
        }

        prev_ctx: CandleContext | None = None
        for feat in features:
            ctx = ctx_by_feature_id.get(feat.id)
            if ctx is None:
                features_skipped_no_context += 1
                continue
            rows_read += 1
            detected = _run_detectors(feat, ctx, prev_ctx)
            prev_ctx = ctx
            for pattern_name, strength, direction in detected:
                patterns_detected += 1
                rows_to_upsert.append(
                    {
                        "candle_feature_id": feat.id,
                        "candle_context_id": ctx.id,
                        "asset_type": feat.asset_type,
                        "provider": feat.provider,
                        "symbol": feat.symbol,
                        "exchange": feat.exchange,
                        "timeframe": feat.timeframe,
                        "market_metadata": feat.market_metadata,
                        "timestamp": feat.timestamp,
                        "pattern_name": pattern_name,
                        "pattern_strength": Decimal(str(round(strength, 8))),
                        "direction": direction,
                    }
                )

    if features_skipped_no_context > 0:
        logger.warning(
            "pattern extract: %s feature row(s) had no matching CandleContext (run context/extract first)",
            features_skipped_no_context,
        )

    if not rows_to_upsert:
        return PatternExtractResponse(
            series_processed=len(series),
            rows_read=rows_read,
            features_skipped_no_context=features_skipped_no_context,
            patterns_upserted=0,
            patterns_detected=patterns_detected,
        )

    stmt_ins = insert(CandlePattern).values(rows_to_upsert)
    excluded = stmt_ins.excluded
    stmt_ins = stmt_ins.on_conflict_do_update(
        constraint="uq_candle_patterns_feature_pattern",
        set_={
            "candle_context_id": excluded.candle_context_id,
            "asset_type": excluded.asset_type,
            "provider": excluded.provider,
            "symbol": excluded.symbol,
            "exchange": excluded.exchange,
            "timeframe": excluded.timeframe,
            "market_metadata": excluded.market_metadata,
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
        features_skipped_no_context=features_skipped_no_context,
        patterns_upserted=patterns_upserted,
        patterns_detected=patterns_detected,
    )
