import logging

import ccxt.async_support as ccxt
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.schemas.features import FeatureExtractRequest, FeatureExtractResponse
from app.schemas.market_data import (
    CandleRow,
    CandlesListResponse,
    MarketDataIngestRequest,
    MarketDataIngestResponse,
)
from app.services.candle_query import list_stored_candles
from app.services.feature_extraction import extract_features
from app.services.market_data_ingestion import MarketDataIngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-data", tags=["market-data"])
_ingestion = MarketDataIngestionService()


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


@router.post("/features/extract", response_model=FeatureExtractResponse)
async def extract_candle_features(
    body: FeatureExtractRequest,
    session: AsyncSession = Depends(get_db_session),
) -> FeatureExtractResponse:
    return await extract_features(session, body)


@router.post("/ingest", response_model=MarketDataIngestResponse)
async def ingest_market_data(
    body: MarketDataIngestRequest,
    session: AsyncSession = Depends(get_db_session),
) -> MarketDataIngestResponse:
    try:
        return await _ingestion.ingest(session, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ccxt.BaseError as e:
        logger.exception("ccxt exchange error")
        raise HTTPException(status_code=502, detail=str(e)) from e
