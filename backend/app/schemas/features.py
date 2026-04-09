from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.extract_scope import validate_extract_timeframe_for_scope


class FeatureExtractRequest(BaseModel):
    """Trigger feature extraction over stored candles."""

    symbol: str | None = Field(
        default=None,
        description="Restrict to one instrument symbol (e.g. BTC/USDT for crypto). Omit for all.",
    )
    exchange: str | None = Field(
        default=None,
        description="Restrict to venue id (e.g. binance, YAHOO_US). Omit to include all venues.",
    )
    provider: Literal["binance", "yahoo_finance", "alpaca"] | None = Field(
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
        description="Max feature rows per series (oldest-first window). One extra prior candle is loaded for look-back only.",
    )

    @model_validator(mode="after")
    def _timeframe_matches_market(self) -> Self:
        validate_extract_timeframe_for_scope(self.timeframe, self.provider, self.exchange)
        return self


class FeatureExtractResponse(BaseModel):
    series_processed: int
    candles_read: int = Field(
        description="Candle rows read from DB (includes one look-back context row per series when available).",
    )
    candles_featured: int = Field(
        description="Candles for which a feature row was computed (excludes look-back-only context rows).",
    )
    rows_upserted: int = Field(
        description="PostgreSQL driver rowcount for bulk UPSERT; may not match rows affected exactly.",
    )


class FeatureRow(BaseModel):
    """Stored candle feature row (API shape)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    candle_id: int
    asset_type: str = Field(default="crypto")
    provider: str = Field(default="binance")
    symbol: str
    exchange: str
    timeframe: str
    market_metadata: dict[str, Any] | None = None
    timestamp: datetime
    body_size: Decimal
    range_size: Decimal
    upper_wick: Decimal
    lower_wick: Decimal
    close_position_in_range: Decimal
    pct_return_1: Decimal | None
    volume_ratio_vs_prev: Decimal | None
    is_bullish: bool
    created_at: datetime


class FeaturesListResponse(BaseModel):
    features: list[FeatureRow]
    count: int

