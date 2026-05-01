"""
Ingestione OHLCV via IBKR TWS (reqHistoricalData) per due mercati distinti:

1. Azioni / ETF azionari USA (exchange="SMART", currency="USD"):
   Drop-in replacement di yahoo_finance_ingestion per il provider "yahoo_finance" su
   timeframe 1h. I dati vengono salvati con gli stessi campi (provider="yahoo_finance",
   exchange="YAHOO_US") per compatibilità completa con tutto il sistema esistente
   (opportunities, validator, pattern detection, backtest).

2. Azioni UK (London Stock Exchange, exchange="LSE", currency="GBP"):
   Ingestione FTSE 100/250. I dati vengono salvati con provider="ibkr", exchange="LSE"
   (NESSUN alias su YAHOO_US) — il mercato UK parte da zero, senza legacy di compatibilità.
   Prezzi in pence (GBp): es. AZN a 12500 = £125.00 GBP.

Routing:
  Scheduler imposta provider="ibkr" → market_data router dispatch a IBKRIngestionService
  US:  IBKRIngestionService salva con provider="yahoo_finance" (trasparente al resto)
  UK:  IBKRIngestionService salva con provider="ibkr", exchange="LSE"

Limiti IBKR historical data:
  max 6 richieste concurrent (pacing limit)
  max 60 richieste per simbolo in 10 minuti
  Mitigazione: _IBKR_HIST_SEMAPHORE limita la concorrenza a 5 richieste simultanee.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.yahoo_finance_constants import (
    ALLOWED_YAHOO_SYMBOLS,
    YAHOO_FINANCE_PROVIDER_ID,
    YAHOO_SYMBOL_ASSET_TYPE,
    YAHOO_VENUE_LABEL,
)
from app.models.candle import Candle
from app.schemas.market_data import MarketDataIngestRequest, MarketDataIngestResponse
from app.services.tws_service import get_tws_service

logger = logging.getLogger(__name__)

# Semaphore IBKR: max 5 richieste storiche concurrent (pacing limit IBKR = 6).
_IBKR_HIST_SEMAPHORE = asyncio.Semaphore(5)

# Timeframe supportati da questo provider (stessi di Yahoo Finance 1h).
IBKR_ALLOWED_TIMEFRAMES: frozenset[str] = frozenset({"1h", "1d", "5m", "15m"})

_UPSERT_CHUNK_SIZE = 2_000

# Exchange/currency UK
_LSE_EXCHANGE = "LSE"
_GBP_CURRENCY = "GBP"
_LSE_PROVIDER_ID = "ibkr"
_LSE_ASSET_TYPE = "uk_stock"


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _normalize_ts(ts: Any) -> datetime:
    """Normalizza il timestamp IBKR a datetime UTC consapevole."""
    if hasattr(ts, "astimezone"):
        return ts.astimezone(UTC)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    # Stringa IBKR formato "YYYYMMDD HH:MM:SS" (useRTH=True, formatDate=1)
    if isinstance(ts, str):
        for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d"):
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    raise ValueError(f"timestamp IBKR non riconoscibile: {ts!r}")


async def _chunked_upsert_candles(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
    """Bulk upsert in chunk da 500 righe (limite parametri asyncpg)."""
    if not rows:
        return 0
    total_rc = 0
    for i in range(0, len(rows), _UPSERT_CHUNK_SIZE):
        chunk = rows[i : i + _UPSERT_CHUNK_SIZE]
        stmt = insert(Candle).values(chunk)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_candles_provider_exchange_symbol_timeframe_timestamp",
        )
        result = await session.execute(stmt)
        rc = result.rowcount
        if rc is not None and rc >= 0:
            total_rc += int(rc)
    await session.commit()
    return total_rc


class IBKRIngestionService:
    """
    Provider IBKR TWS per azioni USA (drop-in replacement di YahooFinanceIngestionService)
    e per azioni UK/LSE (nuovo mercato, salvataggio nativo ibkr/LSE).

    Routing key: provider="ibkr" (usato dallo scheduler e dal router API per il dispatch)

    Comportamento in base a request.exchange:
      - exchange=None/"SMART"/"YAHOO_US" → US stock: salva provider="yahoo_finance", exchange="YAHOO_US"
      - exchange="LSE" → UK stock: salva provider="ibkr", exchange="LSE"
    """

    provider_id: str = "ibkr"

    async def ingest(
        self,
        session: AsyncSession,
        request: MarketDataIngestRequest,
    ) -> MarketDataIngestResponse:
        symbols = tuple(request.symbols) if request.symbols else ()
        timeframes = tuple(request.timeframes) if request.timeframes else ("1h",)
        limit = request.limit or 50

        # Determina se è UK (LSE) o US (SMART) in base all'exchange della request.
        is_uk = (request.exchange or "").upper() == _LSE_EXCHANGE
        ibkr_exchange = _LSE_EXCHANGE if is_uk else "SMART"
        ibkr_currency = _GBP_CURRENCY if is_uk else "USD"

        if not symbols:
            raise ValueError("IBKRIngestionService: symbols obbligatorio (nessun default globale)")

        # Validazione simboli:
        # - US: contro ALLOWED_YAHOO_SYMBOLS (universo validato)
        # - UK: nessun whitelist rigido (universe gestita da uk_universe.py); passa tutto
        if not is_uk:
            invalid_sym = set(symbols) - ALLOWED_YAHOO_SYMBOLS
            if invalid_sym:
                raise ValueError(f"simboli non nell'universo Yahoo/IBKR: {sorted(invalid_sym)}")

        invalid_tf = set(timeframes) - IBKR_ALLOWED_TIMEFRAMES
        if invalid_tf:
            raise ValueError(
                f"timeframe non supportati da IBKR ingestion "
                f"(supportati: {sorted(IBKR_ALLOWED_TIMEFRAMES)}): {sorted(invalid_tf)}"
            )

        tws = get_tws_service()
        if not tws._connected:
            raise RuntimeError(
                "IBKRIngestionService: TWS non connesso — "
                "verificare che TWS Gateway sia attivo e TWS_ENABLED=true"
            )

        candles_received = 0
        incomplete_candles_dropped = 0
        rows: list[dict[str, Any]] = []
        symbols_failed: list[str] = []

        for symbol in symbols:
            # Per UK: asset_type fisso "uk_stock". Per US: usa mappa Yahoo.
            asset_type = _LSE_ASSET_TYPE if is_uk else YAHOO_SYMBOL_ASSET_TYPE.get(symbol, "stock")

            for tf in timeframes:
                async with _IBKR_HIST_SEMAPHORE:
                    try:
                        bars = await tws.get_historical_candles(
                            symbol=symbol,
                            timeframe=tf,
                            limit=limit,
                            exchange=ibkr_exchange,
                            currency=ibkr_currency,
                        )
                    except Exception:
                        logger.exception(
                            "ibkr_ingestion: fetch fallito symbol=%s timeframe=%s exchange=%s",
                            symbol, tf, ibkr_exchange,
                        )
                        symbols_failed.append(f"{symbol}/{tf}")
                        continue

                if bars is None:
                    logger.warning(
                        "ibkr_ingestion: TWS ha restituito None symbol=%s timeframe=%s exchange=%s",
                        symbol, tf, ibkr_exchange,
                    )
                    symbols_failed.append(f"{symbol}/{tf}")
                    continue

                if not bars:
                    logger.warning(
                        "ibkr_ingestion: nessuna barra symbol=%s timeframe=%s exchange=%s",
                        symbol, tf, ibkr_exchange,
                    )
                    continue

                # get_historical_candles scarta già l'ultima barra incompleta.
                incomplete_candles_dropped += 1

                # Coordinate DB:
                # - US: provider="yahoo_finance", exchange="YAHOO_US" (compatibilità legacy)
                # - UK: provider="ibkr", exchange="LSE" (nuovo, pulito)
                db_provider = _LSE_PROVIDER_ID if is_uk else YAHOO_FINANCE_PROVIDER_ID
                db_exchange = _LSE_EXCHANGE if is_uk else YAHOO_VENUE_LABEL
                db_metadata: dict[str, Any] = {
                    "source": "ibkr_tws",
                    "ibkr_bar_size": tf,
                    "ibkr_exchange": ibkr_exchange,
                    "ibkr_currency": ibkr_currency,
                }

                last_ts: datetime | None = None
                for bar in bars:
                    try:
                        ts_utc = _normalize_ts(bar["timestamp"])
                    except (ValueError, KeyError) as exc:
                        logger.warning(
                            "ibkr_ingestion: timestamp non valido symbol=%s bar=%s: %s",
                            symbol, bar, exc
                        )
                        continue

                    if last_ts is not None and ts_utc <= last_ts:
                        logger.warning(
                            "ibkr_ingestion: timestamp non crescente symbol=%s tf=%s ts=%s",
                            symbol, tf, ts_utc
                        )
                        continue
                    last_ts = ts_utc

                    o = bar.get("open")
                    h = bar.get("high")
                    lo = bar.get("low")
                    c = bar.get("close")
                    v = bar.get("volume", 0.0)

                    if None in (o, h, lo, c):
                        continue

                    rows.append({
                        "asset_type": asset_type,
                        "provider": db_provider,
                        "symbol": symbol,
                        "exchange": db_exchange,
                        "timeframe": tf,
                        "market_metadata": db_metadata,
                        "timestamp": ts_utc,
                        "open": _to_decimal(o),
                        "high": _to_decimal(h),
                        "low": _to_decimal(lo),
                        "close": _to_decimal(c),
                        "volume": _to_decimal(v) if v is not None else Decimal("0"),
                    })
                    candles_received += 1

        if symbols_failed:
            logger.warning(
                "ibkr_ingestion: %d combinazioni fallite: %s",
                len(symbols_failed), symbols_failed
            )

        rows_inserted = await _chunked_upsert_candles(session, rows)

        # Coordinate response: per UK usa ibkr/LSE; per US usa yahoo_finance/YAHOO_US
        resp_provider = _LSE_PROVIDER_ID if is_uk else YAHOO_FINANCE_PROVIDER_ID
        resp_exchange = _LSE_EXCHANGE if is_uk else YAHOO_VENUE_LABEL

        return MarketDataIngestResponse(
            exchange=resp_exchange,
            provider=resp_provider,
            symbols=list(symbols),
            timeframes=list(timeframes),
            candles_received=candles_received,
            incomplete_candles_dropped=incomplete_candles_dropped,
            rows_inserted=rows_inserted,
        )
