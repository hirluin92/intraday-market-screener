"""
Opportunity ranking v1: derive *base* ``final_opportunity_score`` from ``screener_score`` plus
alignment, pattern quality, and pattern strength.

``list_opportunities`` then applies :mod:`app.services.pattern_timeframe_policy` to adjust the
score using backtest evidence for the specific ``(pattern, timeframe)`` (no extra DB tables).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

# --- Scale: anchor screener_score (0..12) to a wider range so bonuses fit comfortably ---
_SCREENER_WEIGHT = 5.0  # max 60 points from headline score

# --- Signal alignment (score_direction vs latest_pattern_direction, same rules as frontend) ---
# Reward agreement on directional legs; penalize bullish vs bearish clash; neutral/missing → mixed.
_ALIGNMENT_ALIGNED = 10.0
_ALIGNMENT_MIXED = 0.0
_ALIGNMENT_CONFLICTING = -12.0

# --- Pattern quality: prefer numeric 0..100 backtest score; else fall back to quality band ---
_QUALITY_FROM_SCORE_MAX = 20.0  # multiply (pq/100) * this
_QUALITY_BAND_BONUS = {
    "high": 14.0,
    "medium": 7.0,
    "low": 3.0,
    "unknown": 0.0,
    "insufficient": 0.0,
}

# --- Pattern strength: stored ~0..1 in MVP engine ---
_STRENGTH_MAX_BONUS = 4.0  # strength 1.0 → +4

SignalAlignment = Literal["aligned", "mixed", "conflicting"]


def compute_signal_alignment(
    score_direction: str,
    pattern_direction: str | None,
) -> SignalAlignment:
    """Match frontend ``computeSignalAlignment``: aligned / mixed / conflicting."""
    sd = (score_direction or "").lower().strip()
    pd = (pattern_direction or "").strip().lower() if pattern_direction else ""
    if not sd or not pd:
        return "mixed"
    if sd == "neutral" or pd == "neutral":
        return "mixed"
    if sd == pd:
        return "aligned"
    return "conflicting"


def _alignment_bonus(alignment: SignalAlignment) -> float:
    if alignment == "aligned":
        return _ALIGNMENT_ALIGNED
    if alignment == "conflicting":
        return _ALIGNMENT_CONFLICTING
    return _ALIGNMENT_MIXED


def _quality_bonus(
    pattern_quality_score: float | None,
    pattern_quality_label: str,
) -> float:
    if pattern_quality_score is not None:
        return (max(0.0, min(100.0, pattern_quality_score)) / 100.0) * _QUALITY_FROM_SCORE_MAX
    return float(_QUALITY_BAND_BONUS.get(pattern_quality_label, 0.0))


def _strength_bonus(latest_pattern_strength: Decimal | None) -> float:
    if latest_pattern_strength is None:
        return 0.0
    s = float(latest_pattern_strength)
    s = max(0.0, min(1.0, s))
    return s * _STRENGTH_MAX_BONUS


def compute_final_opportunity_score(
    *,
    screener_score: int,
    score_direction: str,
    latest_pattern_direction: str | None,
    pattern_quality_score: float | None,
    pattern_quality_label: str,
    latest_pattern_strength: Decimal | None,
) -> float:
    """
    Single scalar for sorting: higher = better opportunity.

    Formula (v1):
      base = screener_score * SCREENER_WEIGHT
      + alignment_bonus(aligned/mixed/conflicting)
      + quality_bonus(pq score or band)
      + strength_bonus(pattern_strength in 0..1)
    Floored at 0, rounded to 2 decimals.
    """
    alignment = compute_signal_alignment(score_direction, latest_pattern_direction)
    base = float(screener_score) * _SCREENER_WEIGHT
    total = (
        base
        + _alignment_bonus(alignment)
        + _quality_bonus(pattern_quality_score, pattern_quality_label)
        + _strength_bonus(latest_pattern_strength)
    )
    return round(max(0.0, total), 2)


def final_opportunity_label_from_score(score: float) -> str:
    """API-facing band for UI mapping (Italian on frontend)."""
    if score >= 70.0:
        return "strong"
    if score >= 45.0:
        return "moderate"
    if score >= 20.0:
        return "weak"
    return "minimal"
