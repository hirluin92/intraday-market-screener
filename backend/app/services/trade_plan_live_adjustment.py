"""
Influenza **conservativa** del Trade Plan Backtest v1 sul ranking live.

- Non è un filtro duro: niente esclusioni o soglie che «spengono» opportunità.
- Malus/bonus **piccoli**, moltiplicati per un peso di affidabilità ↑ con `sample_size`.
- Gli **alert** (soglie score) usano lo score **prima** di questo aggiustamento (vedi
  ``list_opportunities``), così un TPB debole non toglie da solo la candidatura alert.

Taratura: solo costanti sotto.
"""

from __future__ import annotations

from app.schemas.backtest import TradePlanBacktestAggregateRow

# Ampiezza massima del delta sul score (dopo peso affidabilità)
MAX_ABS_SCORE_DELTA: float = 4.0
# Malus/bonus «grezzi» prima del peso sample (piccoli, non distruttivi)
RAW_MALUS_NON_POSITIVE_EXPECTANCY: float = 3.5
RAW_BONUS_POSITIVE_EXPECTANCY: float = 2.0
# Soglia sample per poter applicare il bonus (coerente con TPB aggregato)
MIN_SAMPLE_FOR_BONUS: int = 28
# Sotto questa n il peso affidabilità è ~0 → aggiustamento score quasi nullo
RELIABILITY_N_FLOOR: int = 5
RELIABILITY_N_SCALE: float = 30.0  # (n - floor) / scale → 1.0 circa a n=35


def _reliability_weight(sample_size: int) -> float:
    """Campione piccolo → effetto quasi nullo; cresce in modo lineare fino a 1."""
    if sample_size <= RELIABILITY_N_FLOOR:
        return 0.0
    return min(1.0, (sample_size - RELIABILITY_N_FLOOR) / RELIABILITY_N_SCALE)


def operational_confidence_label(bucket: TradePlanBacktestAggregateRow | None) -> str:
    """
    Indicatore di cautela (non giudizio finale): high | medium | low | unknown.
    Con pochissime osservazioni resta unknown per non sovrainterpretare.
    """
    if bucket is None:
        return "unknown"
    n = bucket.sample_size
    exp = bucket.expectancy_r
    if n < 8:
        return "unknown"
    if exp is None:
        return "unknown"
    if exp <= 0:
        return "low"
    if exp > 0 and n >= MIN_SAMPLE_FOR_BONUS:
        return "high"
    return "medium"


def adjust_final_score_for_trade_plan_backtest(
    score: float,
    bucket: TradePlanBacktestAggregateRow | None,
) -> tuple[float, float, str, float | None, int | None, str]:
    """
    Soft adjustment sul score (ranking / display). Ritorna anche operational_confidence.

    Ritorna:
        adjusted_score, delta, label, expectancy, sample_size, operational_confidence
    """
    if bucket is None:
        return score, 0.0, "no_bucket", None, None, operational_confidence_label(None)

    n = bucket.sample_size
    exp = bucket.expectancy_r
    w = _reliability_weight(n)
    rules: list[str] = []
    raw_delta = 0.0

    if exp is not None:
        if exp <= 0:
            raw_delta -= RAW_MALUS_NON_POSITIVE_EXPECTANCY * w
            if w > 0:
                rules.append("soft_malus_exp")
        elif exp > 0 and n >= MIN_SAMPLE_FOR_BONUS:
            raw_delta += RAW_BONUS_POSITIVE_EXPECTANCY * w
            if w > 0:
                rules.append("soft_bonus_exp")

    delta = max(-MAX_ABS_SCORE_DELTA, min(MAX_ABS_SCORE_DELTA, raw_delta))
    s = float(score) + delta
    s = max(0.0, round(s, 2))
    delta_applied = round(s - float(score), 2)
    label = "+".join(rules) if rules else "neutral"
    return s, delta_applied, label, exp, n, operational_confidence_label(bucket)
