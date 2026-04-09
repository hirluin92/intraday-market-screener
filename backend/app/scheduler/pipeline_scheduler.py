"""
Periodic pipeline refresh (ingest → features → context → patterns).

APScheduler runs inside the FastAPI process — no Celery/Redis. Replace with a
distributed scheduler later if needed.

Default ``explicit`` / ``universe`` / ``validated_1h``: lista fissa in
``trade_plan_variant_constants`` (40 Yahoo 1h + Binance 1h + BTC/USDT 1d regime).
Solo ``registry_full`` espande ``market_universe`` con ``PIPELINE_UNIVERSE_TAGS``.
``legacy`` = Binance da PIPELINE_SYMBOLS × PIPELINE_TIMEFRAMES.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.market_universe import (
    SchedulerPipelineJob,
    iter_scheduler_jobs,
    validate_registry_timeframes,
)
from app.core.trade_plan_variant_constants import (
    SCHEDULER_SYMBOLS_ALPACA_5M,
    SCHEDULER_SYMBOLS_BINANCE_1D_REGIME,
    SCHEDULER_SYMBOLS_BINANCE_1H,
    SCHEDULER_SYMBOLS_BINANCE_5M,
    SCHEDULER_SYMBOLS_YAHOO_1H,
)
from app.core.timeframes import ALLOWED_TIMEFRAMES_SET
from app.db.session import AsyncSessionLocal
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.market_data_ingestion import (
    ALLOWED_SYMBOLS,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
)
from app.services.alert_service import cleanup_old_alerts
from app.services.opportunities import list_opportunities
from app.services.pipeline_refresh import execute_pipeline_refresh
from app.services.tws_live_candle_service import update_live_candles

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Timeout per singolo job pipeline (secondi); evita che un fetch lento blocchi il ciclo intero.
_JOB_TIMEOUT_SECONDS: float = 120.0

# Max job pipeline in parallelo. I job sono I/O-bound (network + DB) e indipendenti:
# con 4 paralleli il ciclo scende da ~450s a ~130s su 45 job da ~12s l'uno.
_PIPELINE_PARALLELISM: int = 4

# Contatore fallimenti consecutivi per job (provider|symbol|timeframe).
# Emette WARNING ogni N fallimenti senza successo.
_CONSECUTIVE_FAIL_WARN_THRESHOLD: int = 3
_consecutive_failures: dict[str, int] = {}

_PIPELINE_EXCHANGE_BINANCE = "binance"

# Stessi job della lista esplicita (non espandono tutto il registry).
_EXPLICIT_SCHEDULER_MODES: frozenset[str] = frozenset(
    {"explicit", "validated_1h", "universe"},
)


def _uses_explicit_scheduler_list(mode: str) -> bool:
    return mode.strip().lower() in _EXPLICIT_SCHEDULER_MODES


def _parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_tag_filter(raw: str) -> frozenset[str] | None:
    """Tag in minuscolo; tutti devono essere presenti su ogni voce (AND)."""
    parts = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return frozenset(parts) if parts else None


def _get_symbols_to_refresh() -> list[dict]:
    """
    Coppie da refresh per modalità esplicita (``explicit`` / ``universe`` / ``validated_1h``):
    non usa ``iter_scheduler_jobs``.
    """
    symbols: list[dict] = []

    for symbol, timeframe in SCHEDULER_SYMBOLS_YAHOO_1H:
        symbols.append(
            {
                "provider": "yahoo_finance",
                "symbol": symbol,
                "timeframe": timeframe,
                "ingest_limit": 50,
                "extract_limit": 500,
                "lookback": 50,
            },
        )

    for symbol, timeframe in SCHEDULER_SYMBOLS_BINANCE_1H:
        symbols.append(
            {
                "provider": "binance",
                "symbol": symbol,
                "timeframe": timeframe,
                "ingest_limit": 50,
                "extract_limit": 500,
                "lookback": 50,
            },
        )

    for symbol, timeframe in SCHEDULER_SYMBOLS_BINANCE_5M:
        symbols.append(
            {
                "provider": "binance",
                "symbol": symbol,
                "timeframe": timeframe,
                "ingest_limit": 50,
                "extract_limit": 500,
                "lookback": 50,
            },
        )

    for symbol, timeframe in SCHEDULER_SYMBOLS_BINANCE_1D_REGIME:
        symbols.append(
            {
                "provider": "binance",
                "symbol": symbol,
                "timeframe": timeframe,
                "ingest_limit": 500,
                "extract_limit": 500,
                "lookback": 120,
            },
        )

    # US stocks 5m: Alpaca se abilitato; altrimenti Yahoo Finance (stessi ticker, venue YAHOO_US).
    if settings.alpaca_enabled:
        for symbol, timeframe in SCHEDULER_SYMBOLS_ALPACA_5M:
            symbols.append(
                {
                    "provider": "alpaca",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "ingest_limit": 50,
                    "extract_limit": 500,
                    "lookback": 50,
                },
            )
    else:
        for symbol, timeframe in SCHEDULER_SYMBOLS_ALPACA_5M:
            symbols.append(
                {
                    "provider": "yahoo_finance",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "ingest_limit": 50,
                    "extract_limit": 500,
                    "lookback": 50,
                },
            )

    return symbols


def _resolve_symbols_and_timeframes_legacy() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Comportamento precedente: solo Binance, simboli/TF da env o default."""
    sym = _parse_csv(settings.pipeline_symbols)
    tf = _parse_csv(settings.pipeline_timeframes)
    symbols = tuple(sym) if sym else DEFAULT_SYMBOLS
    timeframes = tuple(tf) if tf else DEFAULT_TIMEFRAMES
    bad_sym = set(symbols) - ALLOWED_SYMBOLS
    if bad_sym:
        raise ValueError(f"PIPELINE_SYMBOLS contains unsupported symbols: {sorted(bad_sym)}")
    bad_tf = set(timeframes) - ALLOWED_TIMEFRAMES_SET
    if bad_tf:
        raise ValueError(f"PIPELINE_TIMEFRAMES contains unsupported timeframes: {sorted(bad_tf)}")
    return symbols, timeframes


