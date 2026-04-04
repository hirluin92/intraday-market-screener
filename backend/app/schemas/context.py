from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ContextExtractRequest(BaseModel):
    """Trigger context classification over stored candle features."""

    symbol: str | None = Field(
        default=None,
        description="Restrict to one pair (e.g. BTC/USDT). Omit for all symbols.",
    )
    exchange: str | None = Field(
        default=None,
        description="Restrict to exchange id (e.g. binance). Omit for all exchanges.",
    )
    timeframe: str | None = Field(
        default=None,
        description="Restrict to one timeframe (e.g. 5m). Omit for all timeframes.",
    )
    limit: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Max candle-feature rows processed per series (oldest-first).",
    )
    lookback: int = Field(
        default=20,
        ge=3,
        le=200,
        description="Rolling window size (bars) for regime heuristics.",
    )


class ContextExtractResponse(BaseModel):
    series_processed: int
    features_read: int
    contexts_upserted: int = Field(
        description="PostgreSQL driver rowcount for bulk UPSERT; approximate.",
    )


class ContextRow(BaseModel):
    """Stored context classification row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    candle_feature_id: int
    symbol: str
    exchange: str
    timeframe: str
    timestamp: datetime
    market_regime: str
    volatility_regime: str
    candle_expansion: str
    direction_bias: str
    created_at: datetime


class ContextListResponse(BaseModel):
    contexts: list[ContextRow]
    count: int


class LatestContextSnapshot(BaseModel):
    """Latest context bar per (exchange, symbol, timeframe) series."""

    model_config = ConfigDict(from_attributes=True)

    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    market_regime: str
    volatility_regime: str
    candle_expansion: str
    direction_bias: str


class LatestScreenerResponse(BaseModel):
    snapshots: list[LatestContextSnapshot]
    count: int
