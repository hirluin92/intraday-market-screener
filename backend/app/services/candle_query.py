from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle


async def list_stored_candles(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str,
    timeframe: str | None,
    limit: int,
) -> list[Candle]:
    """Return candles newest-first, optionally filtered."""
    stmt = (
        select(Candle)
        .where(Candle.exchange == exchange)
        .order_by(Candle.timestamp.desc())
        .limit(limit)
    )
    if symbol is not None:
        stmt = stmt.where(Candle.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(Candle.timeframe == timeframe)

    result = await session.execute(stmt)
    return list(result.scalars().all())
