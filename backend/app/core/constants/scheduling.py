"""
Scheduling and time-based constants — entry scan limits, holding periods, TP profiles.
"""

# Profili TP per variant backtest.
TP_PROFILE_CONFIGS: tuple[tuple[str, float, float], ...] = (
    ("tp_1.0_2.0", 1.0, 2.0),
    ("tp_1.5_2.0", 1.5, 2.0),
    ("tp_1.5_2.5", 1.5, 2.5),
    ("tp_2.0_3.0", 2.0, 3.0),
    ("tp_2.5_4.0", 2.5, 4.0),
)

# Ricerca entry per timeframe.
MAX_BARS_ENTRY_SCAN_1H: int = 4
MAX_BARS_ENTRY_SCAN_5M: int = 3

MAX_BARS_ENTRY_SCAN_BY_TF: dict[str, int] = {
    "1h": MAX_BARS_ENTRY_SCAN_1H,
    "5m": MAX_BARS_ENTRY_SCAN_5M,
    "15m": 20,
    "4h": 20,
    "1d": 20,
}

# Ora minima ET per operatività 5m.
MIN_HOUR_ET_5M: int = 11
EXCLUDED_HOURS_ET_5M_START: int = 0
EXCLUDED_HOURS_ET_5M_END: int = 11

# Holding period massimo per timeframe.
MAX_BARS_HOLDING_1H: int = 48
MAX_BARS_HOLDING_5M: int = 24

MAX_BARS_HOLDING_BY_TF: dict[str, int] = {
    "1h": MAX_BARS_HOLDING_1H,
    "5m": MAX_BARS_HOLDING_5M,
}

# Timeframe operativi validati.
VALIDATED_TIMEFRAMES: frozenset[str] = frozenset({"1h", "5m"})
