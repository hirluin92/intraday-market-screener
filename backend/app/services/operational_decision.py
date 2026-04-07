"""
Parametri query API per filtrare opportunità per decisione operativa (execute | monitor | discard).

La logica che imposta ``operational_decision`` sulle righe è in ``opportunity_validator.validate_opportunity``.
"""

from __future__ import annotations

from typing import Literal

OperationalDecision = Literal["execute", "monitor", "discard"]


def map_decision_filter_param(raw: str | None) -> OperationalDecision | None:
    """Query API: execute | monitor | discard o alias IT (operable/operabile → execute)."""
    if not raw or not raw.strip():
        return None
    s = raw.strip().lower()
    aliases: dict[str, OperationalDecision] = {
        "execute": "execute",
        "operabile": "execute",
        "operabili": "execute",
        "operable": "execute",
        "monitor": "monitor",
        "da_monitorare": "monitor",
        "monitorare": "monitor",
        "discard": "discard",
        "scartare": "discard",
        "scarta": "discard",
    }
    return aliases.get(s)
