from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CandlePattern(Base):
    """Detected intraday pattern label for one candle feature row (MVP heuristics)."""

    __tablename__ = "candle_patterns"
    __table_args__ = (
        UniqueConstraint(
            "candle_feature_id",
            "pattern_name",
            name="uq_candle_patterns_feature_pattern",
        ),
        Index("ix_candle_patterns_exchange_symbol_timeframe_ts", "exchange", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candle_feature_id: Mapped[int] = mapped_column(
        ForeignKey("candle_features.id", ondelete="CASCADE"),
        nullable=False,
    )
    candle_context_id: Mapped[int | None] = mapped_column(
        ForeignKey("candle_contexts.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pattern_name: Mapped[str] = mapped_column(String(64), nullable=False)
    pattern_strength: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
