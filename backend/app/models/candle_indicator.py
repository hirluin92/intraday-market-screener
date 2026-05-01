"""Indicatori tecnici derivati da candele storiche (EMA, RSI, ATR, VWAP-proxy)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Numeric, PrimaryKeyConstraint, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CandleIndicator(Base):
    """Indicatori tecnici per una candela (calcolati su finestra rolling)."""

    __tablename__ = "candle_indicators"
    __table_args__ = (
        PrimaryKeyConstraint("id", "timestamp", name="pk_candle_indicators"),
        # FK non dichiarate: TimescaleDB non supporta FK tra hypertables.
        UniqueConstraint("candle_id", "timestamp", name="uq_candle_indicators_candle_id_ts"),
        Index(
            "ix_candle_indicators_exchange_symbol_timeframe_ts",
            "exchange",
            "symbol",
            "timeframe",
            "timestamp",
        ),
        # Punto query in get_indicator_for_candle_timestamp: include provider per lookup preciso.
        Index(
            "ix_candle_indicators_exchange_symbol_provider_tf_ts",
            "exchange",
            "symbol",
            "provider",
            "timeframe",
            "timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(autoincrement=True)
    candle_id: Mapped[int] = mapped_column(nullable=False)
    asset_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'crypto'"),
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'binance'"),
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ema_9: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    ema_20: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    ema_50: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)

    rsi_14: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

    atr_14: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)

    volume_ratio_vs_ma20: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

    price_vs_ema20_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    price_vs_ema50_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

    is_swing_high: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    is_swing_low: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    last_swing_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    last_swing_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)

    dist_to_swing_high_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    dist_to_swing_low_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

    structural_range_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

    price_position_in_range: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

    # VWAP (Volume Weighted Average Price)
    # Per crypto: rolling 24h; per ETF/stock: per sessione (09:30-16:00 ET)
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    price_vs_vwap_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )

    # Livelli di sessione (high/low del giorno corrente)
    session_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    session_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)

    # Opening Range (prime N barre di sessione)
    opening_range_high: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 12),
        nullable=True,
    )
    opening_range_low: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 12),
        nullable=True,
    )
    price_vs_or_high_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )
    price_vs_or_low_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )

    # Fibonacci retracement dell'ultimo impulso (swing low → swing high o viceversa)
    fib_382: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    fib_500: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    fib_618: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    dist_to_fib_382_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )
    dist_to_fib_500_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )
    dist_to_fib_618_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )

    # Fair Value Gaps (3-candle imbalance)
    in_fvg_bullish: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    in_fvg_bearish: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    fvg_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    fvg_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    dist_to_fvg_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    fvg_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fvg_filled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    # Order Block (ultima candela opposta prima dell’impulso a 3 barre)
    in_ob_bullish: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    in_ob_bearish: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    ob_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    ob_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    ob_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ob_strength: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    ob_filled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    dist_to_ob_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)

    # Funding rate Binance Futures (solo per provider=binance)
    # Valore grezzo dell'ultimo funding rate prima di questa candela
    funding_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(16, 10),
        nullable=True,
    )
    # Funding rate annualizzato % (funding_rate × 3 × 365 × 100)
    funding_rate_annualized_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    # Bias derivato dal funding rate
    funding_bias: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    # CVD — Cumulative Volume Delta (stima da OHLCV)
    volume_delta: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 4),
        nullable=True,
    )
    cvd: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 4),
        nullable=True,
    )
    cvd_normalized: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    cvd_trend: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )
    cvd_5: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 4),
        nullable=True,
    )

    # Relative Strength vs SPY (solo Yahoo: rendimento barra - rendimento SPY stesso timestamp)
    rs_vs_spy: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    rs_vs_spy_5: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    rs_signal: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
