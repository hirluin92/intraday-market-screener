"""
Alert candidates v1: regole derivate leggibili sulle opportunità (MVP, senza notifiche esterne).

Modifica le costanti sotto per tarare la sensibilità.
"""

from __future__ import annotations

from typing import Literal

from app.core.trade_plan_variant_constants import (
    ALERT_HIGH_FINAL_SCORE,
    ALERT_MIN_FINAL_SCORE,
)
from app.services.opportunity_final_score import compute_signal_alignment

AlertLevel = Literal["alta_priorita", "media_priorita", "nessun_alert"]


def compute_alert_candidate_fields(
    *,
    score_direction: str,
    latest_pattern_direction: str | None,
    final_opportunity_score: float,
    pattern_quality_label: str,
    pattern_timeframe_quality_ok: bool | None,
) -> tuple[bool, AlertLevel]:
    """
    Restituisce (alert_candidate, alert_level).

    Regole MVP (tutte richieste per essere candidato):
    - allineamento segnale = aligned (score vs ultimo pattern)
    - OK sul TF = sì (pattern_timeframe_quality_ok è True)
    - banda qualità pattern non bassa: solo high o medium
    - score finale ≥ ALERT_MIN_FINAL_SCORE

    Livello:
    - alta_priorità: candidato e score ≥ ALERT_HIGH_FINAL_SCORE
    - media_priorità: candidato e score < ALERT_HIGH_FINAL_SCORE
    - nessun_alert: altrimenti
    """
    alignment = compute_signal_alignment(score_direction, latest_pattern_direction)
    aligned = alignment == "aligned"
    tf_ok = pattern_timeframe_quality_ok is True
    quality_ok = pattern_quality_label in ("high", "medium")
    score_ok = final_opportunity_score >= ALERT_MIN_FINAL_SCORE

    base = aligned and tf_ok and quality_ok and score_ok
    if not base:
        return False, "nessun_alert"

    if final_opportunity_score >= ALERT_HIGH_FINAL_SCORE:
        return True, "alta_priorita"
    return True, "media_priorita"
