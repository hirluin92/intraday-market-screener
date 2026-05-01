from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.extract_scope import validate_extract_timeframe_for_scope


class ContextExtractRequest(BaseModel):
    """Trigger context classification over stored candle features."""

    symbol: str | None = Field(
        default=None,
        description="Restrict to one instrument symbol. Omit for all.",
    )
    exchange: str | None = Field(
        default=None,
        description="Restrict to venue id (e.g. binance, YAHOO_US). Omit for all venues.",
    )
    provider: Literal["binance", "yahoo_finance", "alpaca", "ibkr"] | None = Field(
        default=None,
        description="Restrict to data provider; combine with exchange for unambiguous Yahoo vs Binance.",
    )
    timeframe: str | None = Field(
        default=None,
        description=(
            "Restrict to one timeframe; allowed values depend on provider/venue "
            "(Binance: 1m,5m,15m,1h â€” Yahoo: 5m,15m,1h,1d). Omit for all timeframes."
        ),
    )
    limit: int = Field(
        default=5000,
        ge=1,
        le=50_000,
        description="Max candle-feature rows processed per series (oldest-first).",
    )
    lookback: int = Field(
        default=50,
        ge=3,
        le=200,
        description="Rolling window size (bars) for regime heuristics.",
    )

    @model_validator(mode="after")
    def _timeframe_matches_market(self) -> Self:
        validate_extract_timeframe_for_scope(self.timeframe, self.provider, self.exchange)
        return self


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
    asset_type: str = Field(default="crypto")
    provider: str = Field(default="binance")
    symbol: str
    exchange: str
    timeframe: str
    market_metadata: dict[str, Any] | None = None
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

    asset_type: str = Field(default="crypto")
    provider: str = Field(default="binance")
    exchange: str
    symbol: str
    timeframe: str
    market_metadata: dict[str, Any] | None = None
    timestamp: datetime
    market_regime: str
    volatility_regime: str
    candle_expansion: str
    direction_bias: str


class LatestScreenerResponse(BaseModel):
    snapshots: list[LatestContextSnapshot]
    count: int

