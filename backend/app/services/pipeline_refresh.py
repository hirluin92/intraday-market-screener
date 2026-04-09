"""
Shared pipeline execution: ingest → features → indicators → context → patterns.

Used by the HTTP ``POST /api/v1/pipeline/refresh`` route and the in-process scheduler (MVP).
Ingest: Binance (ccxt) o Yahoo Finance (yfinance) in base a ``PipelineRefreshRequest.provider``.
"""

from __future__ import annotations

import logging
from datetime import UTC, timedelta
from datetime import datetime as _datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate_opportunity_lookups_after_pipeline
from app.core.config import settings
from app.schemas.context import ContextExtractRequest
from app.schemas.features import FeatureExtractRequest
from app.schemas.indicators import IndicatorExtractRequest
from app.schemas.market_data import MarketDataIngestRequest
from app.schemas.patterns import PatternExtractRequest
from app.schemas.pipeline import PipelineRefreshRequest, PipelineRefreshResponse
from app.services.context_extraction import extract_context
from app.services.feature_extraction import extract_features
from app.services.indicator_extraction import extract_indicators
from app.services.market_data_ingestion import MarketDataIngestionService
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
        _window = timedelta(hours=2) if _tf == "5m" else timedelta(hours=26)
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

    feat_req = FeatureExtractRequest(
        symbol=body.symbol,
        exchange=body.exchange,
        provider=body.provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
    )
    ctx_req = ContextExtractRequest(
        symbol=body.symbol,
        exchange=body.exchange,
        provider=body.provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
        lookback=body.lookback,
    )
    pat_req = PatternExtractRequest(
        symbol=body.symbol,
        exchange=body.exchange,
        provider=body.provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
    )

    features_out = await extract_features(session, feat_req)
    ind_req = IndicatorExtractRequest(
        symbol=body.symbol,
        exchange=body.exchange,
        provider=body.provider,
        timeframe=body.timeframe,
        limit=body.extract_limit,
    )
    indicators_out = await extract_indicators(session, ind_req)
    context_out = await extract_context(session, ctx_req)
    patterns_out = await extract_patterns(session, pat_req)

    try:
        await maybe_send_pattern_alerts_after_pipeline(session, body)
    except Exception:
        # Doppio guardrail: gli alert non devono mai far fallire il pipeline.
        logging.getLogger(__name__).exception(
            "pattern alerts hook failed after extract_patterns (ignored)"
        )

    if settings.alert_legacy_enabled:
        await maybe_notify_after_pipeline_refresh(session, body)
    else:
        logger.debug(
            "alert legacy disabilitato (ALERT_LEGACY_ENABLED=false) — "
            "solo alert pattern via alert_service / pattern_pipeline_alerts"
        )

    await invalidate_opportunity_lookups_after_pipeline(
        provider=body.provider,
        exchange=(body.exchange or "").strip(),
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
    )