def _resolve_scheduler_jobs() -> (
    list[SchedulerPipelineJob]
    | list[tuple[str, str, str, str]]
    | list[dict]
):
    """
    Ritorna dict espliciti (45), job registry completo, o tuple legacy Binance.
    """
    mode = settings.pipeline_scheduler_source.strip().lower()

    if _uses_explicit_scheduler_list(mode):
        return _get_symbols_to_refresh()

    if mode == "legacy":
        symbols, timeframes = _resolve_symbols_and_timeframes_legacy()
        return [
            (s, tf, "binance", _PIPELINE_EXCHANGE_BINANCE)
            for s, tf in itertools.product(symbols, timeframes)
        ]

    if mode == "registry_full":
        reg_errs = validate_registry_timeframes()
        if reg_errs:
            raise ValueError("market universe registry invalid: " + "; ".join(reg_errs))

        tag_filter = _parse_tag_filter(settings.pipeline_universe_tags)
        return iter_scheduler_jobs(tag_filter=tag_filter)

    raise ValueError(
        "pipeline_scheduler_source must be one of: explicit, validated_1h, universe, "
        "registry_full, legacy (got "
        f"{settings.pipeline_scheduler_source!r})",
    )


async def _execute_job_spec(
    *,
    provider: str,
    symbol: str,
    timeframe: str,
    exchange: str | None,
    ingest_limit: int,
    extract_limit: int,
    lookback: int,
) -> bool:
    """
    Esegue il refresh pipeline per un singolo job e aggiorna il contatore errori consecutivi.
    Ritorna True su successo, False su errore/timeout.
    Tutta la logica di retry/failure tracking è centralizzata qui.
    """
    job_key = f"{provider}|{symbol}|{timeframe}"
    t_job = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            body = PipelineRefreshRequest(
                provider=provider,
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                ingest_limit=ingest_limit,
                extract_limit=extract_limit,
                lookback=lookback,
            )
            await asyncio.wait_for(
                execute_pipeline_refresh(session, body),
                timeout=_JOB_TIMEOUT_SECONDS,
            )
        elapsed_job = time.perf_counter() - t_job
        _consecutive_failures[job_key] = 0
        logger.info(
            "pipeline scheduler: refresh succeeded symbol=%s timeframe=%s provider=%s elapsed=%.2fs",
            symbol,
            timeframe,
            provider,
            elapsed_job,
        )
        return True
    except asyncio.TimeoutError:
        _consecutive_failures[job_key] = _consecutive_failures.get(job_key, 0) + 1
        logger.error(
            "pipeline scheduler: refresh TIMEOUT (>%.0fs) symbol=%s timeframe=%s provider=%s consecutive_failures=%d",
            _JOB_TIMEOUT_SECONDS,
            symbol,
            timeframe,
            provider,
            _consecutive_failures[job_key],
        )
    except Exception:
        consec = _consecutive_failures.get(job_key, 0) + 1
        _consecutive_failures[job_key] = consec
        if consec >= _CONSECUTIVE_FAIL_WARN_THRESHOLD:
            logger.warning(
                "pipeline scheduler: refresh FALLITO %d volte consecutive symbol=%s timeframe=%s provider=%s — verificare connettivita' provider",
                consec,
                symbol,
                timeframe,
                provider,
            )
        else:
            logger.exception(
                "pipeline scheduler: refresh failed symbol=%s timeframe=%s provider=%s (consecutive=%d)",
                symbol,
                timeframe,
                provider,
                consec,
            )
    return False


