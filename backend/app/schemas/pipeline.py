from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.core.extract_scope import validate_extract_timeframe_for_scope
from app.core.yahoo_finance_constants import YAHOO_VENUE_LABEL
from app.schemas.context import ContextExtractResponse
from app.schemas.features import FeatureExtractResponse
from app.schemas.indicators import IndicatorExtractResponse
from app.schemas.market_data import MarketDataIngestResponse
from app.schemas.patterns import PatternExtractResponse


class PipelineRefreshRequest(BaseModel):
    """Run ingest → features → indicators → context → patterns with the same optional series filters."""

    provider: Literal["binance", "yahoo_finance"] = Field(
        default="binance",
        description="binance: ccxt ingest. yahoo_finance: yfinance US equities/ETFs.",
    )
    exchange: str | None = Field(
        default=None,
        description="Venue per gli extract (default: binance o YAHOO_US in base al provider).",
    )
    symbol: str | None = Field(
        default=None,
        description="If set, restricts ingest to this symbol and passes through to extract steps.",
    )
    timeframe: str | None = Field(
        default=None,
        description="If set, restricts ingest and extract; TF ammessi dipendono dal provider.",
    )
    ingest_limit: int = Field(
        default=2500,
        ge=1,
        le=10_000,
        description="Barre OHLCV per simbolo/timeframe (ingest). 2500 default; Yahoo 5m usa anche pipeline_ingest_limit_5m.",
    )
    extract_limit: int = Field(
        default=5000,
        ge=1,
        le=10_000,
        description="Max barre per serie in feature/context/pattern extraction.",
    )
    lookback: int = Field(
        default=50,
        ge=3,
        le=200,
        description="Finestra rolling context (barre). 50 più stabile di 20 su TF lunghi.",
    )

    @model_validator(mode="after")
    def _default_exchange_and_timeframe(self) -> Self:
        if self.exchange is None or (
            isinstance(self.exchange, str) and not self.exchange.strip()
        ):
            self.exchange = (
                YAHOO_VENUE_LABEL if self.provider == "yahoo_finance" else "binance"
            )
        validate_extract_timeframe_for_scope(self.timeframe, self.provider, self.exchange)
        return self


class PipelineRefreshResponse(BaseModel):
    ingest: MarketDataIngestResponse
    features: FeatureExtractResponse
    indicators: IndicatorExtractResponse
    context: ContextExtractResponse
    patterns: PatternExtractResponse
