"""
Validazione timeframe per estrazioni (features / context / patterns) in base a provider e venue.

- Binance (crypto): 1m, 5m, 15m, 1h
- Yahoo Finance (azioni/ETF US): 5m, 15m, 1h, 1d
- Alpaca (azioni/ETF US): 1m, 5m, 15m, 30m, 1h, 1d
- IBKR/LSE (azioni UK): 5m, 15m, 1h, 1d (stessi TF di Yahoo Finance)

Se ``provider`` e ``exchange`` sono assenti, un ``timeframe`` esplicito deve appartenere all'unione
(cosi' le richieste "solo TF" restano possibili). In caso di conflitto esplicito tra ``provider`` e
venue dedotto da ``exchange`` viene sollevato ``ValueError``.
"""

from __future__ import annotations

from typing import Literal

from app.core.timeframes import ALLOWED_TIMEFRAMES_SET as BINANCE_TF
from app.core.yahoo_finance_constants import (
    YAHOO_ALLOWED_TIMEFRAMES_SET as YAHOO_TF,
    YAHOO_VENUE_LABEL,
)

# Alpaca supporta gli stessi TF di Yahoo + 30m
ALPACA_TF: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h", "1d"})
ALPACA_VENUE_LABEL: str = "ALPACA_US"

ALL_EXTRACT_TIMEFRAMES_SET: frozenset[str] = BINANCE_TF | YAHOO_TF | ALPACA_TF

ProviderId = Literal["binance", "yahoo_finance", "alpaca", "ibkr"]

# ibkr azionario USA salva i dati con provider="yahoo_finance" ed exchange="YAHOO_US":
# per la fase di extract è trattato come yahoo_finance.
# ibkr azionario UK salva con provider="ibkr" ed exchange="LSE": nessun alias.
_IBKR_US_EXTRACT_ALIAS = "yahoo_finance"

# Label exchange LSE
LSE_VENUE_LABEL: str = "LSE"

# Timeframe supportati da UK/LSE (identici a Yahoo Finance)
LSE_TF: frozenset[str] = frozenset({"5m", "15m", "1h", "1d"})


def infer_provider_from_exchange(exchange: str) -> ProviderId | None:
    """Mappa venue noti -> id provider."""
    ex = exchange.strip()
    if not ex:
        return None
    if ex.upper() == YAHOO_VENUE_LABEL.upper():
        return "yahoo_finance"
    if ex.upper() == ALPACA_VENUE_LABEL.upper():
        return "alpaca"
    if ex.lower() == "binance":
        return "binance"
    if ex.upper() == LSE_VENUE_LABEL.upper():
        return "ibkr"
    return None


def validate_extract_timeframe_for_scope(
    timeframe: str | None,
    provider: ProviderId | None,
    exchange: str | None,
) -> None:
    if timeframe is None:
        return

    # ibkr azionario USA salva su YAHOO_US → alias yahoo_finance per validazione TF.
    # ibkr azionario UK salva su LSE → trattato separatamente (TF = LSE_TF ≡ YAHOO_TF).
    _is_ibkr_lse = provider == "ibkr" and (exchange or "").upper() == LSE_VENUE_LABEL
    effective_provider = provider if _is_ibkr_lse else (_IBKR_US_EXTRACT_ALIAS if provider == "ibkr" else provider)

    inferred_from_ex = infer_provider_from_exchange(exchange) if exchange else None
    if (
        effective_provider is not None
        and inferred_from_ex is not None
        and effective_provider != inferred_from_ex
    ):
        raise ValueError(
            f"provider {provider!r} is inconsistent with exchange {exchange!r} "
            f"(implies {inferred_from_ex!r})",
        )

    effective: ProviderId | None = effective_provider or inferred_from_ex
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
    if effective == "alpaca":
        if timeframe not in ALPACA_TF:
            raise ValueError(
                f"timeframe must be one of {sorted(ALPACA_TF)} for Alpaca, got {timeframe!r}",
            )
        return
    if effective == "ibkr":
        if timeframe not in LSE_TF:
            raise ValueError(
                f"timeframe must be one of {sorted(LSE_TF)} for IBKR/LSE, got {timeframe!r}",
            )
        return

    if timeframe not in ALL_EXTRACT_TIMEFRAMES_SET:
        raise ValueError(
            f"timeframe must be one of {sorted(ALL_EXTRACT_TIMEFRAMES_SET)} "
            f"when provider/exchange are omitted, got {timeframe!r}",
        )
