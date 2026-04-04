from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle
from app.models.candle_feature import CandleFeature
from app.schemas.features import FeatureExtractRequest, FeatureExtractResponse

logger = logging.getLogger(__name__)


def _d(x: Any) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _compute_features_for_candle(
    candle: Candle,
    prev: Candle | None,
) -> dict[str, Any] | None:
    """Return column dict for CandleFeature, or None if candle OHLC is invalid."""
    try:
        o = _d(candle.open)
        h = _d(candle.high)
        l = _d(candle.low)
        c = _d(candle.close)
        v = _d(candle.volume)
    except Exception:
        logger.warning("skipping candle id=%s: non-numeric OHLCV", candle.id)
        return None

    if l > h:
        logger.warning("skipping candle id=%s: low > high", candle.id)
        return None
    if not (l <= o <= h and l <= c <= h):
        logger.warning("skipping candle id=%s: open/close outside [low, high]", candle.id)
        return None

    body_size = abs(c - o)
    range_size = h - l
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if range_size > 0:
        close_position_in_range = (c - l) / range_size
    else:
        close_position_in_range = Decimal("0.5")

    pct_return_1: Decimal | None = None
    volume_ratio_vs_prev: Decimal | None = None

    if prev is not None:
        try:
            prev_close = _d(prev.close)
            prev_vol = _d(prev.volume)
        except Exception:
            prev_close = None
            prev_vol = None

        if prev_close is not None and prev_close != 0:
            pct_return_1 = (c - prev_close) / prev_close * Decimal(100)

        if prev_vol is not None and prev_vol > 0:
            volume_ratio_vs_prev = v / prev_vol

    is_bullish = c > o

    return {
        "candle_id": candle.id,
        "symbol": candle.symbol,
        "exchange": candle.exchange,
        "timeframe": candle.timeframe,
        "timestamp": candle.timestamp,
        "body_size": body_size,
        "range_size": range_size,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "close_position_in_range": close_position_in_range,
        "pct_return_1": pct_return_1,
        "volume_ratio_vs_prev": volume_ratio_vs_prev,
        "is_bullish": is_bullish,
    }


async def _distinct_series(
    session: AsyncSession,
    *,
    exchange: str | None,
    symbol: str | None,
    timeframe: str | None,
) -> list[tuple[str, str, str]]:
    stmt = select(Candle.exchange, Candle.symbol, Candle.timeframe).distinct()
    conditions = []
    if exchange is not None:
        conditions.append(Candle.exchange == exchange)
    if symbol is not None:
        conditions.append(Candle.symbol == symbol)
    if timeframe is not None:
        conditions.append(Candle.timeframe == timeframe)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(Candle.exchange, Candle.symbol, Candle.timeframe)

    result = await session.execute(stmt)
    rows = result.all()
    return [(r[0], r[1], r[2]) for r in rows]


async def extract_features(
    session: AsyncSession,
    request: FeatureExtractRequest,
) -> FeatureExtractResponse:
    exchange = request.exchange
    series = await _distinct_series(
        session,
        exchange=exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
    )

    rows_to_upsert: list[dict[str, Any]] = []
    candles_seen = 0

    for ex, sym, tf in series:
        stmt = (
            select(Candle)
            .where(
                Candle.exchange == ex,
                Candle.symbol == sym,
                Candle.timeframe == tf,
            )
            .order_by(Candle.timestamp.asc())
            .limit(request.limit)
        )
        result = await session.execute(stmt)
        candles = list(result.scalars().all())

        prev: Candle | None = None
        for candle in candles:
            candles_seen += 1
            feat = _compute_features_for_candle(candle, prev)
            prev = candle
            if feat is not None:
                rows_to_upsert.append(feat)

    if not rows_to_upsert:
        return FeatureExtractResponse(
            series_processed=len(series),
            candles_processed=candles_seen,
            features_upserted=0,
        )

    stmt_ins = insert(CandleFeature).values(rows_to_upsert)
    excluded = stmt_ins.excluded
    stmt_ins = stmt_ins.on_conflict_do_update(
        constraint="uq_candle_features_candle_id",
        set_={
            "symbol": excluded.symbol,
            "exchange": excluded.exchange,
            "timeframe": excluded.timeframe,
            "timestamp": excluded.timestamp,
            "body_size": excluded.body_size,
            "range_size": excluded.range_size,
            "upper_wick": excluded.upper_wick,
            "lower_wick": excluded.lower_wick,
            "close_position_in_range": excluded.close_position_in_range,
            "pct_return_1": excluded.pct_return_1,
            "volume_ratio_vs_prev": excluded.volume_ratio_vs_prev,
            "is_bullish": excluded.is_bullish,
        },
    )
    result = await session.execute(stmt_ins)
    await session.commit()

    upserted = result.rowcount if result.rowcount is not None else len(rows_to_upsert)

    return FeatureExtractResponse(
        series_processed=len(series),
        candles_processed=candles_seen,
        features_upserted=upserted,
    )
