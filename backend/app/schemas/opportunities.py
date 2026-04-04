from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OpportunityRow(BaseModel):
    """Latest context snapshot per series plus optional latest detected pattern (computed, not persisted)."""

    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    market_regime: str
    volatility_regime: str
    candle_expansion: str
    direction_bias: str
    screener_score: int = Field(description="Additive MVP score (typically 0–12).")
    score_label: str = Field(description="Bucket: strong | moderate | mild | weak.")
    latest_pattern_name: str | None = None
    latest_pattern_strength: Decimal | None = Field(
        default=None,
        description="Strength of the latest pattern for this series, if any.",
    )
    latest_pattern_direction: str | None = None


class OpportunitiesResponse(BaseModel):
    opportunities: list[OpportunityRow]
    count: int
