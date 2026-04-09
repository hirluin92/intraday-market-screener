from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.extract_scope import validate_extract_timeframe_for_scope


class PatternRow(BaseModel):
    """Stored detected pattern row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    candle_feature_id: int
    candle_context_id: int | None
    asset_type: str = Field(default="crypto")
    provider: str = Field(default="binance")
    symbol: str
    exchange: str
    timeframe: str
    market_metadata: dict[str, Any] | None = None
    timestamp: datetime
    pattern_name: str
    pattern_strength: Decimal
    direction: str
    created_at: datetime


class PatternsListResponse(BaseModel):
    patterns: list[PatternRow]
    count: int


class PatternExtractRequest(BaseModel):
    """Trigger pattern detection over stored candle features + market context."""

    symbol: str | None = Field(
        default=None,
        description="Restrict to one instrument symbol. Omit for all.",
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
        le=10_000,
        description="Max joined (feature, context) rows processed per series, oldest-first.",
    )

    @model_validator(mode="after")
    def _timeframe_matches_market(self) -> Self:
        validate_extract_timeframe_for_scope(self.timeframe, self.provider, self.exchange)
        return self


class PatternExtractResponse(BaseModel):
    series_processed: int
    rows_read: int = Field(
        description="Feature rows that had matching context and were evaluated for patterns.",
    )
    features_skipped_no_context: int = Field(
        description="Feature rows in scope with no CandleContext row (skipped for detection).",
    )
    patterns_upserted: int = Field(
        description="PostgreSQL driver rowcount for bulk UPSERT; approximate.",
    )
    patterns_detected: int = Field(
        description="Number of (candle, pattern_name) detections before deduplication by upsert.",
    )

