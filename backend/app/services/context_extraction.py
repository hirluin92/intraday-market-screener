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
from app.services.context_thresholds import thresholds_for_timeframe


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


def _classify_context(
    current: CandleFeature,
    window: list[CandleFeature],
    *,
    timeframe: str,
) -> dict[str, str]:
    """
    Heuristics (MVP); numeric cutoffs come from ``thresholds_for_timeframe`` (see
    ``context_thresholds.py``).

    market_regime — trend vs range:
      - "trend" if mean absolute pct_return_1 over the window exceeds timeframe-specific
        thresholds (optionally reinforced by volume participation), else "range".

    volatility_regime — low / normal / high:
      - Compare current range_size to the median range_size in the window.

    candle_expansion — compression / normal / expansion:
      - Compare current range_size to the mean range_size in the window.

    direction_bias — bullish / bearish / neutral:
      - Current bar: is_bullish, close_position_in_range, pct_return_1 (thresholds per TF).
    """
    t = thresholds_for_timeframe(timeframe)
    ranges = [_f(f.range_size) for f in window if _f(f.range_size) > 0]
    cur_range = _f(current.range_size)

    med_r = median(ranges) if ranges else cur_range
    mean_r = sum(ranges) / len(ranges) if ranges else cur_range

    # Volatility vs median range in window
    vol_ratio = cur_range / med_r if med_r > 0 else 1.0
    if vol_ratio < t.vol_low_ratio:
        volatility_regime = "low"
    elif vol_ratio > t.vol_high_ratio:
        volatility_regime = "high"
    else:
        volatility_regime = "normal"

    # Expansion vs mean range (same bar, different baseline)
    exp_ratio = cur_range / mean_r if mean_r > 0 else 1.0
    if exp_ratio < t.exp_low_ratio:
        candle_expansion = "compression"
    elif exp_ratio > t.exp_high_ratio:
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
    if mean_abs_pct > t.trend_abs_pct_high or (
        mean_abs_pct > t.trend_abs_pct_med and mean_vol_ratio > t.trend_volume_ratio
    ):
        market_regime = "trend"
    else:
        market_regime = "range"

    # Direction on the *current* bar only (MVP)
    pr = _f(current.pct_return_1) if current.pct_return_1 is not None else 0.0
    cp = _f(current.close_position_in_range)
    if current.is_bullish and cp >= t.dir_cp_bull:
        direction_bias = "bullish"
    elif (not current.is_bullish) and cp <= t.dir_cp_bear:
        direction_bias = "bearish"
    elif pr > t.dir_pr:
        direction_bias = "bullish"
    elif pr < -t.dir_pr:
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
        provider=request.provider,
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
            labels = _classify_context(feat, window, timeframe=feat.timeframe)
            rows_to_upsert.append(
                {
                    "candle_feature_id": feat.id,
                    "asset_type": feat.asset_type,
                    "provider": feat.provider,
                    "symbol": feat.symbol,
                    "exchange": feat.exchange,
                    "timeframe": feat.timeframe,
                    "market_metadata": feat.market_metadata,
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
            "asset_type": excluded.asset_type,
            "provider": excluded.provider,
            "symbol": excluded.symbol,
            "exchange": excluded.exchange,
            "timeframe": excluded.timeframe,
            "market_metadata": excluded.market_metadata,
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
