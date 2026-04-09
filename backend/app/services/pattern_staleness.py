"""
Età del pattern rispetto all’ultimo contesto (barre di ritardo).

Un pattern rilevato molte candele fa non ha lo stesso peso operativo di uno sull’ultima barra.
"""

from __future__ import annotations

from datetime import datetime

# ---------------------------------------------------------------------------
# Soglie in barre oltre le quali il pattern è «datato» (solo tuning — la logica è sotto).
# Modificare qui i numeri senza toccare compute_pattern_staleness_fields.
# ---------------------------------------------------------------------------
STALE_THRESHOLD_BARS_BY_TIMEFRAME: dict[str, int] = {
    "1m": 10,
    "5m": 8,
    "15m": 5,
    "1h": 8,   # 8h = copertura di un'intera sessione di trading (era 3h)
    "1d": 2,
}
# TF non in mappa (es. nuovi intervalli): usa questo default.
DEFAULT_STALE_THRESHOLD_BARS = 5


def timeframe_bar_minutes(timeframe: str) -> float | None:
    """Minuti per una candela (es. 5m → 5, 1h → 60, 1d → 1440)."""
    tf = (timeframe or "").strip().lower()
    if not tf:
        return None
    try:
        if tf.endswith("m"):
            return float(tf[:-1])
        if tf.endswith("h"):
            return float(tf[:-1]) * 60.0
        if tf.endswith("d"):
            return float(tf[:-1]) * 60.0 * 24.0
    except ValueError:
        return None
    return None


def stale_threshold_bars(timeframe: str) -> int:
    """Barre oltre le quali pattern_stale è True. Vedi STALE_THRESHOLD_BARS_BY_TIMEFRAME."""
    tf = (timeframe or "").strip().lower()
    if tf in STALE_THRESHOLD_BARS_BY_TIMEFRAME:
        return STALE_THRESHOLD_BARS_BY_TIMEFRAME[tf]
    return DEFAULT_STALE_THRESHOLD_BARS


def compute_pattern_staleness_fields(
    context_timestamp: datetime,
    pattern_timestamp: datetime | None,
    timeframe: str,
) -> tuple[int | None, bool]:
    """
    Restituisce (pattern_age_bars, pattern_stale).

    - pattern_age_bars: barre intere tra timestamp pattern e contesto (0 = stessa «era»).
    - pattern_stale: True se età > soglia per il TF (solo se c’è pattern).
    """
    if pattern_timestamp is None:
        return None, False
    ctx = context_timestamp
    pt = pattern_timestamp
    if pt > ctx:
        return 0, False
    delta_sec = (ctx - pt).total_seconds()
    if delta_sec < 0:
        return 0, False
    bar_min = timeframe_bar_minutes(timeframe)
    if bar_min is None or bar_min <= 0:
        return None, False
    bar_sec = bar_min * 60.0
    age_bars = int(delta_sec // bar_sec)
    thresh = stale_threshold_bars(timeframe)
    stale = age_bars > thresh
    return age_bars, stale
