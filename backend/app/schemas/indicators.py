"""Schemi Pydantic per indicatori tecnici."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.extract_scope import validate_extract_timeframe_for_scope


class IndicatorExtractRequest(BaseModel):
    """Trigger calcolo indicatori su candele storiche."""

    symbol: str | None = Field(default=None)
    exchange: str | None = Field(default=None)
    provider: Literal["binance", "yahoo_finance", "alpaca"] | None = Field(default=None)
    timeframe: str | None = Field(default=None)
    limit: int = Field(
        default=5000,
        ge=1,
        le=10_000,
        description="Max candele piÃ¹ recenti per serie (calcolo in ordine cronologico oldestâ†’newest).",
    )

    @model_validator(mode="after")
    def _timeframe_matches_market(self) -> Self:
        validate_extract_timeframe_for_scope(
            self.timeframe,
            self.provider,
            self.exchange,
        )
        return self


class IndicatorExtractResponse(BaseModel):
    series_processed: int
    candles_read: int
    indicators_upserted: int


class IndicatorRow(BaseModel):
    """Riga indicatori (API shape)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    candle_id: int
    asset_type: str
    provider: str
    symbol: str
    exchange: str
    timeframe: str
    timestamp: datetime
    ema_9: Decimal | None
    ema_20: Decimal | None
    ema_50: Decimal | None
    rsi_14: Decimal | None
    atr_14: Decimal | None
    volume_ratio_vs_ma20: Decimal | None
    price_vs_ema20_pct: Decimal | None
    price_vs_ema50_pct: Decimal | None
    is_swing_high: bool = False
    is_swing_low: bool = False
    last_swing_high: Decimal | None = None
    last_swing_low: Decimal | None = None
    dist_to_swing_high_pct: Decimal | None = None
    dist_to_swing_low_pct: Decimal | None = None
    structural_range_pct: Decimal | None = None
    price_position_in_range: Decimal | None = None
    vwap: Decimal | None = None
    price_vs_vwap_pct: Decimal | None = None
    session_high: Decimal | None = None
    session_low: Decimal | None = None
    opening_range_high: Decimal | None = None
    opening_range_low: Decimal | None = None
    price_vs_or_high_pct: Decimal | None = None
    price_vs_or_low_pct: Decimal | None = None
    fib_382: Decimal | None = None
    fib_500: Decimal | None = None
    fib_618: Decimal | None = None
    dist_to_fib_382_pct: Decimal | None = None
    dist_to_fib_500_pct: Decimal | None = None
    dist_to_fib_618_pct: Decimal | None = None
    in_fvg_bullish: bool = False
    in_fvg_bearish: bool = False
    fvg_high: Decimal | None = None
    fvg_low: Decimal | None = None
    dist_to_fvg_pct: Decimal | None = None
    fvg_direction: str | None = None
    fvg_filled: bool = False
    in_ob_bullish: bool = False
    in_ob_bearish: bool = False
    ob_high: Decimal | None = None
    ob_low: Decimal | None = None
    ob_direction: str | None = None
    ob_strength: Decimal | None = None
    ob_filled: bool = False
    dist_to_ob_pct: Decimal | None = None
    funding_rate: Decimal | None = None
    funding_rate_annualized_pct: Decimal | None = None
    funding_bias: str | None = None
    volume_delta: Decimal | None = None
    cvd: Decimal | None = None
    cvd_normalized: Decimal | None = None
    cvd_trend: str | None = None
    cvd_5: Decimal | None = None
    rs_vs_spy: Decimal | None = None
    rs_vs_spy_5: Decimal | None = None
    rs_signal: str | None = None
    created_at: datetime


class IndicatorsListResponse(BaseModel):
    indicators: list[IndicatorRow]
    count: int

