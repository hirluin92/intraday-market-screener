import logging
from datetime import UTC, datetime
from decimal import Decimal

import ccxt.async_support as ccxt
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle
from app.schemas.market_data import MarketDataIngestRequest, MarketDataIngestResponse

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT")
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h")

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
            "symbol": symbol,
            "exchange": exchange_id,
            "timeframe": timeframe,
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
    """Fetches OHLCV from Binance via CCXT and persists candles (MVP)."""

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

        candles_fetched = 0
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

                    candles_fetched += len(batch)
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

        candles_inserted = 0
        if rows:
            stmt = insert(Candle).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_candles_exchange_symbol_timeframe_timestamp",
            )
            result = await session.execute(stmt)
            # rowcount is indicative for bulk INSERT ... ON CONFLICT (see driver notes).
            candles_inserted = result.rowcount or 0
            await session.commit()

        return MarketDataIngestResponse(
            exchange=self.exchange_id,
            symbols=list(symbols),
            timeframes=list(timeframes),
            candles_fetched=candles_fetched,
            candles_inserted=candles_inserted,
        )
