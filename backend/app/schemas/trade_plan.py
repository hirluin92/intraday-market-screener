"""Trade Plan v1 — piano operativo derivato (MVP, rule-based, non persistito)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


TradeDirection = Literal["long", "short", "none"]
EntryStrategy = Literal["breakout", "retest", "close"]


class TradePlanV1(BaseModel):
    """Piano di trade euristico da contesto + pattern + ultima candela."""

    trade_direction: TradeDirection = Field(
        description="long | short | none se setup non operabile o dati insufficienti.",
    )
    entry_strategy: EntryStrategy = Field(
        description="breakout | retest | close (ultima conferma).",
    )
    entry_price: Decimal | None = Field(
        default=None,
        description="Riferimento ingresso (tipicamente ultimo close).",
    )
    stop_loss: Decimal | None = Field(default=None)
    take_profit_1: Decimal | None = Field(default=None)
    take_profit_2: Decimal | None = Field(default=None)
    risk_reward_ratio: Decimal | None = Field(
        default=None,
        description="Rapporto rischio/reward verso TP1 (|move TP1| / |move stop|).",
    )
    invalidation_note: str = Field(
        default="",
        description="Condizioni che invalidano il setup (testo MVP).",
    )
