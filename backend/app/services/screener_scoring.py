"""
MVP additive screener score (v1).

Replaceable later with ML or rule engine: keep public entrypoint `score_snapshot`
and dimension weights in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SnapshotForScoring:
    """Minimal fields needed for scoring (from ORM or Pydantic)."""

    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    market_regime: str
    volatility_regime: str
    candle_expansion: str
    direction_bias: str


def score_snapshot(snapshot: SnapshotForScoring) -> tuple[int, str]:
    """
    Simple additive score in [0, 12]: each dimension contributes 1–3 points.

    Rationale (MVP, long-bias intraday screener):
    - market_regime: trend > range (directional opportunity).
    - volatility_regime: high > normal > low (room to move; low = chop/sleep).
    - candle_expansion: expansion > normal > compression (energy vs squeeze).
    - direction_bias: bullish > neutral > bearish for long-leaning book.

    score_label bands (tunable):
    - strong: 10–12
    - moderate: 7–9
    - mild: 4–6
    - weak: 0–3
    """
    points = 0

    # market_regime
    if snapshot.market_regime == "trend":
        points += 3
    elif snapshot.market_regime == "range":
        points += 1

    # volatility_regime
    if snapshot.volatility_regime == "high":
        points += 3
    elif snapshot.volatility_regime == "normal":
        points += 2
    elif snapshot.volatility_regime == "low":
        points += 1

    # candle_expansion
    if snapshot.candle_expansion == "expansion":
        points += 3
    elif snapshot.candle_expansion == "normal":
        points += 2
    elif snapshot.candle_expansion == "compression":
        points += 1

    # direction_bias
    if snapshot.direction_bias == "bullish":
        points += 3
    elif snapshot.direction_bias == "neutral":
        points += 2
    elif snapshot.direction_bias == "bearish":
        points += 1

    label = _score_label(points)
    return points, label


def _score_label(points: int) -> str:
    if points >= 10:
        return "strong"
    if points >= 7:
        return "moderate"
    if points >= 4:
        return "mild"
    return "weak"
