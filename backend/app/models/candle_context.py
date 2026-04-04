from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CandleContext(Base):
    """Market context classification for one candle feature row (MVP heuristics)."""

    __tablename__ = "candle_contexts"
    __table_args__ = (
        UniqueConstraint("candle_feature_id", name="uq_candle_contexts_candle_feature_id"),
        Index("ix_candle_contexts_exchange_symbol_timeframe_ts", "exchange", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candle_feature_id: Mapped[int] = mapped_column(
        ForeignKey("candle_features.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    market_regime: Mapped[str] = mapped_column(String(16), nullable=False)
    volatility_regime: Mapped[str] = mapped_column(String(16), nullable=False)
    candle_expansion: Mapped[str] = mapped_column(String(16), nullable=False)
    direction_bias: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
