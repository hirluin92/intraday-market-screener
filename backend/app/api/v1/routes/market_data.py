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
from app.schemas.features import FeatureExtractRequest, FeatureExtractResponse
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
from app.services.candle_query import list_stored_candles
from app.services.context_extraction import extract_context
from app.services.context_query import list_stored_contexts
from app.services.feature_extraction import extract_features
from app.services.pattern_extraction import extract_patterns
from app.services.pattern_query import list_stored_patterns
from app.services.market_data_ingestion import MarketDataIngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/candles", response_model=CandlesListResponse)
async def get_candles(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair (e.g. BTC/USDT). Omit for recent candles across symbols.",
    ),
    exchange: str = Query(
        default="binance",
        description="Exchange id (matches ingestion). Defaults to binance.",
    ),
    timeframe: str | None = Query(
        default=None,
        description="Filter by timeframe (e.g. 1m). Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> CandlesListResponse:
    rows = await list_stored_candles(
        session,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        limit=limit,
    )
    candles = [CandleRow.model_validate(r) for r in rows]
    return CandlesListResponse(candles=candles, count=len(candles))


@router.get("/context", response_model=ContextListResponse)
async def get_market_context(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair (e.g. BTC/USDT). Omit for all symbols.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by exchange id. Omit for all exchanges.",
    ),
    timeframe: str | None = Query(
        default=None,
        description="Filter by timeframe (e.g. 5m). Omit for all timeframes.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> ContextListResponse:
    rows = await list_stored_contexts(
        session,
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        limit=limit,
    )
    contexts = [ContextRow.model_validate(r) for r in rows]
    return ContextListResponse(contexts=contexts, count=len(contexts))


@router.get("/patterns", response_model=PatternsListResponse)
async def get_patterns(
    symbol: str | None = Query(
        default=None,
        description="Filter by trading pair (e.g. BTC/USDT). Omit for all symbols.",
    ),
    exchange: str | None = Query(
        default=None,
        description="Filter by exchange id. Omit for all exchanges.",
    ),
    timeframe: str | None = Query(
        default=None,
        description="Filter by timeframe (e.g. 5m). Omit for all timeframes.",
    ),
    pattern_name: str | None = Query(
        default=None,
        description="Filter by pattern name (e.g. impulsive_bullish_candle). Omit for all patterns.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> PatternsListResponse:
    rows = await list_stored_patterns(
        session,
        symbol=symbol,
        exchange=exchange,
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
    try:
        return await service.ingest(session, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ccxt.BaseError as e:
        logger.exception("ccxt exchange error")
        raise HTTPException(status_code=502, detail=str(e)) from e