def _extract_job_params(item: object) -> dict:
    """Normalizza un job (dict / tuple / SchedulerPipelineJob) in un dict uniforme."""
    if isinstance(item, dict):
        return {
            "symbol": item["symbol"],
            "timeframe": item["timeframe"],
            "provider": item["provider"],
            "exchange": None,
            "ingest_limit": item["ingest_limit"],
            "extract_limit": item["extract_limit"],
            "lookback": item["lookback"],
        }
    if isinstance(item, tuple):
        symbol, timeframe, provider, exchange = item
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "provider": provider,
            "exchange": exchange,
            "ingest_limit": settings.pipeline_ingest_limit,
            "extract_limit": settings.pipeline_extract_limit,
            "lookback": settings.pipeline_lookback,
        }
    # SchedulerPipelineJob
    job: SchedulerPipelineJob = item  # type: ignore[assignment]
    return {
        "symbol": job.symbol,
        "timeframe": job.timeframe,
        "provider": job.provider,
        "exchange": job.exchange,
        "ingest_limit": settings.pipeline_ingest_limit,
        "extract_limit": settings.pipeline_extract_limit,
        "lookback": settings.pipeline_lookback,
    }


async def _run_scheduled_pipeline_cycle() -> None:
    """Un tick: esegue la pipeline per ogni job configurato, con parallelismo limitato."""
    mode = settings.pipeline_scheduler_source.strip().lower()

    try:
        jobs = _resolve_scheduler_jobs()
    except ValueError as e:
        logger.error("pipeline scheduler: invalid configuration — %s", e)
        return

    n = len(jobs)
    if _uses_explicit_scheduler_list(mode):
        us_5m_n = len(SCHEDULER_SYMBOLS_ALPACA_5M)
        us_5m_label = (
            f" alpaca_5m={us_5m_n}" if settings.alpaca_enabled else f" yahoo_5m={us_5m_n}"
        )
        logger.info(
            "pipeline scheduler: ciclo avviato (jobs=%d, yahoo_1h=%d binance_1h=%d binance_5m=%d%s, parallelismo=%d)",
            n,
            len(SCHEDULER_SYMBOLS_YAHOO_1H),
            len(SCHEDULER_SYMBOLS_BINANCE_1H),
            len(SCHEDULER_SYMBOLS_BINANCE_5M),
            us_5m_label,
            _PIPELINE_PARALLELISM,
        )
    else:
        logger.info(
            "pipeline scheduler: refresh cycle started (jobs=%d, mode=%s, interval_s=%d, parallelismo=%d)",
            n,
            settings.pipeline_scheduler_source,
            settings.pipeline_refresh_interval_seconds,
            _PIPELINE_PARALLELISM,
        )
        if n == 0:
            logger.warning(
                "pipeline scheduler: no jobs to run (empty universe or tag filter excludes all)",
            )

    t0 = time.perf_counter()
    semaphore = asyncio.Semaphore(_PIPELINE_PARALLELISM)

    async def _run_job(item: object) -> bool:
        params = _extract_job_params(item)
        logger.info(
            "pipeline scheduler: processing symbol=%s timeframe=%s provider=%s",
            params["symbol"], params["timeframe"], params["provider"],
        )
        async with semaphore:
            return await _execute_job_spec(**params)

    results = await asyncio.gather(*[_run_job(item) for item in jobs], return_exceptions=True)

    ok = sum(1 for r in results if r is True)
    failed = len(results) - ok

    elapsed = time.perf_counter() - t0
    logger.info(
        "pipeline scheduler: refresh cycle finished in %.1fs (ok=%d failed=%d)",
        elapsed,
        ok,
        failed,
    )
    await _prewarm_opportunities_cache()


