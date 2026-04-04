"""Dedupe store for outbound alert notifications (MVP)."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AlertNotificationSent(Base):
    """
    One row per (series, context bar) after a high-priority alert was successfully sent.
    Prevents re-sending the same alert on every pipeline cycle until context_timestamp changes.
    """

    __tablename__ = "alert_notification_sent"
    __table_args__ = (
        UniqueConstraint(
            "exchange",
            "symbol",
            "timeframe",
            "context_timestamp",
            name="uq_alert_notification_sent_series_context",
        ),
        Index(
            "ix_alert_notification_sent_exchange_symbol_tf",
            "exchange",
            "symbol",
            "timeframe",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    context_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
