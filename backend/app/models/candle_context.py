from datetime import datetime

from sqlalchemy import DateTime, Index, PrimaryKeyConstraint, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CandleContext(Base):
    """Market context classification for one candle feature row (MVP heuristics)."""

    __tablename__ = "candle_contexts"
    __table_args__ = (
        PrimaryKeyConstraint("id", "timestamp", name="pk_candle_contexts"),
        # FK non dichiarate: TimescaleDB non supporta FK tra hypertables.
        UniqueConstraint("candle_feature_id", "timestamp", name="uq_candle_contexts_feature_id_ts"),
        Index("ix_candle_contexts_exchange_symbol_timeframe_ts", "exchange", "symbol", "timeframe", "timestamp"),
        Index("ix_candle_contexts_provider_ts_id", "provider", "timestamp", "id", postgresql_ops={"timestamp": "DESC", "id": "DESC"}),
        Index("ix_candle_contexts_ts_id", "timestamp", "id", postgresql_ops={"timestamp": "DESC", "id": "DESC"}),
    )

    id: Mapped[int] = mapped_column(autoincrement=True)
    candle_feature_id: Mapped[int] = mapped_column(nullable=False)
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

    market_regime: Mapped[str] = mapped_column(String(16), nullable=False)
    volatility_regime: Mapped[str] = mapped_column(String(16), nullable=False)
    candle_expansion: Mapped[str] = mapped_column(String(16), nullable=False)
    direction_bias: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
