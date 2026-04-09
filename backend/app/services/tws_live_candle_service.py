"""
Aggiornamento live delle candele correnti (in formazione) via TWS.

Yahoo Finance fornisce solo barre completate: questo servizio riempie il gap
chiedendo a TWS i dati storici del giorno corrente (inclusa la barra parziale).

IBKR restituisce sempre tutte le barre del periodo richiesto, inclusa l'ultima
ancora aperta (la "barra corrente" aggiornata al tick più recente con delay).

Funzionamento:
  - Ogni 2 minuti (solo durante ore di mercato US), per ogni simbolo Yahoo 1h
    monitorato, richiediamo a TWS le ultime 2 barre 1h.
  - Upsert con on_conflict_do_update: la barra parziale viene aggiornata
    continuamente (OHLCV sovrascritta con i valori più recenti).
  - Usa lo stesso exchange="YAHOO_US" e provider="yahoo_finance" perché il DB
    e le query del frontend già filtrano su queste colonne.

Nota dati: TWS usa dati delayed (tipo 3, ~15-20 min) se l'account non ha
abbonamento real-time API US. Per il pattern di visualizzazione è comunque
molto meglio di aspettare la chiusura della barra.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trade_plan_variant_constants import SCHEDULER_SYMBOLS_YAHOO_1H
from app.core.yahoo_finance_constants import (
    YAHOO_FINANCE_PROVIDER_ID,
    YAHOO_SYMBOL_ASSET_TYPE,
    YAHOO_VENUE_LABEL,
)
from app.db.session import AsyncSessionLocal
from app.models.candle import Candle
from app.services.tws_service import get_tws_service

logger = logging.getLogger(__name__)

# Simboli Yahoo 1h monitorati (senza il timeframe, solo ticker)
_YAHOO_1H_SYMBOLS: list[str] = [sym for sym, tf in SCHEDULER_SYMBOLS_YAHOO_1H if tf == "1h"]

# Quante barre storiche richiedere per ogni simbolo (2 = ultima completata + corrente)
_BARS_TO_FETCH: int = 2

# Ore mercato US: 9:30-16:00 ET = 13:30-20:00 UTC
_MARKET_OPEN_UTC_H: int = 13
_MARKET_OPEN_UTC_M: int = 30
_MARKET_CLOSE_UTC_H: int = 20
_MARKET_CLOSE_UTC_M: int = 0


def _is_market_hours() -> bool:
    """True se siamo durante le ore di mercato US (Mon-Fri, 09:30-16:00 ET)."""
    now = datetime.now(tz=timezone.utc)
    if now.weekday() >= 5:  # Sabato=5, Domenica=6
        return False
    open_minutes = _MARKET_OPEN_UTC_H * 60 + _MARKET_OPEN_UTC_M
    close_minutes = _MARKET_CLOSE_UTC_H * 60 + _MARKET_CLOSE_UTC_M
    now_minutes = now.hour * 60 + now.minute
    return open_minutes <= now_minutes < close_minutes


async def _upsert_live_candles(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """
    Inserisce barre live nel DB.

    Usa on_conflict_do_update SOLO per le barre parziali (is_partial=True),
    per aggiornarle ogni 2 minuti con i prezzi più recenti.
    Le barre già completate (is_partial non impostato) usano do_nothing
    per non sovrascrivere i dati Yahoo Finance più accurati.
    """
    if not rows:
        return 0

    # Separa barre parziali da quelle complete
    partial_rows = [r for r in rows if r.get("market_metadata", {}).get("is_partial")]
    complete_rows = [r for r in rows if not r.get("market_metadata", {}).get("is_partial")]

    total = 0
    chunk_size = 100

    # Barre complete: do_nothing (Yahoo Finance ha già la versione corretta)
    for i in range(0, len(complete_rows), chunk_size):
        chunk = complete_rows[i : i + chunk_size]
        stmt = insert(Candle).values(chunk)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_candles_exchange_symbol_timeframe_timestamp",
        )
        result = await session.execute(stmt)
        rc = result.rowcount
        if rc is not None and rc >= 0:
            total += int(rc)

    # Barre parziali: do_update per aggiornare OHLCV ogni 2 minuti
    for i in range(0, len(partial_rows), chunk_size):
        chunk = partial_rows[i : i + chunk_size]
        stmt = insert(Candle).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_candles_exchange_symbol_timeframe_timestamp",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "market_metadata": stmt.excluded.market_metadata,
            },
        )
        result = await session.execute(stmt)
        rc = result.rowcount
        if rc is not None and rc >= 0:
            total += int(rc)

    await session.commit()
    return total


async def update_live_candles() -> dict[str, Any]:
    """
    Aggiorna le candele live via TWS per tutti i simboli Yahoo 1h.

    Viene chiamato dallo scheduler ogni 2 minuti durante le ore di mercato.
    Restituisce un dizionario con statistiche dell'aggiornamento.
    """
    if not _is_market_hours():
        logger.debug("tws_live_candles: fuori orario mercato, skip")
        return {"skipped": True, "reason": "outside_market_hours"}

    tws = get_tws_service()
    if tws is None or not tws.is_connected:
        logger.debug("tws_live_candles: TWS non connesso, skip")
        return {"skipped": True, "reason": "tws_not_connected"}

    symbols_ok: list[str] = []
    symbols_failed: list[str] = []
    rows: list[dict[str, Any]] = []

    for symbol in _YAHOO_1H_SYMBOLS:
        try:
            bars = await tws.get_historical_bars(
                symbol,
                duration="1 D",
                bar_size="1 hour",
                use_rth=True,
            )
            if not bars:
                logger.debug("tws_live_candles: nessuna barra per %s", symbol)
                symbols_failed.append(symbol)
                continue

            asset_type = YAHOO_SYMBOL_ASSET_TYPE.get(symbol, "stock")

            # Aggiungiamo tutte le barre ricevute (inclusa la parziale finale)
            for idx, bar in enumerate(bars):
                ts = bar.get("timestamp")
                if ts is None:
                    continue
                if not isinstance(ts, datetime):
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)

                o = bar.get("open")
                h = bar.get("high")
                low = bar.get("low")
                c = bar.get("close")
                vol = bar.get("volume") or 0.0

                # Salta barre con dati mancanti
                if any(v is None or v <= 0 for v in [o, h, low, c]):
                    continue

                is_last = idx == len(bars) - 1
                meta: dict[str, Any] = {
                    "source": "tws_live",
                    "fetched_at": datetime.now(tz=UTC).isoformat(),
                }
                if is_last:
                    meta["is_partial"] = True

                rows.append({
                    "asset_type": asset_type,
                    "provider": YAHOO_FINANCE_PROVIDER_ID,
                    "symbol": symbol,
                    "exchange": YAHOO_VENUE_LABEL,
                    "timeframe": "1h",
                    "market_metadata": meta,
                    "timestamp": ts,
                    "open": Decimal(str(round(o, 8))),
                    "high": Decimal(str(round(h, 8))),
                    "low": Decimal(str(round(low, 8))),
                    "close": Decimal(str(round(c, 8))),
                    "volume": Decimal(str(int(vol))),
                })

            symbols_ok.append(symbol)

        except Exception:
            logger.exception("tws_live_candles: errore per simbolo %s", symbol)
            symbols_failed.append(symbol)

        # Pausa breve per non sovraccaricare TWS con richieste consecutive
        await asyncio.sleep(0.3)

    rows_inserted = 0
    if rows:
        try:
            async with AsyncSessionLocal() as session:
                rows_inserted = await _upsert_live_candles(session, rows)
        except Exception:
            logger.exception("tws_live_candles: upsert fallito")

    logger.info(
        "tws_live_candles: aggiornamento completato — simboli_ok=%d simboli_ko=%d righe_db=%d",
        len(symbols_ok),
        len(symbols_failed),
        rows_inserted,
    )
    return {
        "symbols_ok": symbols_ok,
        "symbols_failed": symbols_failed,
        "rows_upserted": rows_inserted,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }
