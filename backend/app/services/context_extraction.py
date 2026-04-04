"""
MVP context engine: classifies market_regime, volatility_regime, candle_expansion,
direction_bias from stored CandleFeature rows using explicit rolling-window heuristics.
No ML; thresholds are intentionally simple and documented inline.
"""

from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.schemas.context import ContextExtractRequest, ContextExtractResponse


def _f(x: Any) -> float:
    if x is None:
        return 0.0
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


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


def _classify_context(
    current: CandleFeature,
    window: list[CandleFeature],
) -> dict[str, str]:
    """
    Heuristics (MVP):

    market_regime — trend vs range:
      - "trend" if mean absolute pct_return_1 over the window exceeds a small threshold
        (sustained directional movement in % terms), else "range".

    volatility_regime — low / normal / high:
      - Compare current range_size to the median range_size in the window.
        Below ~0.7x median → low; above ~1.3x → high; else normal.

    candle_expansion — compression / normal / expansion:
      - Compare current range_size to the mean range_size in the window.
        Below ~0.75x → compression; above ~1.25x → expansion; else normal.

    direction_bias — bullish / bearish / neutral:
      - Use current bar: is_bullish, close_position_in_range, and pct_return_1 sign/magnitude.
    """
    ranges = [_f(f.range_size) for f in window if _f(f.range_size) > 0]
    cur_range = _f(current.range_size)

    med_r = median(ranges) if ranges else cur_range
    mean_r = sum(ranges) / len(ranges) if ranges else cur_range

    # Volatility vs median range in window
    vol_ratio = cur_range / med_r if med_r > 0 else 1.0
    if vol_ratio < 0.7:
        volatility_regime = "low"
    elif vol_ratio > 1.3:
        volatility_regime = "high"
    else:
        volatility_regime = "normal"

    # Expansion vs mean range (same bar, different baseline)
    exp_ratio = cur_range / mean_r if mean_r > 0 else 1.0
    if exp_ratio < 0.75:
        candle_expansion = "compression"
    elif exp_ratio > 1.25:
        candle_expansion = "expansion"
    else:
        candle_expansion = "normal"

    # Trend vs range: average absolute % change; optionally reinforce with volume participation.
    pcts: list[float] = []
    for f in window:
        if f.pct_return_1 is not None:
            pcts.append(abs(_f(f.pct_return_1)))
    mean_abs_pct = sum(pcts) / len(pcts) if pcts else 0.0
    vol_ratios = [_f(f.volume_ratio_vs_prev) for f in window if f.volume_ratio_vs_prev is not None]
    mean_vol_ratio = sum(vol_ratios) / len(vol_ratios) if vol_ratios else 1.0
    # Percent points (e.g. 0.05 ≈ 0.05% average absolute move per bar in the window).
    if mean_abs_pct > 0.05 or (mean_abs_pct > 0.03 and mean_vol_ratio > 1.2):
        market_regime = "trend"
    else:
        market_regime = "range"

    # Direction on the *current* bar only (MVP)
    pr = _f(current.pct_return_1) if current.pct_return_1 is not None else 0.0
    cp = _f(current.close_position_in_range)
    if current.is_bullish and cp >= 0.55:
        direction_bias = "bullish"
    elif (not current.is_bullish) and cp <= 0.45:
        direction_bias = "bearish"
    elif pr > 0.02:
        direction_bias = "bullish"
    elif pr < -0.02:
        direction_bias = "bearish"
    else:
        direction_bias = "neutral"

    return {
        "market_regime": market_regime,
        "volatility_regime": volatility_regime,
        "candle_expansion": candle_expansion,
        "direction_bias": direction_bias,
    }


async def extract_context(
    session: AsyncSession,
    request: ContextExtractRequest,
) -> ContextExtractResponse:
    series = await _distinct_series(
        session,
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
    )

    rows_to_upsert: list[dict[str, Any]] = []
    features_read = 0

    for ex, sym, tf in series:
        stmt = (
            select(CandleFeature)
            .where(
                CandleFeature.exchange == ex,
                CandleFeature.symbol == sym,
                CandleFeature.timeframe == tf,
            )
            .order_by(CandleFeature.timestamp.asc())
            .limit(request.limit)
        )
        result = await session.execute(stmt)
        features = list(result.scalars().all())
        features_read += len(features)

        for i, feat in enumerate(features):
            start = max(0, i - request.lookback + 1)
            window = features[start : i + 1]
            if not window:
                continue
            labels = _classify_context(feat, window)
            rows_to_upsert.append(
                {
                    "candle_feature_id": feat.id,
                    "symbol": feat.symbol,
                    "exchange": feat.exchange,
                    "timeframe": feat.timeframe,
                    "timestamp": feat.timestamp,
                    **labels,
                }
            )

    if not rows_to_upsert:
        return ContextExtractResponse(
            series_processed=len(series),
            features_read=features_read,
            contexts_upserted=0,
        )

    stmt_ins = insert(CandleContext).values(rows_to_upsert)
    excluded = stmt_ins.excluded
    stmt_ins = stmt_ins.on_conflict_do_update(
        constraint="uq_candle_contexts_candle_feature_id",
        set_={
            "symbol": excluded.symbol,
            "exchange": excluded.exchange,
            "timeframe": excluded.timeframe,
            "timestamp": excluded.timestamp,
            "market_regime": excluded.market_regime,
            "volatility_regime": excluded.volatility_regime,
            "candle_expansion": excluded.candle_expansion,
            "direction_bias": excluded.direction_bias,
        },
    )
    result = await session.execute(stmt_ins)
    await session.commit()

    rc = result.rowcount
    contexts_upserted = int(rc) if rc is not None and rc >= 0 else 0

    return ContextExtractResponse(
        series_processed=len(series),
        features_read=features_read,
        contexts_upserted=contexts_upserted,
    )
