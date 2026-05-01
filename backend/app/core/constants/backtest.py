"""
Backtest and simulation constants — cost rates, sample thresholds, simulation limits.
"""

# Costi simulazione backtest (round-trip).
BACKTEST_FEE_RATE_RT_DEFAULT: float = 0.001
BACKTEST_SLIPPAGE_RATE_DEFAULT: float = 0.0005
BACKTEST_TOTAL_COST_RATE_DEFAULT: float = (
    BACKTEST_FEE_RATE_RT_DEFAULT + BACKTEST_SLIPPAGE_RATE_DEFAULT
)

# Qualità pattern: campione minimo per calcolare uno score numerico affidabile.
PATTERN_QUALITY_MIN_SAMPLE: int = 30

# Soglie descrittive per CI / affidabilità.
PATTERN_QUALITY_SAMPLE_POOR: int = 30
PATTERN_QUALITY_SAMPLE_FAIR: int = 50
PATTERN_QUALITY_SAMPLE_GOOD: int = 100
PATTERN_QUALITY_SAMPLE_EXCELLENT: int = 200

# Simulazione equity.
MAX_SIMULTANEOUS_TRADES: int = 3

# Limiti righe pattern per simulazione.
PATTERN_ROWS_CAP: int = 50_000
SIMULATION_PATTERN_HARD_CAP: int = 500_000
EQUITY_FLOOR: float = 1.0

# Variant backtest thresholds.
TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE: int = 20
TRADE_PLAN_VARIANT_MIN_SAMPLE: int = TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE
TRADE_PLAN_VARIANT_PROMOTED_MIN_SAMPLE: int = 50
TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE_FOR_LIVE: int = 30

# Alert scoring thresholds.
ALERT_MIN_FINAL_SCORE: float = 45.0
ALERT_HIGH_FINAL_SCORE: float = 70.0
