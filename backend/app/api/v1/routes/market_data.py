import logging

import ccxt.async_support as ccxt
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_market_data_ingestion_service
from app.schemas.context import (
    ContextExtractRequest,
    ContextExtractResponse,
    ContextListResponse,
    ContextRow,
)
from app.schemas.features import (
    FeatureExtractRequest,
    FeatureExtractResponse,
    FeatureRow,
    FeaturesListResponse,
)
from app.schemas.indicators import IndicatorExtractRequest, IndicatorExtractResponse, IndicatorRow, IndicatorsListResponse
from app.schemas.patterns import (
    PatternExtractRequest,
    PatternExtractResponse,
    PatternRow,
    PatternsListResponse,
)
from app.schemas.market_data import (
    CandleRow,
    CandlesListResponse,
    MarketDataIngestRequest,
    MarketDataIngestResponse,
)
from app.schemas.timeframe_fields import OptionalAllMarketsTimeframe
from app.services.candle_query import list_stored_candles
from app.services.context_extraction import extract_context
from app.services.context_query import list_stored_contexts
from app.services.feature_extraction import extract_features
from app.services.feature_query import list_stored_features
from app.services.indicator_extraction import extract_indicators
from app.services.indicator_query import list_stored_indicators
from app.services.pattern_extraction import extract_patterns
from app.services.pattern_query import list_stored_patterns
from app.services.binance_ingestion import MarketDataIngestionService
from app.services.ibkr_ingestion import IBKRIngestionService
from app.services.yahoo_finance_ingestion import YahooFinanceIngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/candles", response_model=CandlesListResponse)
async def get_candles(
    symbol: str | None = Query(
        default=None,
        description="Filter by instrument (e.g. BTC/USDT, SPY). Omit for recent candles across symbols.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Venue id (e.g. binance, YAHOO_US). Omit to include all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Data provider id (e.g. binance, yahoo_finance). Omit to include all providers.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (e.g. 1m, 1d). Omit for all timeframes.",
    ),
    limit: int = Query(default=500, ge=1, le=10_000),
    session: AsyncSession = Depends(get_db_session),
) -> CandlesListResponse:
    rows = await list_stored_candles(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
    )
    candles = [CandleRow.model_validate(r) for r in rows]
    return CandlesListResponse(candles=candles, count=len(candles))


@router.get("/features", response_model=FeaturesListResponse)
async def get_candle_features(
    symbol: str | None = Query(
        default=None,
        description="Filter by instrument. Omit for recent rows across symbols.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id. Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (e.g. 5m, 1d). Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> FeaturesListResponse:
    rows = await list_stored_features(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
    )
    features = [FeatureRow.model_validate(r) for r in rows]
    return FeaturesListResponse(features=features, count=len(features))


@router.get("/indicators", response_model=IndicatorsListResponse)
async def get_candle_indicators(
    symbol: str | None = Query(
        default=None,
        description="Filter by instrument. Omit for recent rows across symbols.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id. Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (e.g. 5m, 1d). Omit for all timeframes.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=5000,
        description="Massimo righe restituite (ordine timestamp desc). Fino a 5000 per analisi storiche.",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> IndicatorsListResponse:
    rows = await list_stored_indicators(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
    )
    indicators = [IndicatorRow.model_validate(r) for r in rows]
    return IndicatorsListResponse(indicators=indicators, count=len(indicators))


@router.post("/indicators/extract", response_model=IndicatorExtractResponse)
async def extract_candle_indicators(
    body: IndicatorExtractRequest,
    session: AsyncSession = Depends(get_db_session),
) -> IndicatorExtractResponse:
    return await extract_indicators(session, body)


@router.get("/context", response_model=ContextListResponse)
async def get_market_context(
    symbol: str | None = Query(
        default=None,
        description="Filter by instrument. Omit for all symbols.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id. Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (e.g. 5m, 1d). Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> ContextListResponse:
    rows = await list_stored_contexts(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        limit=limit,
    )
    contexts = [ContextRow.model_validate(r) for r in rows]
    return ContextListResponse(contexts=contexts, count=len(contexts))


@router.get("/patterns", response_model=PatternsListResponse)
async def get_patterns(
    symbol: str | None = Query(
        default=None,
        description="Filter by instrument. Omit for all symbols.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by venue id. Omit for all venues.",
    ),
    provider: str | None = Query(
        default=None,
        description="Filter by data provider (binance, yahoo_finance). Omit for all.",
    ),
    asset_type: str | None = Query(
        default=None,
        description="Filter by asset class (crypto, stock, etf, index). Omit for all.",
    ),
    timeframe: OptionalAllMarketsTimeframe = Query(
        default=None,
        description="Filter by timeframe (e.g. 5m, 1d). Omit for all timeframes.",
    ),
    pattern_name: str | None = Query(
        default=None,
        description="Filter by pattern name (e.g. impulsive_bullish_candle). Omit for all patterns.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=5000,
        description="Massimo righe restituite (ordine timestamp desc). Fino a 5000 per analisi batch.",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PatternsListResponse:
    rows = await list_stored_patterns(
        session,
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        asset_type=asset_type,
        timeframe=timeframe,
        pattern_name=pattern_name,
        limit=limit,
    )
    patterns = [PatternRow.model_validate(r) for r in rows]
    return PatternsListResponse(patterns=patterns, count=len(patterns))


@router.post("/features/extract", response_model=FeatureExtractResponse)
async def extract_candle_features(
    body: FeatureExtractRequest,
    session: AsyncSession = Depends(get_db_session),
) -> FeatureExtractResponse:
    return await extract_features(session, body)


@router.post("/context/extract", response_model=ContextExtractResponse)
async def extract_market_context(
    body: ContextExtractRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ContextExtractResponse:
    return await extract_context(session, body)


@router.post("/patterns/extract", response_model=PatternExtractResponse)
async def extract_candle_patterns(
    body: PatternExtractRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PatternExtractResponse:
    return await extract_patterns(session, body)


@router.post("/ingest", response_model=MarketDataIngestResponse)
async def ingest_market_data(
    body: MarketDataIngestRequest,
    session: AsyncSession = Depends(get_db_session),
    service: MarketDataIngestionService = Depends(get_market_data_ingestion_service),
) -> MarketDataIngestResponse:
    if body.provider == "yahoo_finance":
        yahoo = YahooFinanceIngestionService()
        try:
            return await yahoo.ingest(session, body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            logger.exception("yahoo finance ingestion error")
            raise HTTPException(status_code=502, detail=str(e)) from e

    if body.provider == "ibkr":
        ibkr = IBKRIngestionService()
        try:
            return await ibkr.ingest(session, body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except Exception as e:
            logger.exception("ibkr ingestion error")
            raise HTTPException(status_code=502, detail=str(e)) from e

    try:
        return await service.ingest(session, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ccxt.BaseError as e:
        logger.exception("ccxt exchange error")
        raise HTTPException(status_code=502, detail=str(e)) from e
