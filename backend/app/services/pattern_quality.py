"""
MVP pattern quality score (0–100) derived from backtest aggregates — not persisted.

Heuristic (tunable):
- Prefer horizon **5**; fall back to **3** when 5 is missing.
- **Win rate** (direction-aware, already in aggregate): up to 45 points.
- **Avg return %** at that horizon, clamped to [-1, +2] then normalized: up to 35 points.
- **Sample depth** (max of n_3 / n_5): up to 20 points (saturates at 80 samples).
"""

from __future__ import annotations


def compute_pattern_quality_score(
    *,
    sample_size_3: int,
    sample_size_5: int,
    avg_return_3: float | None,
    avg_return_5: float | None,
    win_rate_3: float | None,
    win_rate_5: float | None,
) -> float | None:
    """
    Return a 0–100 score or ``None`` if there is not enough signal (no win rate / return).
    """
    wr = win_rate_5 if win_rate_5 is not None else win_rate_3
    ar = avg_return_5 if avg_return_5 is not None else avg_return_3
    if wr is None or ar is None:
        return None

    n_eff = max(sample_size_5, sample_size_3, 0)
    if n_eff == 0:
        return None

    # Map typical intraday % moves into 0..1 (wider clamp keeps MVP stable).
    ar_clamped = max(-1.0, min(2.0, ar))
    ar_norm = (ar_clamped + 1.0) / 3.0

    n_norm = min(max(n_eff / 80.0, 0.0), 1.0)

    score = 45.0 * wr + 35.0 * ar_norm + 20.0 * n_norm
    return round(min(100.0, max(0.0, score)), 2)


def pattern_quality_label_from_score(score: float | None) -> str:
    """Readable band for API consumers; ``None`` means insufficient backtest signal."""
    if score is None:
        return "unknown"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    return "low"
