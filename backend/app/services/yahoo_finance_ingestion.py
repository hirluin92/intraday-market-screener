"""
Ingestione OHLCV via Yahoo Finance (yfinance) per azioni / ETF / proxy indice.

- Usa le stesse tabelle ``candles`` del path Binance; ``provider`` = yahoo_finance.
- Fetch sincrono eseguito in thread pool per non bloccare l'event loop asyncio.
- Future: altri mercati (LSE, …) aggiungendo venue, simboli e mapping interval/period.

Vedi :mod:`app.core.yahoo_finance_constants` per timeframe e universo MVP.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.retry import with_retry
from app.core.yahoo_finance_constants import (
    ALLOWED_YAHOO_SYMBOLS,
    DEFAULT_YAHOO_SYMBOLS,
    DEFAULT_YAHOO_TIMEFRAMES,
    YAHOO_ALLOWED_TIMEFRAMES_SET,
    YAHOO_FINANCE_PROVIDER_ID,
    YAHOO_SYMBOL_ASSET_TYPE,
    YAHOO_VENUE_LABEL,
)
from app.models.candle import Candle
from app.schemas.market_data import MarketDataIngestRequest, MarketDataIngestResponse

logger = logging.getLogger(__name__)

# Timeframe intraday con limite di periodo imposto da Yahoo: usare period massimo, senza tail(ingest_limit).
_SHORT_TF_YAHOO = frozenset({"1m", "5m", "15m", "30m"})

# (timeframe_db) → (yfinance_interval, yfinance_period) — solo TF lunghi; 1m/5m/15m/30m usano _max_period_for_timeframe.
_YAHOO_TF_PARAMS: dict[str, tuple[str, str]] = {
    "1d": ("1d", "10y"),
    "1h": ("1h", "730d"),
}


def _max_period_for_timeframe(timeframe: str) -> str:
    """
    Ritorna il period massimo supportato da Yahoo Finance per timeframe.
    Documentazione yfinance: 1m=7d, 5m=60d, 15m=60d, 1h=730d, 1d=max.
    """
    return {
        "1m": "7d",
        "5m": "60d",
        "15m": "60d",
        "30m": "60d",
        "1h": "730d",
        "1d": "max",
    }.get(timeframe, "60d")


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _history_sync(ticker: str, yf_interval: str, period: str) -> Any:
    """Chiamata sincrona yfinance (eseguita in thread pool)."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    # auto_adjust=False: OHLC non modificati per split/dividend (più vicini a dati “raw”).
    return t.history(period=period, interval=yf_interval, auto_adjust=False)


_UPSERT_CHUNK_SIZE = 500


async def _chunked_upsert_candles(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
    """
    Esegue bulk upsert in chunk da _UPSERT_CHUNK_SIZE righe.
    asyncpg ha un limite di 65535 parametri per statement;
    con 12 colonne per riga il massimo teorico è ~5400 righe,
    ma 500 è conservativo e sicuro su qualsiasi configurazione.
    Restituisce il rowcount totale (approssimativo come da asyncpg).
    """
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


class YahooFinanceIngestionService:
    """Provider Yahoo Finance v1 (azioni/ETF US)."""

    provider_id: str = YAHOO_FINANCE_PROVIDER_ID

    async def ingest(
        self,
        session: AsyncSession,
        request: MarketDataIngestRequest,
    ) -> MarketDataIngestResponse:
        symbols = tuple(request.symbols) if request.symbols else DEFAULT_YAHOO_SYMBOLS
        timeframes = tuple(request.timeframes) if request.timeframes else DEFAULT_YAHOO_TIMEFRAMES

        invalid_sym = set(symbols) - ALLOWED_YAHOO_SYMBOLS
        if invalid_sym:
            raise ValueError(f"unsupported Yahoo symbols for this MVP: {sorted(invalid_sym)}")
        invalid_tf = set(timeframes) - YAHOO_ALLOWED_TIMEFRAMES_SET
        if invalid_tf:
            raise ValueError(
                f"unsupported Yahoo timeframes (allowed: {sorted(YAHOO_ALLOWED_TIMEFRAMES_SET)}): "
                f"{sorted(invalid_tf)}",
            )

        candles_received = 0
        incomplete_candles_dropped = 0
        rows: list[dict[str, Any]] = []

        for symbol in symbols:
            asset_type = YAHOO_SYMBOL_ASSET_TYPE[symbol]
            for tf in timeframes:
                if tf in _SHORT_TF_YAHOO:
                    yf_interval = tf
                    period = _max_period_for_timeframe(tf)
                else:
                    yf_interval, period = _YAHOO_TF_PARAMS[tf]
                try:
                    df = await with_retry(
                        lambda s=symbol, i=yf_interval, p=period: asyncio.to_thread(
                            _history_sync, s, i, p
                        ),
                        label=f"yahoo_finance.history({symbol},{tf})",
                        max_attempts=3,
                    )
                except Exception:
                    logger.exception(
                        "yahoo_finance: fetch failed definitivamente symbol=%s timeframe=%s",
                        symbol,
                        tf,
                    )
                    raise

                if df is None or df.empty:
                    logger.warning("yahoo_finance: empty history symbol=%s timeframe=%s", symbol, tf)
                    continue

                # Indice barra: Yahoo US spesso senza tz → assumiamo America/New_York poi UTC.
                df = df.sort_index()
                if df.index.tz is None:
                    df.index = df.index.tz_localize("America/New_York", ambiguous="infer")
                df.index = df.index.tz_convert("UTC")

                if (
                    request.limit
                    and tf not in _SHORT_TF_YAHOO
                    and len(df) > request.limit
                ):
                    df = df.tail(request.limit)

                # Ultima barra spesso ancora in formazione → stesso criterio del path Binance.
                if len(df) < 2:
                    continue
                df = df.iloc[:-1]
                incomplete_candles_dropped += 1

                if df.empty:
                    continue

                last_ts: datetime | None = None
                for ts, row in df.iterrows():
                    tsp = pd.Timestamp(ts)
                    ts_utc = tsp.to_pydatetime()
                    if ts_utc.tzinfo is None:
                        ts_utc = ts_utc.replace(tzinfo=UTC)
                    if last_ts is not None and ts_utc <= last_ts:
                        logger.warning(
                            "yahoo_finance: non-increasing ts symbol=%s tf=%s ts=%s",
                            symbol,
                            tf,
                            ts_utc,
                        )
                        continue
                    last_ts = ts_utc

                    o = _to_decimal(row["Open"])
                    h = _to_decimal(row["High"])
                    low = _to_decimal(row["Low"])
                    c = _to_decimal(row["Close"])
                    v_raw = row["Volume"] if "Volume" in row.index else None
                    if v_raw is None or pd.isna(v_raw):
                        vol = Decimal("0")
                    else:
                        vol = _to_decimal(v_raw)

                    meta: dict[str, Any] = {
                        "source": "yahoo_finance",
                        "yahoo_ticker": symbol,
                        "yahoo_interval": yf_interval,
                        "yahoo_period": period,
                    }

                    rows.append(
                        {
                            "asset_type": asset_type,
                            "provider": self.provider_id,
                            "symbol": symbol,
                            "exchange": YAHOO_VENUE_LABEL,
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

        rows_inserted = await _chunked_upsert_candles(session, rows)

        return MarketDataIngestResponse(
            exchange=YAHOO_VENUE_LABEL,
            provider=self.provider_id,
            symbols=list(symbols),
            timeframes=list(timeframes),
            candles_received=candles_received,
            incomplete_candles_dropped=incomplete_candles_dropped,
            rows_inserted=rows_inserted,
        )
