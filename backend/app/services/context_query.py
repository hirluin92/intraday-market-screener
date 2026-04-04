from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext


async def list_stored_contexts(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
    limit: int,
) -> list[CandleContext]:
    """Recent context rows, newest first."""
    stmt = select(CandleContext).order_by(CandleContext.timestamp.desc()).limit(limit)
    if exchange is not None:
        stmt = stmt.where(CandleContext.exchange == exchange)
    if provider is not None:
        stmt = stmt.where(CandleContext.provider == provider)
    if asset_type is not None:
        stmt = stmt.where(CandleContext.asset_type == asset_type)
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
    provider: str | None = None,
    asset_type: str | None = None,
    timeframe: str | None,
) -> list[CandleContext]:
    """
    One row per (exchange, symbol, timeframe): latest by `timestamp`, tie-break by `id`
    (ROW_NUMBER) to avoid duplicate rows when multiple bars share the same timestamp.
    """
    conditions = []
    if exchange is not None:
        conditions.append(CandleContext.exchange == exchange)
    if provider is not None:
        conditions.append(CandleContext.provider == provider)
    if asset_type is not None:
        conditions.append(CandleContext.asset_type == asset_type)
    if symbol is not None:
        conditions.append(CandleContext.symbol == symbol)
    if timeframe is not None:
        conditions.append(CandleContext.timeframe == timeframe)

    inner = (
        select(
            CandleContext.id,
            func.row_number()
            .over(
                partition_by=(
                    CandleContext.exchange,
                    CandleContext.symbol,
                    CandleContext.timeframe,
                ),
                order_by=(
                    CandleContext.timestamp.desc(),
                    CandleContext.id.desc(),
                ),
            )
            .label("rn"),
        )
        .select_from(CandleContext)
    )
    if conditions:
        inner = inner.where(and_(*conditions))
    subq = inner.subquery()

    stmt = (
        select(CandleContext)
        .join(subq, CandleContext.id == subq.c.id)
        .where(subq.c.rn == 1)
        .order_by(
            CandleContext.exchange,
            CandleContext.symbol,
            CandleContext.timeframe,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
