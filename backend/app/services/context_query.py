from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext


async def list_stored_contexts(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    timeframe: str | None,
    limit: int,
) -> list[CandleContext]:
    """Recent context rows, newest first."""
    stmt = select(CandleContext).order_by(CandleContext.timestamp.desc()).limit(limit)
    if exchange is not None:
        stmt = stmt.where(CandleContext.exchange == exchange)
    if symbol is not None:
        stmt = stmt.where(CandleContext.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(CandleContext.timeframe == timeframe)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_latest_context_per_series(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    timeframe: str | None,
) -> list[CandleContext]:
    """
    One row per (exchange, symbol, timeframe): the row with max(timestamp).
    """
    subq = select(
        CandleContext.exchange,
        CandleContext.symbol,
        CandleContext.timeframe,
        func.max(CandleContext.timestamp).label("max_ts"),
    )
    conditions = []
    if exchange is not None:
        conditions.append(CandleContext.exchange == exchange)
    if symbol is not None:
        conditions.append(CandleContext.symbol == symbol)
    if timeframe is not None:
        conditions.append(CandleContext.timeframe == timeframe)
    if conditions:
        subq = subq.where(and_(*conditions))
    subq = subq.group_by(
        CandleContext.exchange,
        CandleContext.symbol,
        CandleContext.timeframe,
    ).subquery()

    stmt = (
        select(CandleContext)
        .join(
            subq,
            and_(
                CandleContext.exchange == subq.c.exchange,
                CandleContext.symbol == subq.c.symbol,
                CandleContext.timeframe == subq.c.timeframe,
                CandleContext.timestamp == subq.c.max_ts,
            ),
        )
        .order_by(
            CandleContext.exchange,
            CandleContext.symbol,
            CandleContext.timeframe,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