async def _prewarm_opportunities_cache() -> None:
    """Pre-warm della cache opportunità dopo ogni ciclo scheduler.

    Strategia:
    1. invalidate_all() per svuotare cache potenzialmente stale (inclusa chiave globale
       "all" che i job individuali NON invalidano, perché la loro needle ha provider/tf
       specifici che non matchano la chiave wildcard pq|*|*|*|*|*).
    2. Ricalcolo parallelo delle combinazioni comuni + combo globale "all".
       Il combo "all" (provider=None, timeframe=None) copre la query default del frontend.
    """
    from app.core.cache import (  # noqa: PLC0415
        pattern_quality_cache,
        trade_plan_backtest_cache,
        variant_best_cache,
    )

    await pattern_quality_cache.invalidate_all()
    await trade_plan_backtest_cache.invalidate_all()
    await variant_best_cache.invalidate_all()
    logger.debug("pipeline scheduler: prewarm — cache svuotata, avvio ricalcolo")

    t0 = time.perf_counter()

    # I combo sono eseguiti in parallelo; "all" è il più lento ma fondamentale per
    # le richieste frontend senza filtri (chiave globale pq|*|*|*|*|*).
    combos = [
        {"provider": "yahoo_finance", "timeframe": "1h"},
        {"provider": "binance", "timeframe": "1h"},
        {"provider": None, "timeframe": None},
    ]

    async def _prewarm_combo(combo: dict) -> int:
        prov = combo["provider"]
        tf = combo["timeframe"]
        try:
            async with AsyncSessionLocal() as session:
                rows = await asyncio.wait_for(
                    list_opportunities(
                        session,
                        symbol=None,
                        exchange=None,
                        provider=prov,
                        asset_type=None,
                        timeframe=tf,
                        limit=500,
                    ),
                    timeout=120.0,
                )
                return len(rows)
        except asyncio.TimeoutError:
            logger.warning(
                "pipeline scheduler: prewarm opportunities timeout provider=%s timeframe=%s",
                prov, tf,
            )
            return 0
        except Exception:
            logger.exception(
                "pipeline scheduler: prewarm opportunities failed provider=%s timeframe=%s",
                prov, tf,
            )
            return 0

    # return_exceptions=True: un fallimento su una combo non cancella le altre.
    # _prewarm_combo gestisce già le eccezioni interne (ritorna 0 in caso di errore),
    # ma return_exceptions difende da scenari di cancellazione esterna.
    raw = await asyncio.gather(*[_prewarm_combo(c) for c in combos], return_exceptions=True)
    counts = [r if isinstance(r, int) else 0 for r in raw]
    total = sum(counts)
    elapsed = time.perf_counter() - t0
    logger.info(
        "pipeline scheduler: prewarm opportunities completato in %.1fs — %d serie pronte (combo: %s)",
        elapsed,
        total,
        [f"{c['provider'] or 'all'}/{c['timeframe'] or 'all'}" for c in combos],
    )


async def _run_alert_sent_cleanup() -> None:
    """Elimina righe vecchie in ``alerts_sent`` (dedupe alert pattern)."""
    try:
        await cleanup_old_alerts(days_to_keep=7)
    except Exception:
        logger.exception("pipeline scheduler: alert_sent cleanup failed")


