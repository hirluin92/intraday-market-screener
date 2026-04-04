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
        description="Max feature rows per series (oldest-first window). One extra prior candle is loaded for look-back only.",
    )


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
