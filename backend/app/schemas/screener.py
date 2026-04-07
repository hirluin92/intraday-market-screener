from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RankedScreenerRow(BaseModel):
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
    screener_score: int = Field(
        description="Dominant directional score (0–12): stronger of long vs short leg.",
    )
    score_label: str = Field(
        description="Strength band + direction, e.g. strong_bullish, moderate_bearish, mild_neutral.",
    )
    score_direction: str = Field(
        description="Which side the headline score favors: bullish | bearish | neutral.",
    )
    latest_pattern_name: str | None = Field(
        default=None,
        description="Latest detected pattern for this series, if any (for quality lookup).",
    )
    pattern_quality_score: float | None = Field(
        default=None,
        description="Backtest quality 0–100 for (latest_pattern_name, timeframe), or null.",
    )
    pattern_quality_label: str = Field(
        default="unknown",
        description="high | medium | low | insufficient | unknown.",
    )


class RankedScreenerResponse(BaseModel):
    ranked: list[RankedScreenerRow]
    count: int
