from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PatternRow(BaseModel):
    """Stored detected pattern row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    candle_feature_id: int
    candle_context_id: int | None
    symbol: str
    exchange: str
    timeframe: str
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
        description="Restrict to one pair (e.g. BTC/USDT). Omit for all symbols.",
    )
    exchange: str | None = Field(
        default=None,
        description="Restrict to exchange id (e.g. binance). Omit to include all exchanges.",
    )
    timeframe: str | None = Field(
        default=None,
        description="Restrict to one timeframe (e.g. 5m). Omit for all timeframes.",
    )
    limit: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Max joined (feature, context) rows processed per series, oldest-first.",
    )


class PatternExtractResponse(BaseModel):
    series_processed: int
    rows_read: int = Field(
        description="Joined feature+context rows read from DB (per series, up to limit).",
    )
    patterns_upserted: int = Field(
        description="PostgreSQL driver rowcount for bulk UPSERT; approximate.",
    )
    patterns_detected: int = Field(
        description="Number of (candle, pattern_name) detections before deduplication by upsert.",
    )
