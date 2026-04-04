from pydantic import BaseModel, Field


class FeatureExtractRequest(BaseModel):
    """Trigger feature extraction over stored candles."""

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
        description="Max candles loaded per (exchange, symbol, timeframe) series, oldest-first.",
    )


class FeatureExtractResponse(BaseModel):
    series_processed: int
    candles_processed: int
    features_upserted: int
