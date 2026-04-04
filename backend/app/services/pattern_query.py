"""Read stored `CandlePattern` rows from the database (MVP)."""

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_pattern import CandlePattern


async def list_stored_patterns(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    timeframe: str | None,
    pattern_name: str | None,
    limit: int,
) -> list[CandlePattern]:
    """Recent pattern rows, newest bar first."""
    stmt = select(CandlePattern).order_by(CandlePattern.timestamp.desc()).limit(limit)
    if exchange is not None:
        stmt = stmt.where(CandlePattern.exchange == exchange)
    if symbol is not None:
        stmt = stmt.where(CandlePattern.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(CandlePattern.timeframe == timeframe)
    if pattern_name is not None:
        stmt = stmt.where(CandlePattern.pattern_name == pattern_name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_latest_pattern_per_series(
    session: AsyncSession,
    *,
    symbol: str | None,
    exchange: str | None,
    timeframe: str | None,
) -> list[CandlePattern]:
    """
    One row per (exchange, symbol, timeframe): the pattern row with latest `timestamp`,
    tie-breaking by stronger `pattern_strength` then `pattern_name` for determinism.
    """
    conditions = []
    if exchange is not None:
        conditions.append(CandlePattern.exchange == exchange)
    if symbol is not None:
        conditions.append(CandlePattern.symbol == symbol)
    if timeframe is not None:
        conditions.append(CandlePattern.timeframe == timeframe)

    inner = (
        select(
            CandlePattern.id,
            func.row_number()
            .over(
                partition_by=(
                    CandlePattern.exchange,
                    CandlePattern.symbol,
                    CandlePattern.timeframe,
                ),
                order_by=(
                    CandlePattern.timestamp.desc(),
                    CandlePattern.pattern_strength.desc(),
                    CandlePattern.pattern_name.asc(),
                ),
            )
            .label("rn"),
        )
        .select_from(CandlePattern)
    )
    if conditions:
        inner = inner.where(and_(*conditions))
    subq = inner.subquery()

    stmt = (
        select(CandlePattern)
        .join(subq, CandlePattern.id == subq.c.id)
        .where(subq.c.rn == 1)
        .order_by(
            CandlePattern.exchange,
            CandlePattern.symbol,
            CandlePattern.timeframe,
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
