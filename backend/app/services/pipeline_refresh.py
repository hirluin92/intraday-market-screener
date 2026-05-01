"""
Shared pipeline execution: ingest → features → indicators → context → patterns.

Used by the HTTP ``POST /api/v1/pipeline/refresh`` route and the in-process scheduler (MVP).
Ingest: Binance (ccxt) o Yahoo Finance (yfinance) in base a ``PipelineRefreshRequest.provider``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, timedelta
from datetime import datetime as _datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_opportunity_lookups_after_pipeline
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.schemas.context import ContextExtractRequest
from app.schemas.features import FeatureExtractRequest
from app.schemas.indicators import IndicatorExtractRequest
from app.schemas.market_data import MarketDataIngestRequest
from app.schemas.patterns import PatternExtractRequest
from app.schemas.context import ContextExtractResponse
from app.schemas.features import FeatureExtractResponse
from app.schemas.indicators import IndicatorExtractResponse
from app.schemas.patterns import PatternExtractResponse
from app.schemas.pipeline import PipelineRefreshRequest, PipelineRefreshResponse
from app.services.context_extraction import extract_context
from app.services.feature_extraction import extract_features
from app.services.indicator_extraction import extract_indicators
from app.services.binance_ingestion import MarketDataIngestionService
from app.services.alert_notifications import maybe_notify_after_pipeline_refresh
from app.services.pattern_extraction import extract_patterns
from app.services.pattern_pipeline_alerts import maybe_send_pattern_alerts_after_pipeline
from app.services.yahoo_finance_ingestion import YahooFinanceIngestionService

logger = logging.getLogger(__name__)


async def execute_pipeline_refresh(
    session: AsyncSession,
    body: PipelineRefreshRequest,
) -> PipelineRefreshResponse:
    """
    Run the full pipeline with the same semantics as ``POST /api/v1/pipeline/refresh``.

    Raises ``ValueError`` (validation) or ``ccxt.BaseError`` (Binance exchange/network).
    Provider routing:
      - "yahoo_finance" → YahooFinanceIngestionService
      - "alpaca"        → AlpacaIngestionService (incrementale: ultime ~50 barre)
      - default         → MarketDataIngestionService (Binance ccxt)
    """

    symbols = [body.symbol] if body.symbol else None
    timeframes = [body.timeframe] if body.timeframe else None

    if body.provider == "yahoo_finance":
        yahoo = YahooFinanceIngestionService()
        yahoo_ingest_limit = (
            settings.pipeline_ingest_limit_5m
            if body.timeframe in ("5m", "15m")
            else body.ingest_limit
        )
        ingest_req = MarketDataIngestRequest(
            provider="yahoo_finance",
            symbols=symbols,
            timeframes=timeframes,
            limit=yahoo_ingest_limit,
        )
        ingest_out = await yahoo.ingest(session, ingest_req)

    elif body.provider == "ibkr":
        from app.services.ibkr_ingestion import IBKRIngestionService  # noqa: PLC0415

        ibkr_svc = IBKRIngestionService()
        ingest_req = MarketDataIngestRequest(
            provider="ibkr",
            symbols=symbols,
            timeframes=timeframes,
            limit=body.ingest_limit,
            # Propaga exchange per distinguere UK (LSE) da US (SMART/YAHOO_US).
            # IBKRIngestionService usa questo valore per scegliere le coordinate DB.
            exchange=body.exchange,
        )
        ingest_out = await ibkr_svc.ingest(session, ingest_req)

    elif body.provider == "alpaca":
        from app.services.alpaca_ingestion import AlpacaIngestionService  # noqa: PLC0415

        alpaca = AlpacaIngestionService()
        ingest_req = MarketDataIngestRequest(
            provider="alpaca",
            symbols=symbols,
            timeframes=timeframes,
        )
        # Aggiornamento incrementale: ultime 2 ore (5m) o 24h (1h) per il ciclo live
        _tf = body.timeframe or "5m"
        _window = timedelta(hours=2) if _tf == "5m" else timedelta(hours=72)
        _now = _datetime.now(UTC)
        ingest_out = await alpaca.ingest(
            session,
            ingest_req,
            start=_now - _window,
            end=_now,
        )

    else:
        service = MarketDataIngestionService()
        ingest_req = MarketDataIngestRequest(
            provider="binance",
            symbols=symbols,
            timeframes=timeframes,
            limit=body.ingest_limit,
        )
        ingest_out = await service.ingest(session, ingest_req)

    # ibkr azionario USA salva nel DB come provider="yahoo_finance", exchange="YAHOO_US"
    # (alias di compatibilità legacy). La fase di extract usa quelle coordinate.
    # ibkr azionario UK (exchange="LSE") salva come provider="ibkr", exchange="LSE":
    # nessun alias — usa le coordinate native per l'estrazione.
    from app.core.yahoo_finance_constants import YAHOO_FINANCE_PROVIDER_ID, YAHOO_VENUE_LABEL  # noqa: PLC0415
    _is_ibkr_uk = body.provider == "ibkr" and (body.exchange or "").upper() == "LSE"
    if body.provider == "ibkr" and not _is_ibkr_uk:
        # US IBKR: alias su yahoo_finance/YAHOO_US
        extract_provider = YAHOO_FINANCE_PROVIDER_ID
        extract_exchange = YAHOO_VENUE_LABEL
    else:
        # UK IBKR o altri provider: usa le coordinate del body
        extract_provider = body.provider
        extract_exchange = body.exchange

    # Skip extraction se nessuna candela nuova è stata inserita (es. mercato chiuso,
    # refresh infra-minuto). Risparmia 25-40s per simbolo su cicli a vuoto.
    #
    # NOTA: rows_inserted==0 può indicare sia "nessun dato nuovo" (caso normale) sia
    # "ingest fallito silenziosamente". I servizi di ingest lanciano eccezioni su errori
    # hard (rete, exchange) che propagano prima di arrivare qui. Se rows_inserted==0
    # senza eccezione, significa che l'API ha risposto correttamente ma non aveva
    # candele nuove — l'estrazione produrrebbe gli stessi risultati del ciclo precedente,
    # quindi saltare è corretto. Monitorare il count di skip via log INFO: se durante
    # mercato aperto si superano 10-15 skip su 83 job, indagare l'ingest.
    if body.skip_if_unchanged and ingest_out.rows_inserted == 0:
        logger.info(
            "pipeline skip_if_unchanged: nessuna nuova candela per %s/%s/%s"
            " (rows_inserted=0) — extraction saltata",
            body.provider,
            body.symbol,
            body.timeframe,
        )
        return PipelineRefreshResponse(
            ingest=ingest_out,
            features=FeatureExtractResponse(
                series_processed=0, candles_read=0, candles_featured=0, rows_upserted=0
            ),
            indicators=IndicatorExtractResponse(
                series_processed=0, candles_read=0, indicators_upserted=0
            ),
            context=ContextExtractResponse(
                series_processed=0, features_read=0, contexts_upserted=0
            ),
            patterns=PatternExtractResponse(
                series_processed=0,
                rows_read=0,
                features_skipped_no_context=0,
                patterns_upserted=0,
                patterns_detected=0,
            ),
            extraction_skipped=True,
        )

    feat_req = FeatureExtractRequest(
        symbol=body.symbol,
        exchange=extract_exchange,
        provider=extract_provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
    )
    ctx_req = ContextExtractRequest(
        symbol=body.symbol,
        exchange=extract_exchange,
        provider=extract_provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
        lookback=body.lookback,
    )
    pat_req = PatternExtractRequest(
        symbol=body.symbol,
        exchange=extract_exchange,
        provider=extract_provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
    )

    # Step 1: features (gli altri step dipendono da CandleFeature)
    features_out = await extract_features(session, feat_req)

    ind_req = IndicatorExtractRequest(
        symbol=body.symbol,
        exchange=extract_exchange,
        provider=extract_provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
    )

    # Step 2: indicators + context in parallelo su sessioni indipendenti.
    # extract_features ha già fatto commit → i dati CandleFeature sono visibili
    # a nuove connessioni. Usare sessioni separate evita conflitti su asyncpg
    # (una AsyncSession non supporta operazioni concorrenti sulla stessa connessione).
    async def _run_indicators() -> object:
        async with AsyncSessionLocal() as s:
            return await extract_indicators(s, ind_req)

    async def _run_context() -> object:
        async with AsyncSessionLocal() as s:
            return await extract_context(s, ctx_req)

    indicators_out, context_out = await asyncio.gather(
        _run_indicators(),
        _run_context(),
    )

    # Step 3: patterns (legge CandleFeature + CandleContext + CandleIndicator).
    # Sessione fresca: garantisce visibilità dei CandleContext scritti in Step 2
    # dalle sessioni parallele (READ COMMITTED — la sessione originale potrebbe
    # avere uno snapshot precedente al commit di Step 2).
    async with AsyncSessionLocal() as _pat_session:
        patterns_out = await extract_patterns(_pat_session, pat_req)

    try:
        await maybe_send_pattern_alerts_after_pipeline(session, body)
    except Exception:
        # Doppio guardrail: gli alert non devono mai far fallire il pipeline.
        logging.getLogger(__name__).exception(
            "pattern alerts hook failed after extract_patterns (ignored)"
        )

    if settings.alert_legacy_enabled:
        async with AsyncSessionLocal() as _notify_session:
            await maybe_notify_after_pipeline_refresh(_notify_session, body)
    else:
        logger.debug(
            "alert legacy disabilitato (ALERT_LEGACY_ENABLED=false) — "
            "solo alert pattern via alert_service / pattern_pipeline_alerts"
        )

    await invalidate_opportunity_lookups_after_pipeline(
        provider=extract_provider,
        exchange=(extract_exchange or "").strip(),
        timeframe=body.timeframe,
    )

    try:
        from app.services.auto_execute_service import maybe_ibkr_auto_execute_after_pipeline

        await maybe_ibkr_auto_execute_after_pipeline(session, body)
    except Exception:
        logger.exception("IBKR auto-execute hook failed after pipeline (ignored)")

    return PipelineRefreshResponse(
        ingest=ingest_out,
        features=features_out,
        indicators=indicators_out,
        context=context_out,
        patterns=patterns_out,
        extraction_skipped=False,
    )
