"""Dedupe persistente per alert pattern (Telegram/Discord) da ``alert_service``."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertSent(Base):
    """
    Una riga per chiave (serie × pattern × direzione × barra UTC) dopo un tentativo di invio
    (dedup anche se i canali non sono configurati — allineato al vecchio set in-memory).
    """

    __tablename__ = "alerts_sent"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "timeframe",
            "provider",
            "pattern_name",
            "direction",
            "bar_hour_utc",
            name="uq_alert_sent_dedup",
        ),
        Index("idx_alerts_sent_sent_at", "sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    pattern_name: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)

    bar_hour_utc: Mapped[str] = mapped_column(String(16), nullable=False)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    telegram_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discord_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
