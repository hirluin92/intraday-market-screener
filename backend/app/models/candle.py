from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "exchange",
            "symbol",
            "timeframe",
            "timestamp",
            name="uq_candles_provider_exchange_symbol_timeframe_timestamp",
        ),
        Index("ix_candles_exchange_symbol_timeframe", "exchange", "symbol", "timeframe"),
        Index("ix_candles_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
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
    exchange: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Venue / connector exchange id (e.g. binance for ccxt crypto spot).",
    )
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    market_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
