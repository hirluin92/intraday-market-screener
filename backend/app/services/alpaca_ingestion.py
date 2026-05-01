"""
Ingestione OHLCV via Alpaca Markets Data API v2.

Motivo d'uso: Yahoo Finance limita i dati 5m a 60 giorni; Alpaca fornisce
fino a 2-3 anni di storico 5m su US stocks (feed IEX, account gratuito).
Il feed SIP (National Best Bid/Offer) richiede abbonamento paid.

Flusso:
  1. GET /v2/stocks/{symbol}/bars con paginazione (next_page_token)
  2. Upsert in tabella candles (stessa struttura Yahoo Finance)
  3. exchange = "ALPACA_US" | provider = "alpaca"

Timeframes supportati:
  Alpaca → DB:
    "1Min"  → "1m"
    "5Min"  → "5m"
    "15Min" → "15m"
    "30Min" → "30m"
    "1Hour" → "1h"
    "1Day"  → "1d"

Vedi app.core.config: alpaca_enabled, alpaca_api_key, alpaca_api_secret,
alpaca_base_url, alpaca_feed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.candle import Candle
from app.schemas.market_data import MarketDataIngestRequest, MarketDataIngestResponse

logger = logging.getLogger(__name__)

# ── Costanti provider ────────────────────────────────────────────────────────
ALPACA_PROVIDER_ID: str = "alpaca"
ALPACA_VENUE_LABEL: str = "ALPACA_US"

# Mapping timeframe DB → Alpaca timeframe string
_TF_DB_TO_ALPACA: dict[str, str] = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "1d": "1Day",
}

ALPACA_ALLOWED_TIMEFRAMES: frozenset[str] = frozenset(_TF_DB_TO_ALPACA.keys())
DEFAULT_ALPACA_TIMEFRAMES: tuple[str, ...] = ("5m", "1h")

# Simboli US stocks supportati (stessa lista di Yahoo Finance)
from app.core.yahoo_finance_constants import ALLOWED_YAHOO_SYMBOLS as _ALLOWED_SYMBOLS
from app.core.yahoo_finance_constants import YAHOO_SYMBOL_ASSET_TYPE

ALPACA_ALLOWED_SYMBOLS: frozenset[str] = _ALLOWED_SYMBOLS

# Max barre per request (limite Alpaca API)
_ALPACA_PAGE_LIMIT: int = 10_000
# Delay tra pagine consecutive dello stesso simbolo (Alpaca free: 200 req/min)
_REQUEST_DELAY_S: float = 0.35
# Upsert chunk size
_UPSERT_CHUNK_SIZE: int = 2_000
# Richieste parallele simultanee verso Alpaca (semaforo — safe per free tier)
_FETCH_CONCURRENCY: int = 5
# Tentativi retry su errori di rete transienti
_FETCH_MAX_RETRIES: int = 3


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


async def _chunked_upsert_candles(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
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


async def _fetch_bars_paginated(
    client: httpx.AsyncClient,
    symbol: str,
    alpaca_tf: str,
    start: datetime,
    end: datetime,
    feed: str,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """
    Scarica tutte le barre OHLCV per un (symbol, timeframe, start, end) con paginazione.
    Restituisce lista di dict Alpaca bar: {t, o, h, l, c, v, vw, n}.
    Retry automatico su ConnectError/Timeout (max _FETCH_MAX_RETRIES tentativi).
    """
    url = f"{settings.alpaca_base_url}/stocks/{symbol}/bars"
    params: dict[str, Any] = {
        "timeframe": alpaca_tf,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": _ALPACA_PAGE_LIMIT,
        "adjustment": "split",  # gestisce stock split automaticamente
        "feed": feed,
    }

    all_bars: list[dict[str, Any]] = []
    page = 0
    while True:
        page += 1
        data: dict[str, Any] | None = None
        for attempt in range(1, _FETCH_MAX_RETRIES + 1):
            try:
                async with semaphore:
                    resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                break
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt == _FETCH_MAX_RETRIES:
                    raise
                wait = 2**attempt
                logger.warning(
                    "alpaca: %s symbol=%s tf=%s attempt=%d/%d — retry in %ds",
                    type(exc).__name__,
                    symbol,
                    alpaca_tf,
                    attempt,
                    _FETCH_MAX_RETRIES,
                    wait,
                )
                await asyncio.sleep(wait)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 422:
                    logger.warning(
                        "alpaca: symbol=%s tf=%s non supportato o assente (422) — skip",
                        symbol,
                        alpaca_tf,
                    )
                    return []
                if status == 403:
                    logger.warning(
                        "alpaca: simbolo=%s feed=%s → 403 Forbidden; "
                        "prova feed='iex' oppure verifica abbonamento",
                        symbol,
                        feed,
                    )
                    return []
                raise

        assert data is not None
        bars: list[dict[str, Any]] = data.get("bars") or []
        all_bars.extend(bars)

        next_token: str | None = data.get("next_page_token")
        if not next_token or not bars:
            break

        params["page_token"] = next_token
        await asyncio.sleep(_REQUEST_DELAY_S)

    logger.debug(
        "alpaca: symbol=%s tf=%s → %d barre scaricate in %d paginazioni",
        symbol,
        alpaca_tf,
        len(all_bars),
        page,
    )
    return all_bars


async def _fetch_symbol_tf(
    client: httpx.AsyncClient,
    symbol: str,
    tf: str,
    start_dt: datetime,
    end_dt: datetime,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Fetch bars per una coppia (symbol, tf). Restituisce (symbol, tf, bars).
    In caso di errore di rete definitivo logga e restituisce lista vuota
    per non interrompere il batch degli altri simboli."""
    alpaca_tf = _TF_DB_TO_ALPACA[tf]
    try:
        bars = await _fetch_bars_paginated(
            client,
            symbol=symbol,
            alpaca_tf=alpaca_tf,
            start=start_dt,
            end=end_dt,
            feed=settings.alpaca_feed,
            semaphore=semaphore,
        )
    except Exception:
        logger.exception(
            "alpaca: fetch fallito definitivamente symbol=%s tf=%s",
            symbol,
            tf,
        )
        return symbol, tf, []
    return symbol, tf, bars


