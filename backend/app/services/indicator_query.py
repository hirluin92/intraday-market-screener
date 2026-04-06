"""Query indicatori tecnici salvati."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_indicator import CandleIndicator


async def get_indicator_for_candle_timestamp(
    session: AsyncSession,
    *,
    symbol: str,
    exchange: str,
    provider: str,
    timeframe: str,
    timestamp: datetime,
) -> CandleIndicator | None:
    """Riga CandleIndicator per la stessa chiave e timestamp della candela (barra)."""
    stmt = (
        select(CandleIndicator)
        .where(
            CandleIndicator.symbol == symbol,
            CandleIndicator.exchange == exchange,
            CandleIndicator.provider == provider,
            CandleIndicator.timeframe == timeframe,
            CandleIndicator.timestamp == timestamp,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def list_stored_indicators(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
) -> list[CandleIndicator]:
    stmt = select(CandleIndicator)
    if exchange is not None:
        stmt = stmt.where(CandleIndicator.exchange == exchange)
    if provider is not None:
        stmt = stmt.where(CandleIndicator.provider == provider)
    if asset_type is not None:
        stmt = stmt.where(CandleIndicator.asset_type == asset_type)
    if symbol is not None:
        stmt = stmt.where(CandleIndicator.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(CandleIndicator.timeframe == timeframe)
    stmt = stmt.order_by(CandleIndicator.timestamp.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
