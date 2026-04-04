import logging
from datetime import UTC, datetime
from decimal import Decimal

import ccxt.async_support as ccxt
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.market_identity import (
    DEFAULT_ASSET_TYPE_CRYPTO,
    DEFAULT_PROVIDER_BINANCE,
)
from app.core.timeframes import ALLOWED_TIMEFRAMES as DEFAULT_TIMEFRAMES_TUPLE
from app.models.candle import Candle
from app.schemas.market_data import MarketDataIngestRequest, MarketDataIngestResponse

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT")
DEFAULT_TIMEFRAMES = DEFAULT_TIMEFRAMES_TUPLE

ALLOWED_SYMBOLS = frozenset(DEFAULT_SYMBOLS)
ALLOWED_TIMEFRAMES = frozenset(DEFAULT_TIMEFRAMES)


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _ms_to_utc_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


def _parse_ohlcv_row(
    row: object,
    *,
    symbol: str,
    timeframe: str,
    exchange_id: str,
    last_ts_ms: int | None,
) -> tuple[dict, int] | None:
    """Return (row dict, ts_ms) or None if the row must be skipped."""
    if not isinstance(row, (list, tuple)) or len(row) != 6:
        logger.warning("skipping malformed OHLCV row (expected length 6): %r", row)
        return None

    ts_ms, o_open, high, low, close, volume = row

    try:
        ts_ms_int = int(ts_ms)
    except (TypeError, ValueError):
        logger.warning("skipping OHLCV row with invalid timestamp: %r", row)
        return None

    if last_ts_ms is not None and ts_ms_int <= last_ts_ms:
        logger.warning(
            "skipping OHLCV row with non-increasing timestamp: symbol=%s timeframe=%s ts_ms=%s",
            symbol,
            timeframe,
            ts_ms_int,
        )
        return None

    return (
        {
            "asset_type": DEFAULT_ASSET_TYPE_CRYPTO,
            "provider": DEFAULT_PROVIDER_BINANCE,
            "symbol": symbol,
            "exchange": exchange_id,
            "timeframe": timeframe,
            "market_metadata": None,
            "timestamp": _ms_to_utc_datetime(ts_ms_int),
            "open": _to_decimal(o_open),
            "high": _to_decimal(high),
            "low": _to_decimal(low),
            "close": _to_decimal(close),
            "volume": _to_decimal(volume),
        },
        ts_ms_int,
    )


class MarketDataIngestionService:
    """
    Ingestione OHLCV crypto spot via ccxt (Binance di default).

    Popola ``asset_type``/``provider`` coerenti con :mod:`app.core.market_identity`.
    Altri provider (azioni/ETF) potranno scrivere le stesse tabelle con valori diversi.
    """

    exchange_id: str = "binance"

    async def ingest(
        self,
        session: AsyncSession,
        request: MarketDataIngestRequest,
    ) -> MarketDataIngestResponse:
        symbols = tuple(request.symbols) if request.symbols else DEFAULT_SYMBOLS
        timeframes = tuple(request.timeframes) if request.timeframes else DEFAULT_TIMEFRAMES

        invalid_sym = set(symbols) - ALLOWED_SYMBOLS
        if invalid_sym:
            raise ValueError(f"unsupported symbols: {sorted(invalid_sym)}")
        invalid_tf = set(timeframes) - ALLOWED_TIMEFRAMES
        if invalid_tf:
            raise ValueError(f"unsupported timeframes: {sorted(invalid_tf)}")

        exchange_class = getattr(ccxt, self.exchange_id)
        exchange = exchange_class({"enableRateLimit": True, "options": {"defaultType": "spot"}})

        candles_received = 0
        incomplete_candles_dropped = 0
        rows: list[dict] = []

        try:
            for symbol in symbols:
                for timeframe in timeframes:
                    batch = await exchange.fetch_ohlcv(
                        symbol,
                        timeframe,
                        limit=request.limit,
                    )
                    if not batch:
                        continue

                    # CCXT returns candles oldest-first. The last row is the current period, which is
                    # still open (OHLC not final). Saving it would be overwritten on the next fetch;
                    # exclude it before persistence.
                    batch = batch[:-1]
                    incomplete_candles_dropped += 1
                    if not batch:
                        continue

                    candles_received += len(batch)
                    last_ts_ms: int | None = None

                    for o in batch:
                        parsed = _parse_ohlcv_row(
                            o,
                            symbol=symbol,
                            timeframe=timeframe,
                            exchange_id=self.exchange_id,
                            last_ts_ms=last_ts_ms,
                        )
                        if parsed is None:
                            continue
                        row_dict, ts_ms_int = parsed
                        last_ts_ms = ts_ms_int
                        rows.append(row_dict)
        finally:
            await exchange.close()

        rows_inserted = 0
        if rows:
            stmt = insert(Candle).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_candles_exchange_symbol_timeframe_timestamp",
            )
            result = await session.execute(stmt)
            rc = result.rowcount
            # asyncpg/psycopg bulk INSERT rowcount is not always a precise "inserted rows" count.
            rows_inserted = int(rc) if rc is not None and rc >= 0 else 0
            await session.commit()

        return MarketDataIngestResponse(
            exchange=self.exchange_id,
            provider=DEFAULT_PROVIDER_BINANCE,
            symbols=list(symbols),
            timeframes=list(timeframes),
            candles_received=candles_received,
            incomplete_candles_dropped=incomplete_candles_dropped,
            rows_inserted=rows_inserted,
        )
