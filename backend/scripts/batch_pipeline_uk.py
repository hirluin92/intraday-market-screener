"""
Batch pipeline su storico UK (LSE).

Esegue le fasi di estrazione (features → indicators → context → patterns) sui dati
storici già presenti nel DB dopo il backfill.
NON esegue ingest: i dati IBKR sono già in candles con provider='ibkr', exchange='LSE'.

Uso:
    python -m scripts.batch_pipeline_uk [--symbols SYM,...] [--timeframe TF] [--concurrency N] [--dry-run]

Esempi:
    # Fase 3B: tutti i 30 FTSE 1h
    python -m scripts.batch_pipeline_uk

    # Fase 4A: solo regime anchor ISF.L 1d
    python -m scripts.batch_pipeline_uk --symbols ISF.L --timeframe 1d

    python -m scripts.batch_pipeline_uk --symbols AZN,HSBA --concurrency 2
    python -m scripts.batch_pipeline_uk --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field

# ── bootstrap path ────────────────────────────────────────────────────────────
# Lo script è invocato come "python -m scripts.batch_pipeline_uk" dalla root del
# package backend → sys.path include già la directory backend.

from app.core.uk_universe import (
    UK_EXCHANGE,
    UK_PROVIDER,
    UK_REGIME_ANCHOR,
    UK_SYMBOLS_FTSE100_TOP30,
    UK_TIMEFRAMES,
)
from app.core.yahoo_finance_constants import YAHOO_FINANCE_PROVIDER_ID, YAHOO_VENUE_LABEL
from app.db.session import AsyncSessionLocal
from app.schemas.context import ContextExtractRequest
from app.schemas.features import FeatureExtractRequest
from app.schemas.indicators import IndicatorExtractRequest
from app.schemas.patterns import PatternExtractRequest
from app.services.context_extraction import extract_context
from app.services.feature_extraction import extract_features
from app.services.indicator_extraction import extract_indicators
from app.services.pattern_extraction import extract_patterns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── costanti ──────────────────────────────────────────────────────────────────

# Copertura massima: 3 anni di 1h ≈ 6780 candele + margine
_EXTRACT_LIMIT: int = 8_000

# Finestra rolling context (barre)
_LOOKBACK: int = 50

# Parallelismo default: 4 simboli contemporanei (ogni simbolo apre ~3 sessioni DB)
_DEFAULT_CONCURRENCY: int = 4


# ── struttura risultato per simbolo ──────────────────────────────────────────

@dataclass
class SymbolResult:
    symbol: str
    timeframe: str
    ok: bool = False
    features: int = 0
    indicators: int = 0
    contexts: int = 0
    patterns: int = 0
    elapsed_s: float = 0.0
    error: str = ""


# ── pipeline per singolo simbolo/timeframe ───────────────────────────────────

async def _run_pipeline(symbol: str, timeframe: str, dry_run: bool) -> SymbolResult:
    result = SymbolResult(symbol=symbol, timeframe=timeframe)
    t0 = time.monotonic()

    if dry_run:
        logger.info("DRY-RUN  %s/%s — saltato", symbol, timeframe)
        result.ok = True
        result.elapsed_s = 0.0
        return result

    # Regime anchor (^FTSE) usa Yahoo Finance; tutti gli altri simboli UK usano IBKR/LSE
    is_regime_anchor = (symbol == UK_REGIME_ANCHOR)
    _provider = YAHOO_FINANCE_PROVIDER_ID if is_regime_anchor else UK_PROVIDER
    _exchange = YAHOO_VENUE_LABEL if is_regime_anchor else UK_EXCHANGE

    try:
        feat_req = FeatureExtractRequest(
            symbol=symbol,
            exchange=_exchange,
            provider=_provider,
            timeframe=timeframe,
            limit=_EXTRACT_LIMIT,
        )
        ind_req = IndicatorExtractRequest(
            symbol=symbol,
            exchange=_exchange,
            provider=_provider,
            timeframe=timeframe,
            limit=_EXTRACT_LIMIT,
        )
        ctx_req = ContextExtractRequest(
            symbol=symbol,
            exchange=_exchange,
            provider=_provider,
            timeframe=timeframe,
            limit=_EXTRACT_LIMIT,
            lookback=_LOOKBACK,
        )
        pat_req = PatternExtractRequest(
            symbol=symbol,
            exchange=_exchange,
            provider=_provider,
            timeframe=timeframe,
            limit=_EXTRACT_LIMIT,
        )

        # Step 1: features (prerequisito per tutti gli altri)
        async with AsyncSessionLocal() as session:
            feat_out = await extract_features(session, feat_req)
        result.features = feat_out.rows_upserted

        # Step 2: indicators + context in parallelo su sessioni indipendenti
        async def _run_indicators() -> object:
            async with AsyncSessionLocal() as s:
                return await extract_indicators(s, ind_req)

        async def _run_context() -> object:
            async with AsyncSessionLocal() as s:
                return await extract_context(s, ctx_req)

        ind_out, ctx_out = await asyncio.gather(_run_indicators(), _run_context())
        result.indicators = ind_out.indicators_upserted
        result.contexts = ctx_out.contexts_upserted

        # Step 3: patterns (legge CandleFeature + CandleContext + CandleIndicator)
        async with AsyncSessionLocal() as session:
            pat_out = await extract_patterns(session, pat_req)
        result.patterns = pat_out.patterns_upserted

        result.ok = True
        result.elapsed_s = time.monotonic() - t0

        logger.info(
            "OK  %s/%s  feat=%d  ind=%d  ctx=%d  pat=%d  (%.1fs)",
            symbol, timeframe,
            result.features, result.indicators, result.contexts, result.patterns,
            result.elapsed_s,
        )

    except Exception as exc:
        result.elapsed_s = time.monotonic() - t0
        result.error = str(exc)
        logger.error("ERRORE  %s/%s: %s", symbol, timeframe, exc)

    return result


# ── esecuzione batch con semaforo ─────────────────────────────────────────────

async def _run_batch(
    symbols: list[str],
    timeframes: list[str],
    concurrency: int,
    dry_run: bool,
) -> list[SymbolResult]:
    sem = asyncio.Semaphore(concurrency)
    results: list[SymbolResult] = []

    async def _guarded(sym: str, tf: str) -> SymbolResult:
        async with sem:
            return await _run_pipeline(sym, tf, dry_run)

    tasks = [_guarded(sym, tf) for sym in symbols for tf in timeframes]
    results = await asyncio.gather(*tasks)
    return list(results)


# ── main ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Batch pipeline UK storico")
    p.add_argument(
        "--symbols",
        default="",
        help=(
            "Subset simboli CSV (default: tutti i 30 FTSE UK). "
            f"Usa '{UK_REGIME_ANCHOR}' per il regime anchor (Fase 4A)."
        ),
    )
    p.add_argument(
        "--timeframe",
        default="",
        help=(
            "Timeframe da processare (default: quelli in UK_TIMEFRAMES = 1h). "
            "Usa '1d' per il regime anchor ISF.L."
        ),
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help=f"Simboli in parallelo (default: {_DEFAULT_CONCURRENCY})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Stampa il piano senza eseguire nulla",
    )
    return p.parse_args()


async def main() -> None:
    args = _parse_args()

    # Set allargato che include simboli trading + regime anchor
    _all_known = frozenset(UK_SYMBOLS_FTSE100_TOP30) | {UK_REGIME_ANCHOR}

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        unknown = [s for s in symbols if s not in _all_known]
        if unknown:
            logger.warning("Simboli non nell'universo UK ignorati: %s", unknown)
            symbols = [s for s in symbols if s in _all_known]
        if not symbols:
            logger.error("Nessun simbolo valido — uscita")
            sys.exit(1)
    else:
        symbols = list(UK_SYMBOLS_FTSE100_TOP30)

    if args.timeframe:
        timeframes = [args.timeframe.strip()]
    else:
        timeframes = list(UK_TIMEFRAMES)
    total_jobs = len(symbols) * len(timeframes)
    est_minutes = total_jobs * 15 / 60  # ~15s per simbolo su storico 3 anni

    logger.info("=" * 60)
    logger.info("UK BATCH PIPELINE — configurazione")
    logger.info("  Simboli     : %d (%s)", len(symbols), ", ".join(symbols))
    logger.info("  Timeframe   : %s", ", ".join(timeframes))
    logger.info("  Job totali  : %d", total_jobs)
    logger.info("  Concurrency : %d", args.concurrency)
    logger.info("  Extract lim : %d candele/serie", _EXTRACT_LIMIT)
    logger.info("  Tempo stimato: ~%.0f minuti", est_minutes / args.concurrency)
    logger.info("  Dry-run     : %s", args.dry_run)
    logger.info("=" * 60)

    t_start = time.monotonic()
    results = await _run_batch(symbols, timeframes, args.concurrency, args.dry_run)
    elapsed = time.monotonic() - t_start

    # ── riepilogo ──────────────────────────────────────────────────────────────
    ok = [r for r in results if r.ok]
    errors = [r for r in results if not r.ok]

    logger.info("")
    logger.info("=" * 60)
    logger.info("UK BATCH PIPELINE — COMPLETATO in %.1fs", elapsed)
    logger.info("  OK      : %d job", len(ok))
    logger.info("  Errori  : %d job", len(errors))
    if ok:
        logger.info("  Feature upserted : %d", sum(r.features for r in ok))
        logger.info("  Indicator upserted: %d", sum(r.indicators for r in ok))
        logger.info("  Context upserted : %d", sum(r.contexts for r in ok))
        logger.info("  Pattern upserted : %d", sum(r.patterns for r in ok))
    if errors:
        logger.info("")
        logger.info("  ERRORI DETTAGLIO:")
        for r in errors:
            logger.info("    %-8s %s: %s", r.symbol, r.timeframe, r.error)
    logger.info("=" * 60)
    logger.info("")
    logger.info("Prossimo step — Fase 3C: validazione su dati UK:")
    logger.info("  docker compose exec backend python -m scripts.validate_uk_signals")


if __name__ == "__main__":
    asyncio.run(main())
