import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle

logger = logging.getLogger(__name__)

SeriesCandleKey = tuple[str, str, str, str]  # provider, exchange, symbol, timeframe

# Finestra temporale per la ricerca dell'ultima candela.
# 30 giorni copre: weekend + festivi + settimana di Natale/Capodanno (~10gg borsa chiusa)
# + eventuali trading halt prolungati. Abilita comunque TimescaleDB chunk pruning
# (tocca solo 1-2 chunk invece di tutti i 123) evitando il full-scan storico.
_LATEST_CANDLE_WINDOW_DAYS = 30


async def fetch_latest_candles_by_series_keys(
    session: AsyncSession,
    *,
    keys: list[SeriesCandleKey],
) -> dict[SeriesCandleKey, Candle]:
    """
    Ultima candela per ogni serie (provider, exchange, symbol, timeframe).
    Una sola query con window function, limitata agli ultimi 30 giorni per
    sfruttare il chunk pruning di TimescaleDB.

    Logga un WARNING per ogni serie richiesta ma non trovata nella finestra:
    indica un halt prolungato, errore di ingest, o simbolo non ancora mai ingestato.
    """
    if not keys:
        return {}
    uniq: list[SeriesCandleKey] = list(dict.fromkeys(keys))
    since_dt = datetime.now(timezone.utc) - timedelta(days=_LATEST_CANDLE_WINDOW_DAYS)
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
            and_(
                Candle.timestamp >= since_dt,
                tuple_(
                    Candle.provider,
                    Candle.exchange,
                    Candle.symbol,
                    Candle.timeframe,
                ).in_(uniq),
            )
        )
    ).subquery()
    stmt = select(Candle).join(inner, Candle.id == inner.c.id).where(inner.c.rn == 1)
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    out: dict[SeriesCandleKey, Candle] = {}
    for c in rows:
        k = (c.provider, c.exchange, c.symbol, c.timeframe)
        out[k] = c

    # Warning per serie richieste ma non trovate negli ultimi 30 giorni.
    # Cause possibili: simbolo non ancora ingestato, trading halt prolungato,
    # errore silenzioso nell'ingest service, o finestra troppo stretta.
    missing = [k for k in uniq if k not in out]
    if missing:
        logger.warning(
            "fetch_latest_candles: %d serie non hanno candele negli ultimi %dd "
            "(possibile halt, ingest mancante, o simbolo nuovo): %s",
            len(missing),
            _LATEST_CANDLE_WINDOW_DAYS,
            [(k[2], k[3]) for k in missing[:10]],  # max 10 per non spammare il log
        )

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
