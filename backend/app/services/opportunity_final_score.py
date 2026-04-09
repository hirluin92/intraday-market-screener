"""
Opportunity ranking v2: ``final_opportunity_score`` da ``screener_score`` + allineamento
segnale + qualità pattern + forza pattern.

``list_opportunities`` applica poi :mod:`app.services.pattern_timeframe_policy` per
l'aggiustamento qualità/penalità su backtest (unica fonte di verità per pq).

Modifiche v2 rispetto a v1:
- ``_QUALITY_FROM_SCORE_MAX`` ridotto 20→14: quality bonus non doveva dominare
  il 32% del range pratico; ridotto a ~25% — spread qualità 30→22 punti.
- ``_QUALITY_BAND_BONUS`` ricalibrato coerentemente.
- ``_ALIGNMENT_CONFLICTING`` -12→-10: simmetria con +10 aligned; il penalty
  di -12 era eccessivo per pattern contrarian (es. engulfing_bullish in bear regime)
  che il validator promuove correttamente a "execute".
- ``_STRENGTH_MAX_BONUS`` 4→8: nel range operativo 0.70–1.0 la differenza era
  solo 1.2 punti (rumore); ora 2.4 punti — più discriminante senza dominare.
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
_ALIGNMENT_CONFLICTING = -10.0  # era -12; ridotto per simmetria e per non penalizzare eccessivamente
                                 # i pattern contrarian (PATTERNS_BEAR_REGIME_ONLY) in bear regime.

# --- Pattern quality: prefer numeric 0..100 backtest score; else fall back to quality band ---
# Ridotto 20→14: quality non deve da sola guidare il 30%+ del range pratico.
# I penali per scarsa qualità sono in pattern_timeframe_policy (unica sorgente TF-specifica).
_QUALITY_FROM_SCORE_MAX = 14.0  # multiply (pq/100) * this; max +14 per pq=100
_QUALITY_BAND_BONUS = {
    "high": 10.0,    # era 14
    "medium": 5.0,   # era 7
    "low": 2.0,      # era 3
    "unknown": 0.0,
    "insufficient": 0.0,
}

# --- Pattern strength: stored ~0..1 in MVP engine ---
# Aumentato 4→8: nel range operativo 0.70–1.0 il vecchio bonus era 1.2 pt (rumore).
# Con 8 la differenza tra strength=0.70 e strength=1.0 è 2.4 pt — più discriminante.
_STRENGTH_MAX_BONUS = 8.0  # strength 1.0 → +8

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

    Formula (v2):
      base = screener_score * SCREENER_WEIGHT          (max 60)
      + alignment_bonus(aligned/mixed/conflicting)     (±10)
      + quality_bonus(pq score or band)                (max +14)
      + strength_bonus(pattern_strength in 0..1)       (max +8)

    Poi ``apply_pattern_timeframe_policy`` applica ulteriori penalità
    per qualità bassa su quel TF specifico (non doppione: le penalità
    riguardano il TF, il quality_bonus qui riguarda la qualità assoluta
    del pattern su tutto lo storico).
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
