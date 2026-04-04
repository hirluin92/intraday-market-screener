"""
Costanti condivise per Trade Plan Variant backtest / best / UI.

Usare questi valori al posto di magic number nel codice.
"""

# Variante considerata statisticamente utilizzabile per il ranking "best"
TRADE_PLAN_VARIANT_MIN_SAMPLE: int = 20

# Soglie stato operativo (best variant per bucket)
TRADE_PLAN_VARIANT_PROMOTED_MIN_SAMPLE: int = 50
# watchlist: [MIN_SAMPLE, PROMOTED_MIN_SAMPLE - 1] con expectancy > 0

# Watchlist: sample minimo per applicare la variante in live (oltre a promoted)
TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE_FOR_LIVE: int = 30
