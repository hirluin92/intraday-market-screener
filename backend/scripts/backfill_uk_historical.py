"""
Backfill storico UK da IBKR per i 30 simboli FTSE 100 e il regime anchor ISF.L.

Uso:
    # Backfill completo 3 anni (default, timeframe 1h)
    docker compose exec backend python -m scripts.backfill_uk_historical

    # Backfill specifico: 1 anno, solo AZN e HSBA
    docker compose exec backend python -m scripts.backfill_uk_historical --years 1 --symbols AZN,HSBA

    # Backfill regime anchor ISF.L: 5 anni daily (una singola chiamata IBKR)
    docker compose exec backend python -m scripts.backfill_uk_historical --symbols ISF.L --years 5 --timeframe 1d

    # Dry run: mostra cosa farebbe senza scaricare né scrivere sul DB
    docker compose exec backend python -m scripts.backfill_uk_historical --dry-run

    # Riprendi dopo interruzione o pacing violation (aspetta 10 min, poi rilancia)
    docker compose exec backend python -m scripts.backfill_uk_historical --start-from HSBA

Vincoli IBKR:
    - Barre 1h: max 1 anno per chiamata → N chiamate per N anni
    - Barre 1d: max 5 anni per chiamata → una singola chiamata per ≤5 anni
    - Max 60 richieste / 10 min per ticker+barSize → pacing violation se si supera
    - Pacing conservativo: 2.5s tra chiamate dello stesso simbolo

Tempo stimato (1h):
    30 simboli × 3 anni = 90 chiamate
    ~2.5s pacing + ~5s processing = ~7.5s/chiamata → ~11 minuti totali

IMPORTANTE — prima del backfill:
    Imposta ENABLE_UK_MARKET=false nel .env e riavvia il backend, così lo
    scheduler non fa ingest UK incrementale durante il backfill (evita pacing
    violations per richieste duplicate sullo stesso ticker+barSize).
    Dopo il backfill: ripristina ENABLE_UK_MARKET=true e riavvia.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.uk_universe import (
    UK_CURRENCY,
    UK_EXCHANGE,
    UK_SYMBOL_CURRENCY_OVERRIDES,
    UK_SYMBOLS_FTSE100_TOP30,
)
from app.db.session import AsyncSessionLocal
from app.models.candle import Candle
from app.services.tws_service import TWSService

logger = logging.getLogger(__name__)

# ── Costanti rate-limiting ────────────────────────────────────────────────────

# Secondi di attesa tra richieste consecutive sullo stesso simbolo.
# 2.5s → max ~24 richieste/minuto, ben sotto il limite IBKR di 60/10min.
_PACING_SECONDS: float = 2.5

# Simboli processati in parallelo. Conservativo: IBKR supporta 6 concurrent ma
# con 3 lasciamo margine per altre connessioni TWS attive (es. scheduler US).
_MAX_CONCURRENT: int = 3

# Righe per round-trip di upsert (allineato alle ottimizzazioni esistenti).
_UPSERT_CHUNK_SIZE: int = 2_000

# Timeout per singola chiamata IBKR reqHistoricalData (1 anno di 1h).
# IBKR può richiedere fino a 60-90s per dataset grandi; 120s è conservativo.
_IBKR_TIMEOUT_S: float = 120.0


# ── Logica di backfill per singolo simbolo ───────────────────────────────────

async def _backfill_symbol(
    symbol: str,
    years: int,
    dry_run: bool,
    tws: TWSService | None = None,
    timeframe: str = "1h",
) -> dict:
    """
    Scarica e salva lo storico per un singolo simbolo UK.

    Per timeframe 1h: IBKR limita a max 1 anno per chiamata → eseguiamo `years`
    chiamate separate con end_datetime sfalsato di 1 anno ciascuna.

    Per timeframe 1d: IBKR supporta fino a 5 anni in una singola chiamata →
    una sola richiesta con duration="{years} Y".

    Args:
        tws: istanza TWSService dedicata al backfill (clientId diverso dal backend).
        timeframe: "1h" (default) o "1d" (per regime anchor ISF.L).

    Returns:
        Dict con chiavi: symbol, status, candles_fetched, candles_saved, reason.
    """
    if not dry_run and (tws is None or not tws.is_connected):
        return {
            "symbol": symbol,
            "status": "error",
            "reason": "TWS non connesso",
            "candles_fetched": 0,
            "candles_saved": 0,
        }

    all_candles: list[dict] = []
    currency = UK_SYMBOL_CURRENCY_OVERRIDES.get(symbol, UK_CURRENCY)

    if timeframe == "1d":
        # Daily: una sola chiamata con duration="{years} Y" (IBKR supporta fino a 5Y)
        duration = f"{years} Y"
        end_dt = datetime.now(UTC)
        if dry_run:
            logger.info(
                "DRY RUN  %s/%s  end=%s  duration='%s'",
                symbol, timeframe, end_dt.strftime("%Y-%m-%d"), duration,
            )
            return {"symbol": symbol, "status": "dry_run_ok", "candles_fetched": 0, "candles_saved": 0}

        logger.info(
            "%s/%s  end=%s  duration='%s'  (timeout=%.0fs)",
            symbol, timeframe, end_dt.strftime("%Y-%m-%d"), duration, _IBKR_TIMEOUT_S,
        )
        try:
            candles = await tws.get_historical_candles_backfill(  # type: ignore[union-attr]
                symbol=symbol,
                timeframe=timeframe,
                duration=duration,
                exchange=UK_EXCHANGE,
                currency=currency,
                end_datetime=end_dt,
                timeout_s=_IBKR_TIMEOUT_S,
            )
        except Exception as exc:
            logger.exception("%s/%s fetch fallito: %s", symbol, timeframe, exc)
            return {
                "symbol": symbol,
                "status": "partial_error",
                "reason": str(exc),
                "candles_fetched": 0,
                "candles_saved": 0,
            }
        if candles:
            all_candles.extend(candles)
            logger.info("%s/%s: %d candele ricevute", symbol, timeframe, len(candles))
        else:
            logger.warning("%s/%s: nessuna candela restituita da IBKR", symbol, timeframe)
    else:
        # 1h (e altri timeframe sub-daily): max 1 anno per chiamata → loop su years
        for year_offset in range(years):
            end_dt = datetime.now(UTC) - timedelta(days=year_offset * 365)

            if dry_run:
                logger.info(
                    "DRY RUN  %s/%s  chunk=%d/%d  end=%s  duration='1 Y'",
                    symbol, timeframe, year_offset + 1, years, end_dt.strftime("%Y-%m-%d"),
                )
                continue

            logger.info(
                "%s/%s  chunk=%d/%d  end=%s  duration='1 Y'  (timeout=%.0fs)",
                symbol, timeframe, year_offset + 1, years, end_dt.strftime("%Y-%m-%d"), _IBKR_TIMEOUT_S,
            )

            try:
                candles = await tws.get_historical_candles_backfill(  # type: ignore[union-attr]
                    symbol=symbol,
                    timeframe=timeframe,
                    duration="1 Y",
                    exchange=UK_EXCHANGE,
                    currency=currency,
                    end_datetime=end_dt,
                    timeout_s=_IBKR_TIMEOUT_S,
                )
            except Exception as exc:
                logger.exception("%s/%s  chunk=%d: fetch fallito: %s", symbol, timeframe, year_offset + 1, exc)
                return {
                    "symbol": symbol,
                    "status": "partial_error",
                    "reason": str(exc),
                    "candles_fetched": len(all_candles),
                    "candles_saved": 0,
                }

            if not candles:
                logger.warning(
                    "%s/%s  chunk=%d: nessuna candela restituita da IBKR",
                    symbol, timeframe, year_offset + 1,
                )
            else:
                all_candles.extend(candles)
                logger.info(
                    "%s/%s  chunk=%d: %d candele (totale accumulato: %d)",
                    symbol, timeframe, year_offset + 1, len(candles), len(all_candles),
                )

            if year_offset < years - 1:
                await asyncio.sleep(_PACING_SECONDS)

        if dry_run:
            return {"symbol": symbol, "status": "dry_run_ok", "candles_fetched": 0, "candles_saved": 0}

    if not all_candles:
        return {"symbol": symbol, "status": "no_data", "candles_fetched": 0, "candles_saved": 0}

    # Deduplica per timestamp (può esserci overlap tra chunk annuali).
    seen: set[datetime] = set()
    unique_candles: list[dict] = []
    for c in all_candles:
        ts = c.get("timestamp")
        if ts not in seen:
            seen.add(ts)
            unique_candles.append(c)

    unique_candles.sort(key=lambda c: c["timestamp"])

    rows_saved = await _upsert_candles(symbol, unique_candles, timeframe=timeframe)

    return {
        "symbol": symbol,
        "status": "ok",
        "candles_fetched": len(all_candles),
        "candles_saved": rows_saved,
    }


# ── DB upsert ─────────────────────────────────────────────────────────────────

def _safe_decimal(value: object) -> Decimal | None:
    """Converte in Decimal ignorando None e valori non validi."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


