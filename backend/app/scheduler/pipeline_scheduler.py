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
from app.core.hour_filters import is_equity_market_active
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
    SCHEDULER_SYMBOLS_YAHOO_1D_REGIME,
    SCHEDULER_SYMBOLS_YAHOO_1H,
)
from app.core.timeframes import ALLOWED_TIMEFRAMES_SET
from app.db.session import AsyncSessionLocal
from app.schemas.pipeline import PipelineRefreshRequest
from app.services.binance_ingestion import (
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
# 300s: necessario perché maybe_ibkr_auto_execute_after_pipeline chiama list_opportunities
# alla fine del job, che calcola pq+var+tpb (~90-100s) sui simboli con cache fredda.
# Il primo ciclo dopo restart ha cache fredda → 30s estrazione + 95s backtest = ~125s > 120.
# Sui cicli successivi (cache TTL=300s) il job finisce in <30s.
_JOB_TIMEOUT_SECONDS: float = 300.0

# Max job pipeline in parallelo. Con pool_size=30+overflow=15=45 connessioni:
# 12 × 3 sessioni/job = 36 pipeline + margine per list_opportunities/prewarm.
# Riduce i batch da 11 (parallelismo=8) a 7 su 83 job.
_PIPELINE_PARALLELISM: int = 12

# Parallelismo per ciclo in modalità split (due job separati 1h + 5m).
# 5m usa 10 per ridurre i cicli da ~6 batch a ~4 (da 190s a ~120s).
# 1h rimane a 6: raro (1/ora), breve, + al :01 si sovrappone al 5m → 10+6=16 max.
# 16 job × 3 sessioni/job = 48 — leggermente sopra pool_size=45, ma sessioni non tutte aperte insieme.
_PIPELINE_PARALLELISM_SPLIT_5M: int = 10
_PIPELINE_PARALLELISM_SPLIT_1H: int = 6

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

    equity_provider = settings.equity_provider_1h
    for symbol, timeframe in SCHEDULER_SYMBOLS_YAHOO_1H:
        symbols.append(
            {
                "provider": equity_provider,
                "symbol": symbol,
                "timeframe": timeframe,
                "ingest_limit": 50,
                "extract_limit": 500,
                "lookback": 50,
                "skip_if_unchanged": True,
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
                "skip_if_unchanged": True,
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
                "skip_if_unchanged": True,
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
                "skip_if_unchanged": True,
            },
        )

    # ── SPY 1d: regime anchor US ─────────────────────────────────────────────
    # Necessario per il regime filter EMA50 US (opportunity_validator → RegimeFilter).
    # Processato dal job 1h (timeframe_filter={"1h","1d"}) ogni ora con skip_if_unchanged=True:
    # no-op per ~23h/giorno; si attiva dopo le 16:00 ET quando la candela 1d si chiude.
    for symbol, timeframe in SCHEDULER_SYMBOLS_YAHOO_1D_REGIME:
        symbols.append(
            {
                "provider": equity_provider,
                "symbol": symbol,
                "timeframe": timeframe,
                "ingest_limit": 500,
                "extract_limit": 500,
                "lookback": 120,
                "skip_if_unchanged": True,
            },
        )

    # ── Mercato UK (London Stock Exchange) ───────────────────────────────────
    # Abilitato solo se ENABLE_UK_MARKET=true. Provider: ibkr, exchange: LSE.
    # I dati vengono salvati come provider="ibkr", exchange="LSE" (non aliasati su YAHOO_US
    # come gli azionari USA, che usano una convenzione di compatibilità legacy).
    if settings.enable_uk_market:
        from app.core.uk_universe import (  # noqa: PLC0415
            UK_EXCHANGE,
            UK_PROVIDER,
            UK_SYMBOLS_FTSE100_TOP30,
            UK_TIMEFRAMES,
        )

        for symbol in UK_SYMBOLS_FTSE100_TOP30:
            for tf in UK_TIMEFRAMES:
                symbols.append(
                    {
                        "provider": UK_PROVIDER,
                        "exchange": UK_EXCHANGE,
                        "symbol": symbol,
                        "timeframe": tf,
                        "ingest_limit": 50,
                        "extract_limit": 500,
                        "lookback": 50,
                        "skip_if_unchanged": True,
                    },
                )

    # US stocks 5m: Alpaca se abilitato; altrimenti usa equity_provider_1h (ibkr → TWS,
    # yahoo_finance → yfinance diretto). TWS è preferibile a Yahoo: dati real-time vs 15min delay.
    if settings.alpaca_enabled:
        provider_5m = "alpaca"
    else:
        provider_5m = equity_provider  # "ibkr" (TWS) o "yahoo_finance" secondo EQUITY_PROVIDER_1H
    for symbol, timeframe in SCHEDULER_SYMBOLS_ALPACA_5M:
        symbols.append(
            {
                "provider": provider_5m,
                "symbol": symbol,
                "timeframe": timeframe,
                "ingest_limit": 50,
                "extract_limit": 500,
                "lookback": 50,
                "skip_if_unchanged": True,
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
    skip_if_unchanged: bool = False,
) -> tuple[bool, bool]:
    """
    Esegue il refresh pipeline per un singolo job e aggiorna il contatore errori consecutivi.
    Ritorna (success, extraction_skipped):
      - (True, False)  → refresh completato con extraction
      - (True, True)   → refresh completato ma extraction saltata (rows_inserted==0)
      - (False, False) → errore o timeout
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
                skip_if_unchanged=skip_if_unchanged,
            )
            result = await asyncio.wait_for(
                execute_pipeline_refresh(session, body),
                timeout=_JOB_TIMEOUT_SECONDS,
            )
        elapsed_job = time.perf_counter() - t_job
        _consecutive_failures.pop(job_key, None)
        if not result.extraction_skipped:
            logger.info(
                "pipeline scheduler: refresh succeeded symbol=%s timeframe=%s provider=%s elapsed=%.2fs",
                symbol,
                timeframe,
                provider,
                elapsed_job,
            )
        return (True, result.extraction_skipped)
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
    return (False, False)


def _extract_job_params(item: object) -> dict:
    """Normalizza un job (dict / tuple / SchedulerPipelineJob) in un dict uniforme."""
    if isinstance(item, dict):
        return {
            "symbol": item["symbol"],
            "timeframe": item["timeframe"],
            "provider": item["provider"],
            "exchange": item.get("exchange"),   # None per US (legacy), "LSE" per UK
            "ingest_limit": item["ingest_limit"],
            "extract_limit": item["extract_limit"],
            "lookback": item["lookback"],
            "skip_if_unchanged": item.get("skip_if_unchanged", False),
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
            "skip_if_unchanged": False,
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
        "skip_if_unchanged": False,
    }


async def _run_scheduled_pipeline_cycle(
    timeframe_filter: frozenset[str] | None = None,
    label: str = "",
    parallelism: int | None = None,
) -> None:
    """
    Un tick: esegue la pipeline per ogni job configurato, con parallelismo limitato.

    Args:
        timeframe_filter: se valorizzato, processa solo i job il cui timeframe è nel set
                          (es. frozenset({"1h","1d"}) per il ciclo 1h in split mode).
        label:            etichetta per il logging ("1h", "5m", o "" per unified).
        parallelism:      override del semaforo di concorrenza; None → usa _PIPELINE_PARALLELISM.
    """
    lbl = f"[{label}] " if label else ""
    mode = settings.pipeline_scheduler_source.strip().lower()

    try:
        jobs = _resolve_scheduler_jobs()
    except ValueError as e:
        logger.error("pipeline scheduler %sinvalid configuration — %s", lbl, e)
        return

    # ── Filtro orario per mercati equity ────────────────────────────────────
    # I job Binance (crypto 24/7) girano sempre; i job equity (yahoo/alpaca/ibkr)
    # vengono saltati fuori dalla finestra di mercato (+1h buffer pre/post apertura).
    all_jobs = jobs
    active_jobs: list = []
    skipped_market_closed: int = 0
    equity_market_active: bool = False

    for item in all_jobs:
        params = _extract_job_params(item)
        provider = params["provider"]
        if is_equity_market_active(provider):
            active_jobs.append(item)
            if provider != "binance":
                equity_market_active = True
        else:
            skipped_market_closed += 1

    if skipped_market_closed > 0:
        logger.info(
            "pipeline scheduler %s%d job equity saltati (mercato chiuso), %d attivi",
            lbl,
            skipped_market_closed,
            len(active_jobs),
        )

    jobs = active_jobs

    # ── Filtro timeframe (split mode) ────────────────────────────────────────
    # Limita i job al sottoinsieme di timeframe di questo ciclo.
    # Il filtro avviene DOPO il filtro orario: i job già saltati per mercato chiuso
    # non vengono conteggiati nel totale e non producono log fuorvianti.
    if timeframe_filter is not None:
        jobs = [j for j in jobs if _extract_job_params(j)["timeframe"] in timeframe_filter]

    n = len(jobs)
    actual_parallelism = parallelism if parallelism is not None else _PIPELINE_PARALLELISM

    if _uses_explicit_scheduler_list(mode):
        us_5m_n = len(SCHEDULER_SYMBOLS_ALPACA_5M)
        us_5m_label = (
            f" alpaca_5m={us_5m_n}" if settings.alpaca_enabled else f" yahoo_5m={us_5m_n}"
        )
        logger.info(
            "pipeline scheduler %sciclo avviato (jobs=%d, yahoo_1h=%d binance_1h=%d binance_5m=%d%s, parallelismo=%d)",
            lbl,
            n,
            len(SCHEDULER_SYMBOLS_YAHOO_1H),
            len(SCHEDULER_SYMBOLS_BINANCE_1H),
            len(SCHEDULER_SYMBOLS_BINANCE_5M),
            us_5m_label,
            actual_parallelism,
        )
    else:
        schedule_label = (
            f"cron=*/5min+{settings.pipeline_scheduler_cron_offset_s}s"
            if settings.pipeline_scheduler_align_to_5m
            else f"interval={settings.pipeline_refresh_interval_seconds}s"
        )
        logger.info(
            "pipeline scheduler %srefresh cycle started (jobs=%d, mode=%s, schedule=%s, parallelismo=%d)",
            lbl,
            n,
            settings.pipeline_scheduler_source,
            schedule_label,
            actual_parallelism,
        )
        if n == 0:
            logger.warning(
                "pipeline scheduler %sno jobs to run (empty universe or tag filter excludes all)",
                lbl,
            )

    if n == 0:
        return

    t0 = time.perf_counter()
    semaphore = asyncio.Semaphore(actual_parallelism)

    async def _run_job(item: object) -> tuple[bool, bool]:
        params = _extract_job_params(item)
        logger.info(
            "pipeline scheduler %sprocessing symbol=%s timeframe=%s provider=%s",
            lbl,
            params["symbol"], params["timeframe"], params["provider"],
        )
        async with semaphore:
            return await _execute_job_spec(**params)

    results = await asyncio.gather(*[_run_job(item) for item in jobs], return_exceptions=True)

    ok = sum(1 for r in results if isinstance(r, tuple) and r[0])
    skipped = sum(1 for r in results if isinstance(r, tuple) and r[1])
    failed = sum(1 for r in results if not isinstance(r, tuple) or not r[0])

    elapsed = time.perf_counter() - t0
    logger.info(
        "pipeline scheduler %srefresh cycle finished in %.1fs (ok=%d skipped=%d failed=%d)",
        lbl,
        elapsed,
        ok,
        skipped,
        failed,
    )

    # Soglia di allerta: durante mercato aperto, skip alti indicano problemi di ingest.
    # Soglia conservativa: >50% dei job saltati è anomalo se il mercato è aperto.
    _SKIP_WARN_THRESHOLD = n // 2
    if skipped >= _SKIP_WARN_THRESHOLD and ok > 0:
        logger.warning(
            "pipeline scheduler %s%d/%d job hanno saltato l'extraction (skip_if_unchanged). "
            "Se il mercato è aperto, verificare i log di ingest per errori silenziosi "
            "(rate limit, provider timeout, rows_inserted==0 per errore).",
            lbl,
            skipped,
            n,
        )
    # ── Prewarm cache + auto-execute scan ───────────────────────────────────
    # I due task sono indipendenti:
    #   - _prewarm_opportunities_cache: popola cache in-memory per il frontend
    #   - run_auto_execute_scan: legge opportunità, invia ordini a TWS
    #
    # In split mode, run_auto_execute_scan è scopato al timeframe del ciclo corrente
    # per evitare che due cicli sovrapposti eseguano lo stesso ordine due volte.
    async def _run_auto_execute_safe() -> None:
        if not equity_market_active:
            logger.debug("pipeline scheduler %sauto_execute_scan saltato (mercato equity chiuso)", lbl)
            return
        try:
            from app.services.auto_execute_service import run_auto_execute_scan  # noqa: PLC0415

            # In split mode: restringe la scansione ai timeframe di questo ciclo.
            # Previene doppia esecuzione se 1h e 5m girano in sovrapposizione.
            tf_scope: list[str] | None = None
            if timeframe_filter is not None:
                tf_scope = [
                    tf for tf in settings.auto_execute_timeframes_list
                    if tf in timeframe_filter
                ]
            await run_auto_execute_scan(timeframes_override=tf_scope)
        except Exception:
            logger.exception("pipeline scheduler %srun_auto_execute_scan failed (ignored)", lbl)

    t_parallel = time.perf_counter()
    parallel_results = await asyncio.gather(
        _prewarm_opportunities_cache(),
        _run_auto_execute_safe(),
        return_exceptions=True,
    )
    elapsed_parallel_ms = (time.perf_counter() - t_parallel) * 1000
    logger.info(
        "pipeline scheduler %sprewarm+auto_execute completati in %.0fms (parallelo)",
        lbl,
        elapsed_parallel_ms,
    )
    for i, result in enumerate(parallel_results):
        if isinstance(result, BaseException):
            logger.warning(
                "pipeline scheduler %sparallel task %d fallito inaspettatamente: %s",
                lbl, i, result,
            )

    if not equity_market_active:
        logger.debug("pipeline scheduler %spoll_and_record_stop_fills saltato (mercato equity chiuso)", lbl)
        return

    try:
        from app.services.auto_execute_service import (  # noqa: PLC0415
            check_and_apply_trailing_stops,
            poll_and_record_stop_fills,
            poll_and_record_tp_fills,
        )

        async with AsyncSessionLocal() as session:
            await check_and_apply_trailing_stops(session)

        async with AsyncSessionLocal() as session:
            await poll_and_record_stop_fills(session)

        async with AsyncSessionLocal() as session:
            await poll_and_record_tp_fills(session)
    except Exception:
        logger.exception("pipeline scheduler %spoll_and_record_stop/tp_fills failed (ignored)", lbl)


async def _prewarm_opportunities_cache() -> None:
    """Pre-warm della cache opportunità dopo ogni ciclo scheduler.

    Strategia:
    - Ricalcola SOLO yahoo_finance/1h e binance/1h (le chiavi specifiche che i job
      per-provider hanno appena invalidato con needle chirurgiche).
    - La chiave all/all (provider=None, timeframe=None) NON viene toccata dai job
      individuali (le loro needle non matchano i wildcard), quindi rimane valida per
      il suo TTL e beneficia dello stale-while-revalidate al momento della scadenza.
    - NON chiama invalidate_all(): evita di svuotare la chiave all/all, che richiederebbe
      un ricalcolo bloccante da 100+ secondi sul ciclo successivo.
    """

    t0 = time.perf_counter()

    # Ricalcola solo le combo i cui sotto-cache sono stati invalidati dai job per-provider.
    # La combo all/all (provider=None, timeframe=None) è gestita dal stale-while-revalidate
    # sul TTL naturale: non serve prewarm esplicito.
    combos = [
        {"provider": "yahoo_finance", "timeframe": "1h"},
        {"provider": "binance", "timeframe": "1h"},
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
    for i, r in enumerate(raw):
        if isinstance(r, BaseException):
            combo = combos[i]
            logger.warning(
                "pipeline scheduler: prewarm gather — combo %s/%s fallita inaspettatamente",
                combo.get("provider") or "all",
                combo.get("timeframe") or "all",
                exc_info=r,
            )
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
    """
    Aggiorna le candele live via TWS (barra corrente in formazione).
    Se TWS non è connesso, tenta un reconnect automatico (cooldown 60s).
    """
    try:
        from app.services.tws_service import get_tws_service  # noqa: PLC0415

        tws = get_tws_service()
        if tws is not None and not tws.is_connected:
            # Tentativo di reconnect automatico con cooldown 60s.
            # Se TWS era offline all'avvio ma ora è disponibile, questa chiamata
            # ripristina la connessione senza richiedere un restart del container.
            tws.reconnect()

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


async def _eod_close_all_positions() -> None:
    """
    Job EOD (15:55 ET, lun–ven): cancella ordini entry pendenti e chiude tutte le posizioni con MKT.

    Impedisce overnight: se un ordine entry non è stato fillato entro fine giornata viene cancellato;
    se una posizione è aperta, viene liquidata subito via MKT prima della chiusura del mercato.
    """
    if not settings.eod_close_enabled:
        logger.debug("pipeline scheduler: EOD close saltato (EOD_CLOSE_ENABLED=false)")
        return

    if not getattr(settings, "tws_enabled", False):
        logger.debug("pipeline scheduler: EOD close saltato (TWS_ENABLED=false)")
        return

    from app.services.tws_service import get_tws_service  # noqa: PLC0415

    tws = get_tws_service()
    if tws is None or not tws._ensure_started():
        logger.error("pipeline scheduler: EOD close — TWS non connesso alle 15:55 ET, SKIP CRITICO")
        try:
            from app.services.alert_notifications import send_system_alert  # noqa: PLC0415
            await send_system_alert(
                "🚨 EOD CLOSE FALLITO\n"
                "TWS non connesso alle 15:55 ET\n"
                "Posizioni aperte NON chiuse — verifica manuale richiesta prima delle 16:00 ET!"
            )
        except Exception:
            logger.exception("pipeline scheduler: EOD close — notifica failure fallita")
        return

    cancelled_orders: list[dict] = []
    closed_positions: list[dict] = []

    # ── 1. Cancella tutti gli ordini entry LMT pendenti ─────────────────────
    try:
        def _cancel_pending() -> list[dict]:
            if tws._ib is None:
                return []
            _TERMINAL = {"Filled", "Cancelled", "Inactive", "ApiCancelled"}
            pending = [
                t for t in tws._ib.openTrades()
                if t.orderStatus.status not in _TERMINAL
            ]
            results = []
            for t in pending:
                tws._ib.cancelOrder(t.order)
                results.append({
                    "order_id": t.order.orderId,
                    "symbol": t.contract.symbol,
                    "action": t.order.action,
                    "type": t.order.orderType,
                    "status": t.orderStatus.status,
                })
            return results

        import asyncio as _asyncio  # noqa: PLC0415
        cancelled_orders = await _asyncio.get_running_loop().run_in_executor(None, _cancel_pending)
        if cancelled_orders:
            logger.info("pipeline scheduler: EOD close — cancellati %d ordini: %s",
                        len(cancelled_orders), [o["symbol"] for o in cancelled_orders])
        await _asyncio.sleep(1.5)  # attendi propagazione cancellazioni
    except Exception:
        logger.exception("pipeline scheduler: EOD close — errore cancellazione ordini")

    # ── 2. Chiudi tutte le posizioni aperte con MKT ──────────────────────────
    try:
        open_positions = await tws.get_open_positions()
        for pos in open_positions:
            sym = pos.get("symbol", "")
            qty = pos.get("position", 0.0)
            currency = pos.get("currency", "USD")
            if abs(qty) < 1e-6:
                continue
            action = "SELL" if qty > 0 else "BUY"
            result = await tws.place_market_close_order(
                symbol=sym,
                action=action,
                quantity=abs(qty),
                exchange="SMART",  # always SMART — primaryExchange causes Error 10311
                currency=currency,
            )
            closed_positions.append({
                "symbol": sym, "qty": qty, "action": action,
                "result": result.get("status") or result.get("error", "?"),
            })
            logger.info("pipeline scheduler: EOD close — %s %s %.0f: %s",
                        action, sym, abs(qty), result)
    except Exception:
        logger.exception("pipeline scheduler: EOD close — errore chiusura posizioni")

    # ── 3. Notifica ──────────────────────────────────────────────────────────
    try:
        if cancelled_orders or closed_positions:
            from app.services.alert_notifications import send_system_alert  # noqa: PLC0415

            lines = ["🔔 EOD CLOSE — 15:55 ET"]
            if closed_positions:
                lines.append(f"Posizioni chiuse (MKT): {len(closed_positions)}")
                for p in closed_positions:
                    lines.append(f"  {p['action']} {p['symbol']} {abs(p['qty']):.0f}az → {p['result']}")
            if cancelled_orders:
                lines.append(f"Ordini cancellati: {len(cancelled_orders)}")
                for o in cancelled_orders:
                    lines.append(f"  {o['action']} {o['symbol']} [{o['type']}] #{o['order_id']}")
            await send_system_alert("\n".join(lines))
    except Exception:
        logger.debug("pipeline scheduler: EOD close — notifica fallita (non critico)")


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

    if settings.eod_close_enabled and getattr(settings, "tws_enabled", False):
        _scheduler.add_job(
            _eod_close_all_positions,
            "cron",
            hour=15,
            minute=55,
            day_of_week="mon-fri",
            timezone="America/New_York",
            id="eod_close_positions",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("pipeline scheduler: EOD close job aggiunto (lun-ven 15:55 ET, DST-aware)")
    else:
        logger.debug(
            "pipeline scheduler: EOD close job saltato "
            "(EOD_CLOSE_ENABLED=%s, TWS_ENABLED=%s)",
            settings.eod_close_enabled,
            getattr(settings, "tws_enabled", False),
        )

    # ── Daily regime update: SPY 1d alle 16:05 ET (dopo chiusura mercato US) ──
    # Garantisce che il regime filter EMA50 US usi la candela 1d di oggi entro 5 minuti
    # dalla chiusura. Il job 1h (timeframe_filter={"1h","1d"}) agisce già come fallback
    # ogni ora con skip_if_unchanged=True, ma questo job è il trigger primario puntuale.
    if settings.pipeline_scheduler_enabled:
        _scheduler.add_job(
            _run_scheduled_pipeline_cycle,
            "cron",
            kwargs={
                "timeframe_filter": frozenset({"1d"}),
                "label": "1d_regime",
                "parallelism": 1,
            },
            hour=16,
            minute=5,
            day_of_week="mon-fri",
            timezone="America/New_York",
            id="pipeline_1d_regime_cycle",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("pipeline scheduler: daily regime job aggiunto (lun-ven 16:05 ET, SPY 1d + BTC/USDT 1d)")

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

    sched_mode = settings.pipeline_scheduler_mode.strip().lower()

    if sched_mode == "split":
        # ── Split mode: job separati per 1h e 5m ────────────────────────────
        # Job 1h: una volta per ora a XX:01:00 (60s dopo la chiusura della candela 1h).
        # Processa timeframe 1h + 1d (regime giornaliero crypto).
        _scheduler.add_job(
            _run_scheduled_pipeline_cycle,
            "cron",
            kwargs={
                "timeframe_filter": frozenset({"1h", "1d"}),
                "label": "1h",
                "parallelism": _PIPELINE_PARALLELISM_SPLIT_1H,
            },
            minute=1,
            second=0,
            id="pipeline_1h_cycle",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        # Job 5m: ogni minuto a XX:00:10, XX:01:10, ... (10s dopo ogni minuto).
        # La barra 5m si chiude a XX:00:00/XX:05:00: viene catturata al massimo 70s dopo.
        # 4 cicli su 5 avranno rows_inserted=0 (skip_if_unchanged); costo trascurabile.
        # Rate limit Alpaca free: 29 simboli × 1 req = 29 req/min (limite: 200 req/min).
        _scheduler.add_job(
            _run_scheduled_pipeline_cycle,
            "cron",
            kwargs={
                "timeframe_filter": frozenset({"5m"}),
                "label": "5m",
                "parallelism": _PIPELINE_PARALLELISM_SPLIT_5M,
            },
            minute="*/1",
            second=settings.pipeline_scheduler_cron_offset_s,
            id="pipeline_5m_cycle",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info(
            "pipeline scheduler: started (mode=split | 1h=cron XX:01:00 | "
            "5m=cron */1min+%ds | parallelismo_5m=%d parallelismo_1h=%d | alerts_sent cleanup every 24h)",
            settings.pipeline_scheduler_cron_offset_s,
            _PIPELINE_PARALLELISM_SPLIT_5M,
            _PIPELINE_PARALLELISM_SPLIT_1H,
        )
    elif settings.pipeline_scheduler_align_to_5m:
        _scheduler.add_job(
            _run_scheduled_pipeline_cycle,
            "cron",
            minute="*/5",
            second=settings.pipeline_scheduler_cron_offset_s,
            id="pipeline_refresh_cycle",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info(
            "pipeline scheduler: started (cron=*/5min+%ds, alerts_sent cleanup every 24h)",
            settings.pipeline_scheduler_cron_offset_s,
        )
    else:
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
