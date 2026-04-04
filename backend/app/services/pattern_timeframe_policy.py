"""
Pattern–timeframe quality gate (MVP, no DB).

Uses the same backtest-derived ``pattern_quality_score`` already attached to opportunities
(aggregate for ``(pattern_name, timeframe)``). Adjusts ``final_opportunity_score`` when historical
evidence on *this* timeframe is weak, and exposes transparent flags for UI.

Tune thresholds only here. No ML.
"""

from __future__ import annotations

# Minimum backtest quality (0–100) to treat this pattern+TF as historically acceptable.
_TF_OK_MIN = 45.0

# Down to this level we still emit a "marginal" band (penalize but not "filtered").
_TF_MARGINAL_MIN = 34.0

# Penalties applied to ``final_opportunity_score`` after the base formula (subtractive).
_PENALTY_MARGINAL = 9.0
_PENALTY_POOR = 20.0
# No aggregate / insufficient backtest signal for this pattern+TF key.
_PENALTY_UNKNOWN = 6.0

# Gate labels stored on API rows (frontend maps to Italian).
GATE_NA = "na"
GATE_OK = "ok"
GATE_MARGINAL = "marginal"
GATE_POOR = "poor"
GATE_UNKNOWN = "unknown"


def apply_pattern_timeframe_policy(
    *,
    has_pattern: bool,
    pattern_quality_score: float | None,
    _pattern_quality_label: str,
    base_final_opportunity_score: float,
) -> tuple[float, bool | None, str, bool]:
    """
    Returns:
      (adjusted_final_score, pattern_timeframe_quality_ok, gate_label, filtered_candidate)

    - ``pattern_timeframe_quality_ok``: None if no pattern; True if quality ≥ OK threshold;
      False if marginal/poor/unknown.
    - ``gate_label``: ``na`` | ``ok`` | ``marginal`` | ``poor`` | ``unknown``.
    - ``filtered_candidate``: True when evidence is clearly poor on this TF (``poor`` gate);
      ranking is heavily penalized — transparent "downgrade" without hiding the row.
    """
    if not has_pattern:
        return round(max(0.0, base_final_opportunity_score), 2), None, GATE_NA, False

    # No numeric score: no matching aggregate or insufficient signal from backtest.
    if pattern_quality_score is None:
        adj = max(0.0, base_final_opportunity_score - _PENALTY_UNKNOWN)
        return round(adj, 2), False, GATE_UNKNOWN, False

    pq = max(0.0, min(100.0, float(pattern_quality_score)))

    if pq >= _TF_OK_MIN:
        return round(max(0.0, base_final_opportunity_score), 2), True, GATE_OK, False

    if pq >= _TF_MARGINAL_MIN:
        adj = max(0.0, base_final_opportunity_score - _PENALTY_MARGINAL)
        return round(adj, 2), False, GATE_MARGINAL, False

    adj = max(0.0, base_final_opportunity_score - _PENALTY_POOR)
    return round(adj, 2), False, GATE_POOR, True
