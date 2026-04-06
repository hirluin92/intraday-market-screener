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

# ---------------------------------------------------------------------------
# Costi simulazione backtest (round-trip, come frazione del notional).
# Modificare qui per tarare fee/slippage senza toccare la logica di simulazione.
# Default conservativo: fee exchange + slippage stimato (crypto spot / ETF US).
# ---------------------------------------------------------------------------
BACKTEST_FEE_RATE_RT_DEFAULT: float = 0.001  # 0.10% fee round-trip
BACKTEST_SLIPPAGE_RATE_DEFAULT: float = 0.0005  # 0.05% slippage stimato
BACKTEST_TOTAL_COST_RATE_DEFAULT: float = (
    BACKTEST_FEE_RATE_RT_DEFAULT + BACKTEST_SLIPPAGE_RATE_DEFAULT
)  # 0.15% totale

# Simulazione equity: massimo numero di trade contemporanei sulla stessa barra (timestamp).
MAX_SIMULTANEOUS_TRADES: int = 3

# ---------------------------------------------------------------------------
# Qualità pattern: campione minimo per calcolare uno score numerico affidabile.
# Sotto questa soglia compute_pattern_quality_score restituisce None → "unknown".
# ---------------------------------------------------------------------------
PATTERN_QUALITY_MIN_SAMPLE: int = 10

# ---------------------------------------------------------------------------
# Profili TP per variant backtest (label, moltiplicatore TP1 in R, TP2 in R).
# Aggiunte tp_2.0_3.0 / tp_2.5_4.0 per crypto 5m (target più larghi vs volatilità).
# Combinazioni: 3 entry × 3 stop × len(TP_PROFILE_CONFIGS) varianti totali.
# ---------------------------------------------------------------------------
TP_PROFILE_CONFIGS: tuple[tuple[str, float, float], ...] = (
    ("tp_1.0_2.0", 1.0, 2.0),
    ("tp_1.5_2.0", 1.5, 2.0),
    ("tp_1.5_2.5", 1.5, 2.5),
    ("tp_2.0_3.0", 2.0, 3.0),
    ("tp_2.5_4.0", 2.5, 4.0),
)

# ---------------------------------------------------------------------------
# Opportunità live — pattern e universo allineati a simulazione / OOS (aprile 2026)
# ---------------------------------------------------------------------------
VALIDATED_PATTERNS_1H: frozenset[str] = frozenset(
    {
        "compression_to_expansion_transition",
        "rsi_momentum_continuation",
    }
)

VALIDATED_PATTERNS_5M: frozenset[str] = frozenset(
    {
        "rsi_momentum_continuation",
    }
)

VALIDATED_SYMBOLS_YAHOO: frozenset[str] = frozenset(
    {
        "GOOGL",
        "TSLA",
        "AMD",
        "META",
        "NVDA",
        "NFLX",
        # Rimossi: SPY, QQQ, IWM, AAPL, MSFT, AMZN, JPM, GS
        # Motivo: AvgR insufficiente o negativo nella simulazione validata
    }
)

VALIDATED_SYMBOLS_BINANCE: frozenset[str] = frozenset(
    {
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "BNB/USDT",
        "XRP/USDT",
        "DOGE/USDT",
        "ADA/USDT",
    }
)

VALIDATED_TIMEFRAMES: frozenset[str] = frozenset({"1h", "5m"})
