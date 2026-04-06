"""
Valida le opportunità con pattern/simboli/TF confermati da simulazione + regime SPY 1d (Yahoo).
Sovrascrive solo operational_decision e decision_rationale lato list_opportunities.
"""

from __future__ import annotations

from datetime import datetime

from app.core.hour_filters import EXCLUDED_HOURS_UTC_YAHOO, hour_utc
from app.core.trade_plan_variant_constants import (
    VALIDATED_PATTERNS_1H,
    VALIDATED_PATTERNS_5M,
    VALIDATED_SYMBOLS_BINANCE,
    VALIDATED_SYMBOLS_YAHOO,
    VALIDATED_TIMEFRAMES,
)
from app.services.regime_filter_service import RegimeFilter


def validate_opportunity(
    *,
    symbol: str,
    timeframe: str,
    provider: str,
    pattern_name: str | None,
    direction: str | None,
    regime_filter: RegimeFilter | None,
    timestamp: datetime,
) -> tuple[str, list[str]]:
    """
    Ritorna (operational_decision, decision_rationale).

    execute = setup allineato a vincoli validati (pattern/universo/TF; regime SPY solo Yahoo).
    """
    rationale: list[str] = []

    if provider == "yahoo_finance" and hour_utc(timestamp) in EXCLUDED_HOURS_UTC_YAHOO:
        return "discard", [
            f"Ora {hour_utc(timestamp)}:00 UTC non operativa "
            "(after hours o bassa liquidità).",
        ]

    if timeframe not in VALIDATED_TIMEFRAMES:
        return "discard", [
            f"Timeframe {timeframe} non operativo — usare 1h o 5m.",
        ]

    if provider == "yahoo_finance":
        if symbol not in VALIDATED_SYMBOLS_YAHOO:
            return "discard", [
                f"{symbol} non nell'universo validato — edge non confermato (es. DIA escluso).",
            ]
    elif provider == "binance":
        if symbol not in VALIDATED_SYMBOLS_BINANCE:
            return "discard", [
                f"{symbol} non nell'universo crypto validato.",
            ]

    if not pattern_name or not str(pattern_name).strip():
        return "discard", [
            "Nessun pattern rilevato sull'ultima barra — niente segnale validato.",
        ]

    pn = str(pattern_name).strip()
    if timeframe == "1h":
        validated_patterns = VALIDATED_PATTERNS_1H
    elif timeframe == "5m":
        validated_patterns = VALIDATED_PATTERNS_5M
    else:
        validated_patterns = frozenset()

    pattern_validated = pn in validated_patterns
    if not pattern_validated:
        return "discard", [
            f"Pattern «{pn}» su {timeframe} non validato dalla simulazione.",
            "Su 1h: compression_to_expansion_transition, rsi_momentum_continuation. "
            "Su 5m: rsi_momentum_continuation.",
        ]

    dir_norm = (direction or "").strip().lower()
    if dir_norm not in ("bullish", "bearish"):
        return "discard", [
            "Direzione pattern assente o non direzionale — non classificabile per regime.",
        ]

    regime_label = "neutral"
    regime_ok = True

    if regime_filter is not None and provider == "yahoo_finance":
        allowed_directions = regime_filter.get_allowed_directions(timestamp)
        regime_label = regime_filter.get_regime_label(timestamp)

        if dir_norm not in allowed_directions:
            regime_ok = False
            rationale.append(
                f"Segnale {dir_norm} contro il regime SPY ({regime_label}) — "
                "probabilità di successo ridotta."
            )

    if pattern_validated and regime_ok:
        rationale.append(
            "Pattern validato da backtest / validazione OOS (universo e TF operativi)."
        )
        if provider == "binance":
            rationale.append(
                "Crypto — regime filter non applicato (usa BTC come riferimento)."
            )
        elif regime_label != "neutral":
            rationale.append(
                f"Regime SPY {regime_label} — direzione {dir_norm} consentita dal filtro."
            )
        rationale.append(
            "Segnale operativo — gestire rischio (es. 1% per trade, max 3 simultanei)."
        )
        return "execute", rationale

    if pattern_validated and not regime_ok:
        rationale.append(
            "Pattern validato ma regime SPY non allineato — ridurre size o attendere conferma."
        )
        return "monitor", rationale

    return "monitor", rationale or [
        "Condizioni intermedie — valutare contesto prima dell'ingresso.",
    ]
