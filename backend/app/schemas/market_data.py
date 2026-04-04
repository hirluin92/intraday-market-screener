from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MarketDataIngestRequest(BaseModel):
    """Manual trigger for OHLCV ingestion."""

    symbols: list[str] | None = Field(
        default=None,
        description="Defaults to BTC/USDT and ETH/USDT",
    )
    timeframes: list[str] | None = Field(
        default=None,
        description="Defaults to 1m, 5m, 15m, 1h",
    )
    limit: int = Field(
        default=100,
        ge=1,
        le=1500,
        description="Number of most recent candles to fetch per symbol/timeframe",
    )


class MarketDataIngestResponse(BaseModel):
    exchange: str
    symbols: list[str]
    timeframes: list[str]
    candles_fetched: int
    candles_inserted: int


class CandleRow(BaseModel):
    """Single stored OHLCV row (API shape)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    exchange: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    created_at: datetime


class CandlesListResponse(BaseModel):
    candles: list[CandleRow]
    count: int
