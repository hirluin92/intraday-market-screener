from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CandleFeature(Base):
    """Intraday features derived from a stored candle (one row per candle)."""

    __tablename__ = "candle_features"
    __table_args__ = (
        UniqueConstraint("candle_id", name="uq_candle_features_candle_id"),
        Index("ix_candle_features_exchange_symbol_timeframe_ts", "exchange", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candle_id: Mapped[int] = mapped_column(
        ForeignKey("candles.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
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
