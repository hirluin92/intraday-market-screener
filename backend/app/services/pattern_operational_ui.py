"""
Stato operativo pattern per UI (allineato a opportunity_validator: set per TF).
"""

from __future__ import annotations

from typing import Literal

from app.core.trade_plan_variant_constants import VALIDATED_PATTERNS_1H, VALIDATED_PATTERNS_5M


def pattern_is_validated_for_ui(pattern_name: str | None, timeframe: str) -> bool:
    """
    True se il nome pattern è nella lista validata **per quel timeframe**
    (stesso criterio di ``opportunity_validator.validate_opportunity``).
    """
    if not pattern_name or not str(pattern_name).strip():
        return False
    pn = str(pattern_name).strip()
    tf = timeframe.strip()
    if tf == "1h":
        return pn in VALIDATED_PATTERNS_1H
    if tf == "5m":
        return pn in VALIDATED_PATTERNS_5M
    return False


def pattern_operational_status_for_ui(
    pattern_name: str | None,
    timeframe: str,
    pattern_quality_label: str,
) -> Literal["operational", "development", "experimental"]:
    if pattern_is_validated_for_ui(pattern_name, timeframe):
        return "operational"
    if not pattern_name or not str(pattern_name).strip():
        return "development"
    if pattern_quality_label in ("insufficient", "unknown"):
        return "experimental"
    return "development"
