"""
MVP pattern quality score (0–100) derived from backtest aggregates — not persisted.

Heuristic (tunable):
- Prefer horizon **5**; fall back to **3** when 5 is missing.
- **Win rate** (direction-aware, already in aggregate): up to 45 points.
- **Avg return %** at that horizon, clamped to [-1, +2] then normalized: up to 35 points.
- **Sample depth** (max of n_3 / n_5): up to 20 points (saturates at 80 samples).
"""

from __future__ import annotations

import math
from statistics import NormalDist

try:
    from scipy import stats as scipy_stats
except ImportError:
    scipy_stats = None  # type: ignore[assignment]

from app.core.trade_plan_variant_constants import (
    PATTERN_QUALITY_MIN_SAMPLE,
    PATTERN_QUALITY_SAMPLE_EXCELLENT,
    PATTERN_QUALITY_SAMPLE_FAIR,
    PATTERN_QUALITY_SAMPLE_GOOD,
)

HORIZON_FOR_CI = (5, 3)


def wilson_confidence_interval(
    wins: int,
    n: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """
    Wilson score interval per proporzioni binomiali.
    Più accurato dell'intervallo normale per campioni piccoli.

    Ritorna (lower, upper) come percentuali 0-100.
    """
    if n == 0:
        return (0.0, 100.0)

    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p = wins / n

    center = (p + z**2 / (2 * n)) / (1 + z**2 / n)
    margin = (
        z
        * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
        / (1 + z**2 / n)
    )

    lower = max(0.0, (center - margin) * 100)
    upper = min(100.0, (center + margin) * 100)
    return (round(lower, 1), round(upper, 1))


def _norm_cdf(x: float) -> float:
    return NormalDist().cdf(x)


def _binom_pvalue_greater_half(wins: int, n: int) -> float:
    """P(X >= wins) con X ~ Bin(n, 0.5); one-sided vs 50%. Fallback senza scipy."""
    if n <= 0:
        return 1.0
    w = max(0, min(wins, n))
    s = 0.0
    for k in range(w, n + 1):
        s += math.comb(n, k) * (0.5**n)
    return min(1.0, max(0.0, s))


def binomial_test_vs_50pct(wins: int, n: int) -> float:
    """
    Test binomiale: p-value per H0 = win_rate <= 50%.
    H1 = win_rate > 50% (test one-sided).

    p-value < 0.05 → significativo al 95%
    p-value < 0.01 → significativo al 99%

    Ritorna p-value (0.0 - 1.0).
    """
    if n == 0:
        return 1.0
    if scipy_stats is not None:
        result = scipy_stats.binomtest(wins, n, p=0.5, alternative="greater")
        return round(float(result.pvalue), 4)
    return round(_binom_pvalue_greater_half(wins, n), 4)


def ttest_expectancy_vs_zero(pnl_r_values: list[float]) -> tuple[float, float]:
    """
    T-test one-sample: H0 = expectancy_r == 0, H1 = expectancy_r > 0.

    Ritorna (t_statistic, p_value).
    p-value < 0.05 → l'edge è statisticamente significativo al 95%.
    """
    n = len(pnl_r_values)
    if n < 2:
        return (0.0, 1.0)

    mean = sum(pnl_r_values) / n
    variance = sum((x - mean) ** 2 for x in pnl_r_values) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0:
        return (0.0, 1.0)

    t_stat = mean / (std / math.sqrt(n))
    if scipy_stats is not None:
        if n >= 30:
            p_value = 1 - scipy_stats.norm.cdf(t_stat)
        else:
            p_value = 1 - scipy_stats.t.cdf(t_stat, df=n - 1)
    else:
        p_value = 1 - _norm_cdf(t_stat)

    return (round(float(t_stat), 3), round(float(p_value), 4))


def significance_label(p_value: float) -> str:
    """Etichetta leggibile del livello di significatività."""
    if p_value < 0.01:
        return "***"
    elif p_value < 0.05:
        return "**"
    elif p_value < 0.10:
        return "*"
    else:
        return "ns"


def pattern_primary_horizon_wins_rets(
    hdata: dict[int, dict[str, list]],
) -> tuple[int, int, list[float]]:
    """
    Orizzonte 5 poi 3 (come CI Wilson): primi con almeno un campione.
    Ritorna (wins, n, lista return % firmati) per test binomiale e t-test.
    """
    for h in HORIZON_FOR_CI:
        if h not in hdata:
            continue
        rets = hdata[h]["rets"]
        n_h = len(rets)
        if n_h == 0:
            continue
        wins = sum(1 for w in hdata[h]["wins"] if w)
        return wins, n_h, list(rets)
    return 0, 0, []


def sample_reliability_label(n: int) -> str:
    """Etichetta affidabilità campione basata su sample size."""
    if n < PATTERN_QUALITY_MIN_SAMPLE:
        return "insufficient"
    if n < PATTERN_QUALITY_SAMPLE_FAIR:
        return "poor"
    if n < PATTERN_QUALITY_SAMPLE_GOOD:
        return "fair"
    if n < PATTERN_QUALITY_SAMPLE_EXCELLENT:
        return "good"
    return "excellent"


def pattern_forward_win_rate_wilson_ci(
    *,
    hdata: dict[int, dict[str, list]],
    n3: int,
    n5: int,
) -> tuple[float | None, float | None, str]:
    """
    CI 95% Wilson sul win rate all'orizzonte primario (5 poi 3), coerente con lo score.
    Se ``max(n3,n5) < PATTERN_QUALITY_MIN_SAMPLE``: CI ``None``, affidabilità ``insufficient``.
    """
    n_eff = max(n3, n5, 0)
    rel = sample_reliability_label(n_eff)
    if n_eff < PATTERN_QUALITY_MIN_SAMPLE:
        return None, None, rel

    for h in HORIZON_FOR_CI:
        n_h = len(hdata[h]["wins"]) if h in hdata else 0
        if n_h < PATTERN_QUALITY_MIN_SAMPLE:
            continue
        wins = sum(1 for w in hdata[h]["wins"] if w)
        lo, hi = wilson_confidence_interval(wins, n_h)
        return lo, hi, rel

    return None, None, rel


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

    # Campione troppo piccolo → score non affidabile, restituire None.
    # Sotto PATTERN_QUALITY_MIN_SAMPLE i numeri sono rumore statistico.
    # pattern_timeframe_policy gestisce None con penalità PENALTY_UNKNOWN (-6 pt).
    if n_eff < PATTERN_QUALITY_MIN_SAMPLE:
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
        return "insufficient"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    return "low"
