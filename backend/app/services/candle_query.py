from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle

SeriesCandleKey = tuple[str, str, str, str]  # provider, exchange, symbol, timeframe


async def fetch_latest_candles_by_series_keys(
    session: AsyncSession,
    *,
    keys: list[SeriesCandleKey],
) -> dict[SeriesCandleKey, Candle]:
    """
    Ultima candela per ogni serie (provider, exchange, symbol, timeframe).
    Una sola query con window function.
    """
    if not keys:
        return {}
    uniq: list[SeriesCandleKey] = list(dict.fromkeys(keys))
    rn = (
        func.row_number()
        .over(
            partition_by=[
                Candle.provider,
                Candle.exchange,
                Candle.symbol,
                Candle.timeframe,
            ],
            order_by=Candle.timestamp.desc(),
        )
        .label("rn")
    )
    inner = (
        select(Candle.id, rn).where(
            tuple_(
                Candle.provider,
                Candle.exchange,
                Candle.symbol,
                Candle.timeframe,
            ).in_(uniq)
        )
    ).subquery()
    stmt = select(Candle).join(inner, Candle.id == inner.c.id).where(inner.c.rn == 1)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    out: dict[SeriesCandleKey, Candle] = {}
    for c in rows:
        k = (c.provider, c.exchange, c.symbol, c.timeframe)
        out[k] = c
    return out


async def list_stored_candles(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None = None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
) -> list[Candle]:
    """Return candles newest-first, optionally filtered by venue and/or provider."""
    stmt = select(Candle).order_by(Candle.timestamp.desc()).limit(limit)
    if exchange is not None:
        stmt = stmt.where(Candle.exchange == exchange)
    if provider is not None:
        stmt = stmt.where(Candle.provider == provider)
    if asset_type is not None:
        stmt = stmt.where(Candle.asset_type == asset_type)
    if symbol is not None:
        stmt = stmt.where(Candle.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(Candle.timeframe == timeframe)

    result = await session.execute(stmt)
    return list(result.scalars().all())
