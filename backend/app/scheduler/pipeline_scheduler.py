"""
Periodic pipeline refresh (ingest → features → context → patterns).

APScheduler runs inside the FastAPI process — no Celery/Redis. Replace with a
distributed scheduler later if needed.

L'universo di mercato è definito in ``app.core.market_universe`` (MVP). Modalità
``legacy`` ripristina solo coppie Binance da PIPELINE_SYMBOLS / PIPELINE_TIMEFRAMES.
"""

from __future__ import annotations

import itertools
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.market_universe import (
    SchedulerPipelineJob,
    iter_scheduler_jobs,
    validate_registry_timeframes,
)
from app.core.timeframes import ALLOWED_TIMEFRAMES_SET
from app.db.session import AsyncSessionLocal
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.market_data_ingestion import (
    ALLOWED_SYMBOLS,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
)
from app.services.pipeline_refresh import execute_pipeline_refresh

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

_PIPELINE_EXCHANGE_BINANCE = "binance"


def _parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_tag_filter(raw: str) -> frozenset[str] | None:
    """Tag in minuscolo; tutti devono essere presenti su ogni voce (AND)."""
    parts = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return frozenset(parts) if parts else None


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


def _resolve_scheduler_jobs() -> list[SchedulerPipelineJob] | list[tuple[str, str, str, str]]:
    """
    Ritorna job unificati: o da ``iter_scheduler_jobs`` (universo) o espansione legacy Binance.
    Per legacy: tuple (symbol, timeframe, provider, exchange) come pseudo-job.
    """
    if settings.pipeline_scheduler_source.strip().lower() == "legacy":
        symbols, timeframes = _resolve_symbols_and_timeframes_legacy()
        return [
            (s, tf, "binance", _PIPELINE_EXCHANGE_BINANCE)
            for s, tf in itertools.product(symbols, timeframes)
        ]

    reg_errs = validate_registry_timeframes()
    if reg_errs:
        raise ValueError("market universe registry invalid: " + "; ".join(reg_errs))

    tag_filter = _parse_tag_filter(settings.pipeline_universe_tags)
    return iter_scheduler_jobs(tag_filter=tag_filter)


async def _run_scheduled_pipeline_cycle() -> None:
    """Un tick: esegue la pipeline per ogni job configurato."""
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
                await execute_pipeline_refresh(session, body)
            ok += 1
            logger.info(
                "pipeline scheduler: refresh succeeded symbol=%s timeframe=%s provider=%s",
                symbol,
                timeframe,
                provider,
            )
        except Exception:
            failed += 1
            logger.exception(
                "pipeline scheduler: refresh failed symbol=%s timeframe=%s provider=%s",
                symbol,
                timeframe,
                provider,
            )

    logger.info(
        "pipeline scheduler: refresh cycle finished (ok=%d failed=%d)",
        ok,
        failed,
    )


def start_pipeline_scheduler() -> None:
    """Start the interval job if enabled in settings (no-op otherwise)."""
    global _scheduler

    try:
        jobs = _resolve_scheduler_jobs()
        job_display: object = len(jobs)
        mode_display = settings.pipeline_scheduler_source
        resolve_error = None
    except ValueError as e:
        job_display = "?"
        mode_display = settings.pipeline_scheduler_source
        resolve_error = e

    logger.warning(
        "pipeline scheduler: configuration enabled=%s interval_s=%s mode=%s jobs=%s tags=%r",
        settings.pipeline_scheduler_enabled,
        settings.pipeline_refresh_interval_seconds,
        mode_display,
        job_display,
        settings.pipeline_universe_tags,
    )

    if not settings.pipeline_scheduler_enabled:
        return

    if resolve_error is not None:
        logger.error("pipeline scheduler: not started — %s", resolve_error)
        return

    _scheduler = AsyncIOScheduler()
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
        "pipeline scheduler: started (interval=%ss)",
        settings.pipeline_refresh_interval_seconds,
    )
    if settings.alert_notifications_enabled:
        logger.info(
            "pipeline scheduler: alert notifications enabled — each cycle calls "
            "execute_pipeline_refresh (same hook as manual POST /api/v1/pipeline/refresh)",
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
