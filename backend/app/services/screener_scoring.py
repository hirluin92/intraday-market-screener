"""
MVP screener score: structural opportunity + mirrored directional legs.

Structural dimensions (market regime, volatility, candle expansion) are direction-agnostic.
Direction is scored twice: a long-leaning leg and a short-leaning leg using mirrored
weights on ``direction_bias``. The reported score is the stronger leg; ``score_label``
combines strength band with ``score_direction`` so a strong bearish screen reads
``strong_bearish``, not merely ``strong``.
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


@dataclass(frozen=True, slots=True)
class ScoringResult:
    """Composite screener output for API rows."""

    screener_score: int
    score_label: str
    score_direction: str  # bullish | bearish | neutral


def _structural_points(snapshot: SnapshotForScoring) -> int:
    """Shared 0–9: regime + volatility + expansion (no direction).

    market_regime scale: trend=3 > range=2 > neutral=1 > choppy/volatile=0.
    «range» era 1 (uguale a «neutral» non esplicito): fix per garantire
    trend > range > neutral > else, scala continua senza salti.
    """
    points = 0
    if snapshot.market_regime == "trend":
        points += 3
    elif snapshot.market_regime == "range":
        points += 2
    elif snapshot.market_regime == "neutral":
        points += 1
    # choppy, volatile, qualsiasi altro valore → 0

    if snapshot.volatility_regime == "high":
        points += 3
    elif snapshot.volatility_regime == "normal":
        points += 2
    elif snapshot.volatility_regime == "low":
        points += 1

    if snapshot.candle_expansion == "expansion":
        points += 3
    elif snapshot.candle_expansion == "normal":
        points += 2
    elif snapshot.candle_expansion == "compression":
        points += 1

    return points


def _direction_bonus_long(direction_bias: str) -> int:
    """Long leg: reward bullish > neutral > bearish."""
    if direction_bias == "bullish":
        return 3
    if direction_bias == "neutral":
        return 2
    return 1


def _direction_bonus_short(direction_bias: str) -> int:
    """Short leg: reward bearish > neutral > bullish."""
    if direction_bias == "bearish":
        return 3
    if direction_bias == "neutral":
        return 2
    return 1


def _band(points: int) -> str:
    if points >= 10:
        return "strong"
    if points >= 7:
        return "moderate"
    if points >= 4:
        return "mild"
    return "weak"


def score_snapshot(snapshot: SnapshotForScoring) -> ScoringResult:
    """
    Two additive scores in [0, 12]: ``score_long`` and ``score_short`` share structural
    points (0–9) and add mirrored direction bonuses (0–3).

    - Dominant leg sets ``screener_score`` and ``score_direction``.
    - Ties map to ``neutral`` (choppy / no clear directional edge at this resolution).
    - ``score_label`` is ``{band}_{direction}``, e.g. ``strong_bearish``, ``mild_neutral``.
    """
    structural = _structural_points(snapshot)
    score_long = structural + _direction_bonus_long(snapshot.direction_bias)
    score_short = structural + _direction_bonus_short(snapshot.direction_bias)

    if score_long > score_short:
        direction = "bullish"
        score = score_long
    elif score_short > score_long:
        direction = "bearish"
        score = score_short
    else:
        direction = "neutral"
        score = score_long

    band = _band(score)
    label = f"{band}_{direction}"
    return ScoringResult(
        screener_score=score,
        score_label=label,
        score_direction=direction,
    )
