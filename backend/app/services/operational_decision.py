"""
Decisione operativa (semaforo) per opportunità live: operabile / monitorare / scartare.

Regole allineate a variant backtest, alert MVP, allineamento segnale e qualità TF.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.opportunities import OpportunityRow
from app.services.opportunity_final_score import compute_signal_alignment

OperationalDecision = Literal["operable", "monitor", "discard"]


def _fallback_is_missing_data(r: OpportunityRow) -> bool:
    """
    True se il fallback è dovuto a dati assenti (nessun bucket), non a variante respinta.

    - no_pattern / no_variant_bucket → storico non disponibile → di solito monitor, non discard
    - variant_rejected / watchlist_insufficient_sample → dati presenti ma insufficienti → discard
    """
    fbr = (r.trade_plan_fallback_reason or "").strip()
    return fbr in ("no_pattern", "no_variant_bucket", "")


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

    # --- Operabile: promossa + alert + allineato + TF OK (+ pattern non datato) ---
    operable_core = (
        src == "variant_backtest"
        and st == "promoted"
        and r.alert_candidate
        and align == "aligned"
        and has_pattern
        and r.pattern_timeframe_quality_ok is True
    )
    if operable_core and r.pattern_stale:
        age = r.pattern_age_bars
        age_txt = f"{age} barre sul TF {r.timeframe}" if age is not None else f"sul TF {r.timeframe}"
        return "monitor", [
            "Setup promossa + alert + allineamento OK, ma l’ultimo pattern è datato rispetto al contesto.",
            f"Ritardo stimato: {age_txt} (oltre soglia staleness).",
            "Degradato a «da monitorare»: attendere pattern più recente o conferme aggiuntive.",
        ]
    if operable_core:
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
        if _fallback_is_missing_data(r):
            return "monitor", [
                "Nessun dato storico sufficiente per questo bucket (varianti non calcolate o assenti).",
                "Assenza di dati non equivale a segnale negativo: valutare contesto manualmente.",
                "Preferire conferme prima di operare senza livelli da variant backtest.",
            ]
        return "discard", [
            "Variante backtest respinta o campione insufficiente per uso live.",
            "Segnale non supportato da storico affidabile sul bucket: evitare operatività aggressiva.",
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
