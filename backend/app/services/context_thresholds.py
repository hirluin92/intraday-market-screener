"""
Timeframe-aware thresholds for the MVP context engine (`context_extraction`).

All magic numbers live here so they stay easy to tune without hunting through logic.
Shorter bars are noisier: trend and direction thresholds are slightly looser on 1m;
1h bars are smoother: trend can be declared with smaller mean absolute % moves.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextHeuristicThresholds:
    """Single timeframe profile for regime / expansion / direction heuristics."""

    # --- Volatility vs median range in window (current bar range / median range) ---
    vol_low_ratio: float
    vol_high_ratio: float

    # --- Expansion vs mean range in window ---
    exp_low_ratio: float
    exp_high_ratio: float

    # --- Trend vs range: mean absolute pct_return_1 over window (percent points) ---
    # e.g. 0.05 ≈ 0.05% avg |move| per bar; above `trend_abs_pct_high` => trend.
    trend_abs_pct_high: float
    trend_abs_pct_med: float
    # When mean_abs_pct is between med and high, require volume participation above this.
    trend_volume_ratio: float

    # --- Direction on current bar (close in range, pct_return_1) ---
    dir_cp_bull: float  # close_position >= this => bullish bias (with bullish candle)
    dir_cp_bear: float  # close_position <= this => bearish bias (with bearish candle)
    dir_pr: float  # |pct_return_1| above this pushes bias from return sign


# Default fallback if DB has an unexpected timeframe string.
DEFAULT_TIMEFRAME_KEY = "5m"

CONTEXT_THRESHOLDS: dict[str, ContextHeuristicThresholds] = {
    "1m": ContextHeuristicThresholds(
        vol_low_ratio=0.70,
        vol_high_ratio=1.30,
        exp_low_ratio=0.75,
        exp_high_ratio=1.25,
        trend_abs_pct_high=0.08,
        trend_abs_pct_med=0.05,
        trend_volume_ratio=1.25,
        dir_cp_bull=0.55,
        dir_cp_bear=0.45,
        dir_pr=0.03,
    ),
    "5m": ContextHeuristicThresholds(
        vol_low_ratio=0.70,
        vol_high_ratio=1.30,
        exp_low_ratio=0.75,
        exp_high_ratio=1.25,
        trend_abs_pct_high=0.05,
        trend_abs_pct_med=0.03,
        trend_volume_ratio=1.20,
        dir_cp_bull=0.55,
        dir_cp_bear=0.45,
        dir_pr=0.02,
    ),
    "15m": ContextHeuristicThresholds(
        vol_low_ratio=0.70,
        vol_high_ratio=1.30,
        exp_low_ratio=0.75,
        exp_high_ratio=1.25,
        trend_abs_pct_high=0.04,
        trend_abs_pct_med=0.025,
        trend_volume_ratio=1.18,
        dir_cp_bull=0.55,
        dir_cp_bear=0.45,
        dir_pr=0.015,
    ),
    "1h": ContextHeuristicThresholds(
        vol_low_ratio=0.70,
        vol_high_ratio=1.30,
        exp_low_ratio=0.75,
        exp_high_ratio=1.25,
        trend_abs_pct_high=0.03,
        trend_abs_pct_med=0.02,
        trend_volume_ratio=1.15,
        dir_cp_bull=0.55,
        dir_cp_bear=0.45,
        dir_pr=0.01,
    ),
    # Yahoo Finance daily bars: smoother moves; thresholds closer to 1h than intraday.
    "1d": ContextHeuristicThresholds(
        vol_low_ratio=0.70,
        vol_high_ratio=1.30,
        exp_low_ratio=0.75,
        exp_high_ratio=1.25,
        trend_abs_pct_high=0.025,
        trend_abs_pct_med=0.015,
        trend_volume_ratio=1.12,
        dir_cp_bull=0.55,
        dir_cp_bear=0.45,
        dir_pr=0.008,
    ),
}


def thresholds_for_timeframe(timeframe: str) -> ContextHeuristicThresholds:
    """Resolve thresholds for a series timeframe; unknown values fall back to 5m."""
    return CONTEXT_THRESHOLDS.get(timeframe, CONTEXT_THRESHOLDS[DEFAULT_TIMEFRAME_KEY])