class AlpacaIngestionService:
    """Provider Alpaca v2 — storico OHLCV US stocks con paginazione."""

    provider_id: str = ALPACA_PROVIDER_ID

    async def ingest(
        self,
        session: AsyncSession,
        request: MarketDataIngestRequest,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> MarketDataIngestResponse:
        """
        Scarica e salva barre OHLCV Alpaca per simboli/timeframe richiesti.

        Args:
            session: AsyncSession SQLAlchemy
            request: simboli e timeframe (limit ignorato — Alpaca usa start/end)
            start: data inizio (default: alpaca_backfill_years anni fa)
            end: data fine (default: now UTC)
        """
        if not settings.alpaca_enabled:
            raise RuntimeError(
                "Alpaca non abilitato: imposta ALPACA_ENABLED=true e le credenziali in .env"
            )
        if not settings.alpaca_api_key or not settings.alpaca_api_secret:
            raise RuntimeError(
                "Credenziali Alpaca mancanti: imposta ALPACA_API_KEY e ALPACA_API_SECRET in .env"
            )

        symbols = tuple(request.symbols) if request.symbols else tuple(ALPACA_ALLOWED_SYMBOLS)
        timeframes = tuple(request.timeframes) if request.timeframes else DEFAULT_ALPACA_TIMEFRAMES

        invalid_sym = set(symbols) - ALPACA_ALLOWED_SYMBOLS
        if invalid_sym:
            raise ValueError(f"simboli non supportati da Alpaca ingestion: {sorted(invalid_sym)}")
        invalid_tf = set(timeframes) - ALPACA_ALLOWED_TIMEFRAMES
        if invalid_tf:
            raise ValueError(
                f"timeframe non supportati (consentiti: {sorted(ALPACA_ALLOWED_TIMEFRAMES)}): "
                f"{sorted(invalid_tf)}"
            )

        now_utc = datetime.now(UTC)
        end_dt = end or now_utc.replace(second=0, microsecond=0)
        start_dt = start or (end_dt - timedelta(days=365 * settings.alpaca_backfill_years))

        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
        }

        candles_received = 0
        incomplete_candles_dropped = 0
        rows_inserted = 0
        rows: list[dict[str, Any]] = []

        # Fetch parallelo di tutte le coppie (symbol, tf) con semaforo per rate limiting
        semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            tasks = [
                _fetch_symbol_tf(client, symbol, tf, start_dt, end_dt, semaphore)
                for symbol in symbols
                for tf in timeframes
            ]
            logger.info(
                "alpaca: avvio fetch parallelo %d task (concurrency=%d)",
                len(tasks),
                _FETCH_CONCURRENCY,
            )
            fetch_results: list[tuple[str, str, list[dict[str, Any]]]] = await asyncio.gather(*tasks)

        # Elaborazione risultati (sequenziale — solo CPU, nessuna I/O)
        for symbol, tf, bars in fetch_results:
            asset_type = YAHOO_SYMBOL_ASSET_TYPE.get(symbol, "stock")
            alpaca_tf = _TF_DB_TO_ALPACA[tf]

            if not bars:
                logger.warning(
                    "alpaca: nessuna barra symbol=%s tf=%s [%s → %s]",
                    symbol,
                    tf,
                    start_dt.date(),
                    end_dt.date(),
                )
                continue

            # Scarta l'ultima barra: potrebbe essere ancora in formazione
            # (identico al comportamento Yahoo Finance e Binance)
            if len(bars) < 2:
                continue
            bars = bars[:-1]
            incomplete_candles_dropped += 1

            for bar in bars:
                ts_str: str = bar.get("t", "")
                try:
                    ts_utc = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    logger.warning(
                        "alpaca: timestamp non valido symbol=%s tf=%s t=%r — skip",
                        symbol,
                        tf,
                        ts_str,
                    )
                    continue

                if ts_utc.tzinfo is None:
                    ts_utc = ts_utc.replace(tzinfo=UTC)

                try:
                    o = _to_decimal(bar["o"])
                    h = _to_decimal(bar["h"])
                    low = _to_decimal(bar["l"])
                    c = _to_decimal(bar["c"])
                    vol_raw = bar.get("v")
                    vol = _to_decimal(vol_raw) if vol_raw is not None else Decimal("0")
                except (KeyError, Exception):
                    logger.warning(
                        "alpaca: barra malformata symbol=%s tf=%s t=%s — skip",
                        symbol,
                        tf,
                        ts_str,
                    )
                    continue

                meta: dict[str, Any] = {
                    "source": "alpaca",
                    "alpaca_symbol": symbol,
                    "alpaca_timeframe": alpaca_tf,
                    "alpaca_feed": settings.alpaca_feed,
                    "vwap": str(_to_decimal(bar["vw"])) if bar.get("vw") else None,
                    "trade_count": bar.get("n"),
                }

                rows.append(
                    {
                        "asset_type": asset_type,
                        "provider": self.provider_id,
                        "symbol": symbol,
                        "exchange": ALPACA_VENUE_LABEL,
                        "timeframe": tf,
                        "market_metadata": meta,
                        "timestamp": ts_utc,
                        "open": o,
                        "high": h,
                        "low": low,
                        "close": c,
                        "volume": vol,
                    }
                )
                candles_received += 1

            # Flush periodico ogni 5000 righe per non saturare la memoria
            if len(rows) >= 5000:
                rows_inserted += await _chunked_upsert_candles(session, rows)
                rows = []

        rows_inserted += await _chunked_upsert_candles(session, rows)

        return MarketDataIngestResponse(
            exchange=ALPACA_VENUE_LABEL,
            provider=self.provider_id,
            symbols=list(symbols),
            timeframes=list(timeframes),
            candles_received=candles_received,
            incomplete_candles_dropped=incomplete_candles_dropped,
            rows_inserted=rows_inserted,
        )
