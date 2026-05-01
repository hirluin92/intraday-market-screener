from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Numeric, PrimaryKeyConstraint, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CandleFeature(Base):
    """Intraday features derived from a stored candle (one row per candle)."""

    __tablename__ = "candle_features"
    __table_args__ = (
        PrimaryKeyConstraint("id", "timestamp", name="pk_candle_features"),
        # FK non dichiarate: TimescaleDB non supporta FK tra hypertables.
        # L'integrità è garantita dal pipeline applicativo.
        UniqueConstraint("candle_id", "timestamp", name="uq_candle_features_candle_id_ts"),
        Index("ix_candle_features_exchange_symbol_timeframe_ts", "exchange", "symbol", "timeframe", "timestamp"),
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
    market_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    body_size: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    range_size: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    upper_wick: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    lower_wick: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    close_position_in_range: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)

    pct_return_1: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)
    volume_ratio_vs_prev: Mapped[Decimal | None] = mapped_column(Numeric(24, 12), nullable=True)

    is_bullish: Mapped[bool] = mapped_column(Boolean, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
