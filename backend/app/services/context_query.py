from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.services.candle_query import SeriesCandleKey, fetch_latest_candles_by_series_keys


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
    since_hours: int = 168,
) -> list[CandleContext]:
    """
    One row per (exchange, symbol, timeframe): latest by `timestamp`, tie-break by `id`
    (ROW_NUMBER) to avoid duplicate rows when multiple bars share the same timestamp.

    `since_hours` limita la scansione per evitare full table scan su tabelle grandi.
    168h (7 giorni) copre weekend + festivi anche per timeframe 1d.
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    conditions = [CandleContext.timestamp >= since_dt]
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


def _context_freshness_ts(
    ctx: CandleContext,
    candle_map: dict[SeriesCandleKey, Candle],
) -> datetime:
    """Timestamp dell’ultima candela in DB per la serie, altrimenti timestamp del contesto."""
    k: SeriesCandleKey = (ctx.provider, ctx.exchange, ctx.symbol, ctx.timeframe)
    c = candle_map.get(k)
    if c is not None:
        return c.timestamp
    return ctx.timestamp


async def dedupe_latest_contexts_prefer_freshest_candle(
    session: AsyncSession,
    contexts: list[CandleContext],
) -> tuple[list[CandleContext], dict[SeriesCandleKey, Candle]]:
    """
    Se lo stesso (symbol, timeframe) compare su più venue/provider (es. ALPACA_US vs YAHOO_US),
    tiene una sola riga: quella con ultima candela più recente nel DB.

    Ritorna anche la mappa ultima-candela usata per il confronto, riutilizzabile da
    ``list_opportunities`` per evitare una seconda query identica.
    """
    if not contexts:
        return [], {}
    keys: list[SeriesCandleKey] = [
        (c.provider, c.exchange, c.symbol, c.timeframe) for c in contexts
    ]
    candle_map = await fetch_latest_candles_by_series_keys(session, keys=keys)

    by_sym_tf: dict[tuple[str, str], list[CandleContext]] = defaultdict(list)
    for c in contexts:
        by_sym_tf[(c.symbol.upper(), c.timeframe)].append(c)

    picked: list[CandleContext] = []
    for group in by_sym_tf.values():
        if len(group) == 1:
            picked.append(group[0])
            continue
        best: CandleContext | None = None
        best_ts: datetime | None = None
        best_id = -1
        for ctx in group:
            ts = _context_freshness_ts(ctx, candle_map)
            cid = ctx.id
            if best is None or ts > best_ts or (ts == best_ts and cid > best_id):
                best = ctx
                best_ts = ts
                best_id = cid
        if best is not None:
            picked.append(best)

    picked.sort(key=lambda x: (x.exchange, x.symbol, x.timeframe))
    return picked, candle_map