async def _run_tws_live_candle_update() -> None:
    """Aggiorna le candele live via TWS (barra corrente in formazione)."""
    try:
        result = await update_live_candles()
        if result.get("skipped"):
            return
        logger.debug(
            "tws_live_candles scheduler: ok=%d ko=%d rows=%d",
            len(result.get("symbols_ok", [])),
            len(result.get("symbols_failed", [])),
            result.get("rows_upserted", 0),
        )
    except Exception:
        logger.exception("pipeline scheduler: tws_live_candle_update failed")


def start_pipeline_scheduler() -> None:
    """
    Avvia APScheduler: job ogni 24h su ``alerts_sent``; opzionalmente refresh pipeline.
    Il cleanup gira anche se il refresh pipeline è disabilitato.
    """
    global _scheduler

    try:
        jobs = _resolve_scheduler_jobs()
        job_display: object = len(jobs)
        resolve_error = None
    except ValueError as e:
        job_display = "?"
        resolve_error = e

    mode_raw = settings.pipeline_scheduler_source.strip().lower()
    if resolve_error is None and _uses_explicit_scheduler_list(mode_raw):
        logger.warning(
            "pipeline scheduler: configuration enabled=%s interval_s=%s "
            "mode=explicit jobs=%d yahoo_1h=%d binance_1h=%d binance_1d_regime=%d",
            settings.pipeline_scheduler_enabled,
            settings.pipeline_refresh_interval_seconds,
            job_display,
            len(SCHEDULER_SYMBOLS_YAHOO_1H),
            len(SCHEDULER_SYMBOLS_BINANCE_1H),
            len(SCHEDULER_SYMBOLS_BINANCE_1D_REGIME),
        )
    else:
        logger.warning(
            "pipeline scheduler: configuration enabled=%s interval_s=%s mode=%s jobs=%s tags=%r",
            settings.pipeline_scheduler_enabled,
            settings.pipeline_refresh_interval_seconds,
            settings.pipeline_scheduler_source,
            job_display,
            settings.pipeline_universe_tags,
        )

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_alert_sent_cleanup,
        "interval",
        hours=24,
        id="alert_sent_cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    if settings.tws_enabled:
        _scheduler.add_job(
            _run_tws_live_candle_update,
            "interval",
            minutes=2,
            id="tws_live_candle_update",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("pipeline scheduler: tws_live_candle job aggiunto (ogni 2 min, orario mercato)")
    else:
        logger.debug("pipeline scheduler: tws_live_candle job saltato (TWS_ENABLED=false)")

    if not settings.pipeline_scheduler_enabled:
        _scheduler.start()
        logger.info(
            "pipeline scheduler: started (alerts_sent cleanup every 24h; pipeline disabled)",
        )
        return

    if resolve_error is not None:
        logger.error("pipeline scheduler: pipeline job not started — %s", resolve_error)
        _scheduler.start()
        logger.info("pipeline scheduler: started (alerts_sent cleanup only)")
        return

    _scheduler.add_job(
        _run_scheduled_pipeline_cycle,
        "interval",
        seconds=settings.pipeline_refresh_interval_seconds,
        id="pipeline_refresh_cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "pipeline scheduler: started (interval=%ss, alerts_sent cleanup every 24h)",
        settings.pipeline_refresh_interval_seconds,
    )
    if settings.alert_legacy_enabled:
        logger.info(
            "pipeline scheduler: legacy alert_notifications attivo dopo ogni refresh "
            "(ALERT_LEGACY_ENABLED=true; richiede anche canali e ALERT_NOTIFICATIONS_ENABLED)",
        )
    else:
        logger.info(
            "pipeline scheduler: alert legacy disabilitato (ALERT_LEGACY_ENABLED=false) — "
            "uso solo alert pattern via alert_service / pattern_pipeline_alerts",
        )


def shutdown_pipeline_scheduler() -> None:
    """Stop the scheduler (waits for running job if any)."""
    global _scheduler

    if _scheduler is None:
        return
    logger.info("pipeline scheduler: shutting down")
    _scheduler.shutdown(wait=True)
    _scheduler = None
    logger.info("pipeline scheduler: stopped")