async def _upsert_candles(symbol: str, candles: list[dict], *, timeframe: str = "1h") -> int:
    """
    Upsert candele UK nel DB.

    Conflict target: (provider, exchange, symbol, timeframe, timestamp) — indice
    unique già esistente nel modello Candle.
    """
    total_saved = 0

    async with AsyncSessionLocal() as session:
        for i in range(0, len(candles), _UPSERT_CHUNK_SIZE):
            chunk = candles[i : i + _UPSERT_CHUNK_SIZE]

            rows = []
            for c in chunk:
                open_d  = _safe_decimal(c.get("open"))
                high_d  = _safe_decimal(c.get("high"))
                low_d   = _safe_decimal(c.get("low"))
                close_d = _safe_decimal(c.get("close"))
                vol_d   = _safe_decimal(c.get("volume")) or Decimal("0")

                # Salta candele con OHLC non valido (dati malformati IBKR).
                if any(v is None for v in (open_d, high_d, low_d, close_d)):
                    logger.debug("Candela saltata (OHLC invalido): %s @ %s", symbol, c.get("timestamp"))
                    continue

                rows.append({
                    "provider":  "ibkr",
                    "exchange":  UK_EXCHANGE,
                    "symbol":    symbol,
                    "timeframe": timeframe,
                    "timestamp": c["timestamp"],
                    "open":      open_d,
                    "high":      high_d,
                    "low":       low_d,
                    "close":     close_d,
                    "volume":    vol_d,
                })

            if not rows:
                continue

            stmt = pg_insert(Candle).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["provider", "exchange", "symbol", "timeframe", "timestamp"],
            )
            result = await session.execute(stmt)
            total_saved += result.rowcount or 0

        await session.commit()

    return total_saved


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill storico UK da IBKR — operazione una tantum",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--years", type=int, default=3,
        help="Anni di storico da scaricare (default: 3). Per 1d max 5; per 1h max 3.",
    )
    parser.add_argument(
        "--symbols", type=str, default=None,
        help=(
            "Simboli comma-separated, es. AZN,HSBA. Default: tutti i 30 FTSE. "
            "Usa ISF.L per il backfill del regime anchor (es. --symbols ISF.L --years 5 --timeframe 1d)."
        ),
    )
    parser.add_argument(
        "--timeframe", type=str, default="1h",
        choices=["1h", "1d", "5m", "15m"],
        help=(
            "Timeframe delle barre (default: 1h). "
            "Usa '1d' per il regime anchor ISF.L (una sola chiamata IBKR per ≤5 anni)."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Mostra cosa verrebbe scaricato senza effettuare chiamate IBKR né scrivere nel DB.",
    )
    parser.add_argument(
        "--start-from", type=str, default=None, metavar="SYMBOL",
        help="Riprendi dal simbolo indicato (utile dopo pacing violation o interruzione).",
    )
    parser.add_argument(
        "--concurrency", type=int, default=_MAX_CONCURRENT,
        help=(
            f"Simboli processati in parallelo (default: {_MAX_CONCURRENT}). "
            "Usa 1 per ridurre il rischio di pacing violation su chunk recenti."
        ),
    )
    parser.add_argument(
        "--client-id", type=int, default=11,
        help=(
            "IBKR clientId per questa connessione (default: 11). "
            "DEVE essere diverso da quello del backend (default 10) — "
            "IBKR non accetta due connessioni con lo stesso clientId."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # ── Selezione simboli ──────────────────────────────────────────────────────

    if args.symbols:
        # strip() + upper(): il punto in "ISF.L", "BP.", "BA." rimane invariato
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = list(UK_SYMBOLS_FTSE100_TOP30)

    if args.start_from:
        sym_upper = args.start_from.strip().upper()
        try:
            idx = [s.upper() for s in symbols].index(sym_upper)
            symbols = symbols[idx:]
            logger.info("Resume da: %s (%d simboli rimanenti)", sym_upper, len(symbols))
        except ValueError:
            logger.error(
                "--start-from '%s' non trovato nell'universo (%s)",
                sym_upper, ", ".join(symbols),
            )
            sys.exit(1)

    # Per 1d una sola chiamata per simbolo; per 1h una per anno per simbolo
    if args.timeframe == "1d":
        total_calls = len(symbols)
        est_minutes = int(total_calls * (5 + 2) / 60) + 1
    else:
        total_calls = len(symbols) * args.years
        est_minutes = int(total_calls * (_PACING_SECONDS + 5) / 60) + 2

    logger.info("=" * 60)
    logger.info("UK BACKFILL — configurazione")
    logger.info("  Simboli   : %d (%s)", len(symbols), ", ".join(symbols))
    logger.info("  Timeframe : %s", args.timeframe)
    logger.info("  Anni      : %d", args.years)
    logger.info("  Chiamate  : %d totali", total_calls)
    logger.info("  Tempo     : ~%d minuti stimati", est_minutes)
    logger.info("  Dry-run   : %s", args.dry_run)
    logger.info("  ClientId  : %d", args.client_id)
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("(DRY RUN — nessuna chiamata IBKR, nessuna scrittura DB)")

    # ── Connessione TWS dedicata ───────────────────────────────────────────────
    # Usiamo una istanza TWSService SEPARATA con clientId diverso dal backend.
    # Il backend gira già con clientId=10 (TWS_CLIENT_ID nel .env).
    # IBKR rifiuta due connessioni con lo stesso clientId (errore 326).

    tws: TWSService | None = None

    if not args.dry_run:
        try:
            from app.core.config import settings as _cfg  # noqa: PLC0415
            host = getattr(_cfg, "tws_host", "host.docker.internal")
            port = int(getattr(_cfg, "tws_port", 7497))
        except Exception:
            host, port = "host.docker.internal", 7497

        logger.info(
            "Connessione TWS dedicata: %s:%d  clientId=%d", host, port, args.client_id
        )
        tws = TWSService(host=host, port=port, client_id=args.client_id)
        tws.start()

        logger.info("Attesa connessione TWS (max 15s)...")
        deadline = time.monotonic() + 15
        while not tws.is_connected and time.monotonic() < deadline:
            await asyncio.sleep(0.5)

        if not tws.is_connected:
            logger.error(
                "TWS non connesso dopo 15s. Possibili cause:\n"
                "  1. TWS non è in esecuzione\n"
                "  2. API non abilitata (File → Global Config → API → Settings)\n"
                "  3. clientId %d già in uso da un'altra sessione (usa --client-id N con N libero)",
                args.client_id,
            )
            sys.exit(1)

        logger.info("TWS connesso — avvio backfill")

    # ── Backfill con concorrenza limitata ─────────────────────────────────────

    semaphore = asyncio.Semaphore(args.concurrency)
    t_start = time.monotonic()

    async def _run(sym: str) -> dict:
        async with semaphore:
            result = await _backfill_symbol(sym, args.years, args.dry_run, tws, timeframe=args.timeframe)
            # Pacing inter-simbolo: pausa prima di rilasciare il semaforo per il prossimo.
            if not args.dry_run:
                await asyncio.sleep(_PACING_SECONDS)
            return result

    results = await asyncio.gather(*[_run(s) for s in symbols])

    elapsed = time.monotonic() - t_start

    # ── Summary ───────────────────────────────────────────────────────────────

    ok_count       = sum(1 for r in results if r["status"] in ("ok", "dry_run_ok"))
    no_data_count  = sum(1 for r in results if r["status"] == "no_data")
    err_count      = sum(1 for r in results if r["status"] in ("error", "partial_error"))
    total_fetched  = sum(r.get("candles_fetched", 0) for r in results)
    total_saved    = sum(r.get("candles_saved", 0) for r in results)

    logger.info("")
    logger.info("=" * 60)
    logger.info("UK BACKFILL — COMPLETATO in %.1fs", elapsed)
    logger.info("  OK            : %d simboli", ok_count)
    logger.info("  Nessun dato   : %d simboli", no_data_count)
    logger.info("  Errori        : %d simboli", err_count)
    logger.info("  Candele fetch : %d", total_fetched)
    logger.info("  Candele DB    : %d (nuove, deduplicate)", total_saved)
    logger.info("=" * 60)

    if err_count > 0:
        logger.warning("Simboli con errori:")
        for r in results:
            if r["status"] in ("error", "partial_error"):
                logger.warning("  %-10s  %s — %s", r["symbol"], r["status"], r.get("reason", ""))
        logger.info("")
        logger.info(
            "Per riprendere dopo pacing violation (aspetta 10 min), usa:\n"
            "  python -m scripts.backfill_uk_historical --start-from %s",
            results[next(i for i, r in enumerate(results) if r["status"] in ("error", "partial_error"))]["symbol"],
        )

    if not args.dry_run and total_saved > 0:
        logger.info("")
        logger.info("Verifica DB (esegui nel container o psql):")
        logger.info(
            "  SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp)"
            " FROM candles WHERE provider='ibkr' AND exchange='LSE' AND timeframe='1h'"
            " GROUP BY symbol ORDER BY symbol;"
        )
        logger.info("")
        logger.info("Prossimo step — Fase 3B: batch pipeline su storico UK:")
        logger.info("  python -m scripts.batch_pipeline_uk")


if __name__ == "__main__":
    asyncio.run(main())
