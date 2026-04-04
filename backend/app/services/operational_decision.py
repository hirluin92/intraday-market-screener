"""
Decisione operativa (semaforo) per opportunità live: operabile / monitorare / scartare.

Regole allineate a variant backtest, alert MVP, allineamento segnale e qualità TF.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.opportunities import OpportunityRow
from app.services.opportunity_final_score import compute_signal_alignment

OperationalDecision = Literal["operable", "monitor", "discard"]


def _weak_timeframe_history(r: OpportunityRow) -> bool:
    """Storico TF debole: esclude operatività diretta."""
    if not r.latest_pattern_name:
        return False
    if r.pattern_timeframe_filtered_candidate:
        return True
    if r.pattern_timeframe_quality_ok is False:
        return True
    g = (r.pattern_timeframe_gate_label or "").lower().strip()
    if g == "poor":
        return True
    return False


def compute_operational_decision_and_rationale(
    r: OpportunityRow,
) -> tuple[OperationalDecision, list[str]]:
    """
    Restituisce codice decisione + 2–4 righe motivazione (IT) per UI «Perché».
    """
    align = compute_signal_alignment(r.score_direction, r.latest_pattern_direction)
    has_pattern = bool(r.latest_pattern_name and str(r.latest_pattern_name).strip())
    src = r.trade_plan_source or "default_fallback"
    st = r.selected_trade_plan_variant_status

    # --- Scartare: conflitto o storico TF debole ---
    if align == "conflicting":
        return "discard", [
            "Allineamento conflittuale tra direzione score e pattern.",
            "Il segnale non è coerente per un’azione direzionale unica.",
        ]

    if _weak_timeframe_history(r):
        return "discard", [
            "Storico pattern/timeframe debole o non adeguato su questo TF.",
            "Evitare operatività aggressiva fino a miglioramento qualità storica.",
        ]

    # --- Operabile: promossa + alert + allineato + TF OK ---
    if (
        src == "variant_backtest"
        and st == "promoted"
        and r.alert_candidate
        and align == "aligned"
        and has_pattern
        and r.pattern_timeframe_quality_ok is True
    ):
        lines = [
            "Pattern allineato con il bias dello score.",
            "Storico sul timeframe considerato OK.",
            "Variante promossa dal backtest varianti (livelli applicati).",
        ]
        if r.alert_candidate:
            lines.append("Supera le regole MVP per candidato alert.")
        return "operable", lines[:4]

    # --- Watchlist + alert → da monitorare ---
    if st == "watchlist" and r.alert_candidate:
        return "monitor", [
            "Variante in watchlist (affidabilità media rispetto a «promossa»).",
            "Candidato alert: monitorare evoluzione e conferme.",
        ]

    # --- Promossa ma condizioni non tutte per «operabile» ---
    if src == "variant_backtest" and st == "promoted":
        return "monitor", [
            "Variante promossa in backtest ma alert o allineamento/TF non completi.",
            "Preferire conferme aggiuntive rispetto a un setup pienamente operabile.",
        ]

    # --- Watchlist senza alert ---
    if st == "watchlist":
        return "monitor", [
            "Variante watchlist: campione o metriche sotto la soglia «promossa».",
            "Nessun alert MVP: solo osservazione.",
        ]

    # --- Fallback standard ---
    if src == "default_fallback":
        if r.alert_candidate:
            return "monitor", [
                "Piano da motore base: nessuna variante validata per le regole live.",
                "Alert presente ma senza supporto variant backtest sui livelli.",
            ]
        return "discard", [
            "Nessuna variante affidabile applicata; solo fallback del motore base.",
            "Segnale non sufficiente per alert o condizioni prudenziali non rispettate.",
        ]

    # --- Allineamento misto ---
    if align == "mixed":
        return "monitor", [
            "Allineamento score/pattern non netto (misto o neutro).",
            "Richiede contesto aggiuntivo prima di operare.",
        ]

    return "monitor", [
        "Condizioni intermedie: valutare contesto e rischio prima dell’ingresso.",
    ]


def map_decision_filter_param(raw: str | None) -> OperationalDecision | None:
    """Query API: operable | monitor | discard o alias IT."""
    if not raw or not raw.strip():
        return None
    s = raw.strip().lower()
    aliases: dict[str, OperationalDecision] = {
        "operabile": "operable",
        "operabili": "operable",
        "operable": "operable",
        "monitor": "monitor",
        "da_monitorare": "monitor",
        "monitorare": "monitor",
        "discard": "discard",
        "scartare": "discard",
        "scarta": "discard",
    }
    return aliases.get(s)
