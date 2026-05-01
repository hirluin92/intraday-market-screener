from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.timeframes import ALLOWED_TIMEFRAMES_SET
from app.core.yahoo_finance_constants import YAHOO_ALLOWED_TIMEFRAMES_SET


class MarketDataIngestRequest(BaseModel):
    """Manual trigger for OHLCV ingestion."""

    provider: Literal["binance", "yahoo_finance", "alpaca", "ibkr"] = Field(
        default="binance",
        description=(
            "binance: ccxt crypto spot (default). "
            "yahoo_finance: US equities/ETFs via yfinance (see Yahoo MVP universe). "
            "alpaca: Alpaca Data API v2 US stocks/ETFs (storico 5m lungo, IEX o SIP feed)."
        ),
    )
    symbols: list[str] | None = Field(
        default=None,
        description="Symbols: crypto pairs for Binance (e.g. BTC/USDT); tickers for Yahoo (e.g. SPY).",
    )
    timeframes: list[str] | None = Field(
        default=None,
        description="Depends on provider: Binance defaults 1m,5m,15m,1h,1d; Yahoo defaults 1d,1h (15m/5m on-demand).",
    )
    limit: int = Field(
        default=2500,
        ge=1,
        le=20_000,
        description=(
            "Barre OHLCV da richiedere per simbolo/timeframe. "
            "Yahoo Finance 1d: fino a ~2500 barre (period=10y). "
            "Yahoo Finance 1h: fino a ~3500 barre (period=730d). "
            "Yahoo Finance 5m/15m: fino a ~60d di storico (period); su intraday il tail non taglia come su 1h/1d. "
            "Binance ccxt: max 1000 per chiamata singola senza paginazione. "
        ),
    )
    exchange: str | None = Field(
        default=None,
        description=(
            "Exchange di destinazione (opzionale). Usato da IBKRIngestionService per distinguere "
            "US (None/'SMART') da UK ('LSE'). Ignorato da Yahoo Finance e Binance."
        ),
    )

    @model_validator(mode="after")
    def _validate_timeframes_for_provider(self) -> MarketDataIngestRequest:
        if self.timeframes is None:
            return self
        _ALPACA_TF = frozenset({"1m", "5m", "15m", "30m", "1h", "1d"})
        if self.provider == "binance":
            bad = set(self.timeframes) - ALLOWED_TIMEFRAMES_SET
            if bad:
                raise ValueError(f"unsupported timeframes for Binance: {sorted(bad)}")
        elif self.provider == "alpaca":
            bad = set(self.timeframes) - _ALPACA_TF
            if bad:
                raise ValueError(f"unsupported timeframes for Alpaca: {sorted(bad)}")
        else:
            bad = set(self.timeframes) - YAHOO_ALLOWED_TIMEFRAMES_SET
            if bad:
                raise ValueError(f"unsupported timeframes for Yahoo Finance: {sorted(bad)}")
        return self


class MarketDataIngestResponse(BaseModel):
    exchange: str
    provider: str = Field(
        default="binance",
        description="Data provider id (binance | yahoo_finance).",
    )
    symbols: list[str]
    timeframes: list[str]
    candles_received: int = Field(
        description="OHLCV rows kept after validation (excludes open/incomplete last candle per batch).",
    )
    incomplete_candles_dropped: int = Field(
        description="How many trailing candles were excluded as still-open periods (one per non-empty batch).",
    )
    rows_inserted: int = Field(
        description="PostgreSQL driver rowcount for bulk INSERT ... ON CONFLICT DO NOTHING; not a strict audit count.",
    )


class CandleRow(BaseModel):
    """Single stored OHLCV row (API shape)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: str = Field(
        default="crypto",
        description="Instrument class: crypto | stock | etf | index.",
    )
    provider: str = Field(
        default="binance",
        description="Data provider / connector id (e.g. binance for ccxt crypto).",
    )
    symbol: str
    exchange: str = Field(
        description="Venue / exchange id for the connector (e.g. binance).",
    )
    timeframe: str
    market_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional session/market hooks (timezone, session id, etc.).",
    )
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    created_at: datetime


class CandlesListResponse(BaseModel):
    candles: list[CandleRow]
    count: int
