"""Read stored `CandleFeature` rows (MVP)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_feature import CandleFeature


async def list_stored_features(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
) -> list[CandleFeature]:
    """Recent feature rows, newest bar first."""
    stmt = select(CandleFeature).order_by(CandleFeature.timestamp.desc()).limit(limit)
    if exchange is not None:
        stmt = stmt.where(CandleFeature.exchange == exchange)
    if provider is not None:
        stmt = stmt.where(CandleFeature.provider == provider)
    if asset_type is not None:
        stmt = stmt.where(CandleFeature.asset_type == asset_type)
    if symbol is not None:
        stmt = stmt.where(CandleFeature.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(CandleFeature.timeframe == timeframe)
    result = await session.execute(stmt)
    return list(result.scalars().all())
