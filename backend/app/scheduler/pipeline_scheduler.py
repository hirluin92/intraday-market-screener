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

    # Alpaca 5m: aggiunto solo se ALPACA_ENABLED=true (credenziali configurate)
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


async def _run_scheduled_pipeline_cycle() -> None:
    """Un tick: esegue la pipeline per ogni job configurato."""
    mode = settings.pipeline_scheduler_source.strip().lower()

    if _uses_explicit_scheduler_list(mode):
        t0 = time.perf_counter()
        alpaca_count = len(SCHEDULER_SYMBOLS_ALPACA_5M) if settings.alpaca_enabled else 0
        logger.info(
            "Scheduler ciclo: refreshing %d simboli Yahoo 1h + %d Binance 1h%s",
            len(SCHEDULER_SYMBOLS_YAHOO_1H),
            len(SCHEDULER_SYMBOLS_BINANCE_1H),
            f" + {alpaca_count} Alpaca 5m" if alpaca_count else "",
        )
        try:
            jobs = _resolve_scheduler_jobs()
        except ValueError as e:
            logger.error("pipeline scheduler: invalid configuration — %s", e)
            return

        ok = 0
        failed = 0
        for spec in jobs:
            symbol = spec["symbol"]
            timeframe = spec["timeframe"]
            provider = spec["provider"]
            job_key = f"{provider}|{symbol}|{timeframe}"
            logger.info(
                "pipeline scheduler: processing symbol=%s timeframe=%s provider=%s",
                symbol,
                timeframe,
                provider,
            )
            t_job = time.perf_counter()
            try:
                async with AsyncSessionLocal() as session:
                    body = PipelineRefreshRequest(
                        provider=provider,
                        exchange=None,
                        symbol=symbol,
                        timeframe=timeframe,
                        ingest_limit=spec["ingest_limit"],
                        extract_limit=spec["extract_limit"],
                        lookback=spec["lookback"],
                    )
                    await asyncio.wait_for(
                        execute_pipeline_refresh(session, body),
                        timeout=_JOB_TIMEOUT_SECONDS,
                    )
                elapsed_job = time.perf_counter() - t_job
                ok += 1
                _consecutive_failures[job_key] = 0
                logger.info(
                    "pipeline scheduler: refresh succeeded symbol=%s timeframe=%s provider=%s elapsed=%.2fs",
                    symbol,
                    timeframe,
                    provider,
                    elapsed_job,
                )
            except asyncio.TimeoutError:
                failed += 1
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
                failed += 1
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

        elapsed = time.perf_counter() - t0
        logger.info(
            "Scheduler ciclo completato in %.1fs — prossimo tra %ds",
            elapsed,
            settings.pipeline_refresh_interval_seconds,
        )
        logger.info(
            "pipeline scheduler: refresh cycle finished (ok=%d failed=%d)",
            ok,
            failed,
        )
        await _prewarm_opportunities_cache()
        return

    try:
        jobs = _resolve_scheduler_jobs()
    except ValueError as e:
        logger.error("pipeline scheduler: invalid configuration — %s", e)
        return

    n = len(jobs)
    logger.info(
        "pipeline scheduler: refresh cycle started (jobs=%d, mode=%s, interval_s=%d)",
        n,
        settings.pipeline_scheduler_source,
        settings.pipeline_refresh_interval_seconds,
    )
    if n == 0:
        logger.warning(
            "pipeline scheduler: no jobs to run (empty universe or tag filter excludes all)",
        )

    ok = 0
    failed = 0

    for item in jobs:
        if isinstance(item, tuple):
            symbol, timeframe, provider, exchange = item
            asset_note = "legacy"
        else:
            job = item
            symbol, timeframe, provider, exchange = (
                job.symbol,
                job.timeframe,
                job.provider,
                job.exchange,
            )
            asset_note = job.asset_type

        logger.info(
            "pipeline scheduler: processing symbol=%s timeframe=%s provider=%s exchange=%s (%s)",
            symbol,
            timeframe,
            provider,
            exchange,
            asset_note,
        )
        job_key = f"{provider}|{symbol}|{timeframe}"
        t_job = time.perf_counter()
        try:
            async with AsyncSessionLocal() as session:
                body = PipelineRefreshRequest(
                    provider=provider,
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    ingest_limit=settings.pipeline_ingest_limit,
                    extract_limit=settings.pipeline_extract_limit,
                    lookback=settings.pipeline_lookback,
                )
                await asyncio.wait_for(
                    execute_pipeline_refresh(session, body),
                    timeout=_JOB_TIMEOUT_SECONDS,
                )
            elapsed_job = time.perf_counter() - t_job
            ok += 1
            _consecutive_failures[job_key] = 0
            logger.info(
                "pipeline scheduler: refresh succeeded symbol=%s timeframe=%s provider=%s elapsed=%.2fs",
                symbol,
                timeframe,
                provider,
                elapsed_job,
            )
        except asyncio.TimeoutError:
            failed += 1
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
            failed += 1
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

    logger.info(
        "pipeline scheduler: refresh cycle finished (ok=%d failed=%d)",
        ok,
        failed,
    )
    await _prewarm_opportunities_cache()


async def _prewarm_opportunities_cache() -> None:
    """Pre-warm del cache opportunità globale dopo ogni ciclo scheduler.

    Dopo il ciclo, tutte le cache pq/tpb/var per-simbolo sono state invalidate.
    Questo step esegue list_opportunities per le combinazioni più comuni
    (yahoo 1h e binance 1h) così la prima chiamata frontend trova il cache caldo.
    """
    t0 = time.perf_counter()
    combos = [
        {"provider": "yahoo_finance", "timeframe": "1h"},
        {"provider": "binance", "timeframe": "1h"},
    ]
    total = 0
    for combo in combos:
        try:
            async with AsyncSessionLocal() as session:
                rows = await asyncio.wait_for(
                    list_opportunities(
                        session,
                        symbol=None,
                        exchange=None,
                        provider=combo["provider"],
                        asset_type=None,
                        timeframe=combo["timeframe"],
                        limit=500,
                    ),
                    timeout=90.0,
                )
                total += len(rows)
        except asyncio.TimeoutError:
            logger.warning(
                "pipeline scheduler: prewarm opportunities timeout provider=%s timeframe=%s",
                combo["provider"], combo["timeframe"],
            )
        except Exception:
            logger.exception(
                "pipeline scheduler: prewarm opportunities failed provider=%s timeframe=%s",
                combo["provider"], combo["timeframe"],
            )
    elapsed = time.perf_counter() - t0
    logger.info(
        "pipeline scheduler: prewarm opportunities completato in %.1fs — %d serie pronte",
        elapsed, total,
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


def shutdown_pipeline_scheduler() -> None:
    """Stop the scheduler (waits for running job if any)."""
    global _scheduler

    if _scheduler is None:
        return
    logger.info("pipeline scheduler: shutting down")
    _scheduler.shutdown(wait=True)
    _scheduler = None
    logger.info("pipeline scheduler: stopped")
