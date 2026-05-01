"""Registro persistente delle trade eseguite automaticamente dal sistema.

Nota migrazione: se il DB contiene già la tabella executed_signals con colonne Float,
eseguire dopo il deploy:
    alembic revision --autogenerate -m "executed_signals_prices_to_numeric"
    alembic upgrade head
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# Valori ammessi per close_outcome e close_cause
_CLOSE_OUTCOME_VALUES = ("stop", "tp1", "tp2", "timeout")
_CLOSE_CAUSE_VALUES = ("normal", "overnight_gap")


class ExecutedSignal(Base):
    """
    Una riga per ogni bracket order piazzato dall'auto-execute service via TWS.
    Permette di tracciare la storia completa delle trade eseguite dal sistema.

    I prezzi usano Numeric(24, 8) — coerente con CandlePattern/CandleFeature —
    per evitare arrotondamenti IEEE 754 nel registro storico delle trade.
    """

    __tablename__ = "executed_signals"
    __table_args__ = (
        Index("idx_executed_signals_executed_at", "executed_at"),
        Index("idx_executed_signals_symbol_tf", "symbol", "timeframe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # bullish / bearish

    pattern_name: Mapped[str] = mapped_column(String(64), nullable=False)
    pattern_strength: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opportunity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    entry_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    stop_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    take_profit_1: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 8), nullable=True)
    take_profit_2: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 8), nullable=True)

    quantity_tp1: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity_tp2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    entry_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tp_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sl_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tp2_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sl2_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    tws_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PendingSubmit")
    error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    # ── Chiusura del trade (popolata da poll_and_record_stop_fills) ────────
    # Valori close_outcome: "stop" | "tp1" | "tp2" | "timeout"
    # Valori close_cause:   "normal" | "overnight_gap"
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    close_fill_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(24, 8), nullable=True
    )
    realized_r: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_outcome: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    close_cause: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # ── Fill tracking (popolate da _handle_partial_fill_after_bracket) ────
    partial_fill: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    filled_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 8), nullable=True)
    ordered_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 8), nullable=True)

    # ── Snapshot contesto all'entrata (autopsia post-trade) ───────────────
    # JSON serializzato al momento dell'esecuzione per consentire analisi
    # retrospettiva: perché il trade ha preso lo SL invece del TP?

    # Contesto operativo: regime, score, confluence, ML, rationale, SPY, spread
    entry_context_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Indicatori tecnici alla barra di entrata: RSI, EMA, ATR, volume, VWAP,
    # swing levels, FVG, Order Block, CVD, funding rate, RS vs SPY
    entry_indicators_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
