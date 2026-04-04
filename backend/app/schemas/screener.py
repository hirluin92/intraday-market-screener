from datetime import datetime

from pydantic import BaseModel, Field


class RankedScreenerRow(BaseModel):
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


class RankedScreenerResponse(BaseModel):
    ranked: list[RankedScreenerRow]
    count: int
