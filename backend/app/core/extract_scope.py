"""
Validazione timeframe per estrazioni (features / context / patterns) in base a provider e venue.

- Binance (crypto): 1m, 5m, 15m, 1h
- Yahoo Finance (azioni/ETF US): 5m, 15m, 1h, 1d

Se ``provider`` e ``exchange`` sono assenti, un ``timeframe`` esplicito deve appartenere all'unione
(così le richieste “solo TF” restano possibili). In caso di conflitto esplicito tra ``provider`` e
venue dedotto da ``exchange`` viene sollevato ``ValueError``.
"""

from __future__ import annotations

from typing import Literal

from app.core.timeframes import ALLOWED_TIMEFRAMES_SET as BINANCE_TF
from app.core.yahoo_finance_constants import (
    YAHOO_ALLOWED_TIMEFRAMES_SET as YAHOO_TF,
    YAHOO_VENUE_LABEL,
)

ALL_EXTRACT_TIMEFRAMES_SET: frozenset[str] = BINANCE_TF | YAHOO_TF

ProviderId = Literal["binance", "yahoo_finance"]


def infer_provider_from_exchange(exchange: str) -> ProviderId | None:
    """Mappa venue noti → id provider (estendere per LSE, ecc.)."""
    ex = exchange.strip()
    if not ex:
        return None
    if ex.upper() == YAHOO_VENUE_LABEL.upper():
        return "yahoo_finance"
    if ex.lower() == "binance":
        return "binance"
    return None


def validate_extract_timeframe_for_scope(
    timeframe: str | None,
    provider: ProviderId | None,
    exchange: str | None,
) -> None:
    if timeframe is None:
        return

    inferred_from_ex = infer_provider_from_exchange(exchange) if exchange else None
    if provider is not None and inferred_from_ex is not None and provider != inferred_from_ex:
        raise ValueError(
            f"provider {provider!r} is inconsistent with exchange {exchange!r} "
            f"(implies {inferred_from_ex!r})",
        )

    effective: ProviderId | None = provider or inferred_from_ex
    if effective == "binance":
        if timeframe not in BINANCE_TF:
            raise ValueError(
                f"timeframe must be one of {sorted(BINANCE_TF)} for Binance, got {timeframe!r}",
            )
        return
    if effective == "yahoo_finance":
        if timeframe not in YAHOO_TF:
            raise ValueError(
                f"timeframe must be one of {sorted(YAHOO_TF)} for Yahoo Finance, got {timeframe!r}",
            )
        return

    if timeframe not in ALL_EXTRACT_TIMEFRAMES_SET:
        raise ValueError(
            f"timeframe must be one of {sorted(ALL_EXTRACT_TIMEFRAMES_SET)} "
            f"when provider/exchange are omitted, got {timeframe!r}",
        )
