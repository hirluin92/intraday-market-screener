"""
Costanti condivise per Trade Plan Variant backtest / best / UI.

Usare questi valori al posto di magic number nel codice.
"""

# Variante considerata statisticamente utilizzabile per il ranking "best"
# Soglia minima campione per watchlist vs rejected (stesso valore del nome esplicito sotto).
TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE: int = 20
TRADE_PLAN_VARIANT_MIN_SAMPLE: int = TRADE_PLAN_VARIANT_WATCHLIST_MIN_SAMPLE

# Soglie stato operativo (best variant per bucket)
# Promossa solo con campione ampio (affidabilità superiore alla sola watchlist).
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

# Opportunità live: oltre questa distanza % dall'entry il segnale execute può essere declassato a monitor.
# Valore di default; in runtime si usa ``Settings.opportunity_price_staleness_pct`` (env).
PRICE_STALENESS_THRESHOLD_PCT: float = 1.0

# Simulazione equity: massimo numero di trade contemporanei sulla stessa barra (timestamp).
MAX_SIMULTANEOUS_TRADES: int = 3

# ---------------------------------------------------------------------------
# Qualità pattern: campione minimo per calcolare uno score numerico affidabile.
# Sotto questa soglia compute_pattern_quality_score restituisce None → "insufficient".
# Con n=30 e win_rate=60%, CI 95% Wilson ~ ±18% (vs ±30% con n=10).
# ---------------------------------------------------------------------------
PATTERN_QUALITY_MIN_SAMPLE: int = 30

# Soglie descrittive per CI / affidabilità delle stime (documentazione + sample_reliability_label).
PATTERN_QUALITY_SAMPLE_POOR: int = 30  # CI ancora ampio, stima debole
PATTERN_QUALITY_SAMPLE_FAIR: int = 50  # CI accettabile
PATTERN_QUALITY_SAMPLE_GOOD: int = 100  # stima affidabile
PATTERN_QUALITY_SAMPLE_EXCELLENT: int = 200  # stima solida

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
# Soglia minima pattern strength per execute (validator) e default operativo alert.
SIGNAL_MIN_STRENGTH: float = 0.65

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
        # Tech originali
        "GOOGL",
        "TSLA",
        "AMD",
        "META",
        "NVDA",
        "NFLX",
        # Crypto/Fintech
        "COIN",
        "MSTR",
        "HOOD",
        "SOFI",
        "SCHW",
        # SaaS/Cloud
        "RBLX",
        "SHOP",
        "ZS",
        "NET",
        "MDB",
        "CELH",
        "PLTR",
        "HPE",
        "SMCI",
        "DELL",
        # Space/Energy nuova
        "ACHR",
        "ASTS",
        "JOBY",
        "RKLB",
        "NNE",
        "OKLO",
        "WULF",
        "APLD",
        "SMR",
        "RXRX",
        # Healthcare
        "NVO",
        "LLY",
        "MRNA",
        # Consumer
        "NKE",
        "TGT",
        # Materials/Mining
        "MP",
        "NEM",
        # Retail (borderline ma positivo)
        "WMT",
    }
)

# Universo completo per scheduler — simboli da refreshare ogni ciclo (1h)
SCHEDULER_SYMBOLS_YAHOO_1H: list[tuple[str, str]] = [
    # Top 6 originali
    ("GOOGL", "1h"),
    ("TSLA", "1h"),
    ("AMD", "1h"),
    ("META", "1h"),
    ("NVDA", "1h"),
    ("NFLX", "1h"),
    # Crypto/Fintech
    ("COIN", "1h"),
    ("MSTR", "1h"),
    ("HOOD", "1h"),
    ("SHOP", "1h"),
    ("SOFI", "1h"),
    # SaaS/Cloud
    ("ZS", "1h"),
    ("NET", "1h"),
    ("CELH", "1h"),
    ("RBLX", "1h"),
    ("PLTR", "1h"),
    ("HPE", "1h"),
    ("MDB", "1h"),
    ("SMCI", "1h"),
    ("DELL", "1h"),
    # Space/Energy
    ("ACHR", "1h"),
    ("ASTS", "1h"),
    ("JOBY", "1h"),
    ("RKLB", "1h"),
    ("NNE", "1h"),
    ("OKLO", "1h"),
    ("WULF", "1h"),
    ("APLD", "1h"),
    ("SMR", "1h"),
    ("RXRX", "1h"),
    # Healthcare/Consumer/Materials
    ("NVO", "1h"),
    ("LLY", "1h"),
    ("MP", "1h"),
    ("MRNA", "1h"),
    ("NKE", "1h"),
    ("TGT", "1h"),
    ("NEM", "1h"),
    ("SCHW", "1h"),
    ("WMT", "1h"),
    # Regime filter e RS calculation
    ("SPY", "1h"),
]

SCHEDULER_SYMBOLS_BINANCE_1H: list[tuple[str, str]] = [
    ("ETH/USDT", "1h"),
    ("DOGE/USDT", "1h"),
    ("ADA/USDT", "1h"),
    ("SOL/USDT", "1h"),
    ("WLD/USDT", "1h"),
    ("MATIC/USDT", "1h"),
]

# BTC/USDT giornaliero: solo filtro regime macro (EMA50 ±2%) per crypto — non è un TF operativo pattern.
SCHEDULER_SYMBOLS_BINANCE_1D_REGIME: list[tuple[str, str]] = [
    ("BTC/USDT", "1d"),
]

# Pattern con edge reale confermato da simulazione OOS (nomi; la validità per TF usa VALIDATED_PATTERNS_1H / 5M).
# Aggiornato aprile 2026 dopo walk-forward e stress test.
VALIDATED_PATTERNS_OPERATIONAL: frozenset[str] = frozenset(
    {
        "compression_to_expansion_transition",
        "rsi_momentum_continuation",
    }
)

# Pattern in sviluppo — rilevati ma non operativi nella lista validata.
PATTERNS_IN_DEVELOPMENT: frozenset[str] = frozenset(
    {
        "impulsive_bullish_candle",
        "impulsive_bearish_candle",
        "engulfing_bullish",
        "engulfing_bearish",
        "hammer_reversal",
        "shooting_star_reversal",
        "morning_star",
        "evening_star",
        "bull_flag",
        "bear_flag",
        "inside_bar_breakout_bull",
        "support_bounce",
        "resistance_rejection",
        "breakout_with_retest",
        "vwap_bounce_bull",
        "vwap_bounce_bear",
        "opening_range_breakout_bull",
        "opening_range_breakout_bear",
        "fibonacci_bounce",
        "trend_continuation_pullback",
        "ema_pullback_to_support",
        "ema_pullback_to_resistance",
        "range_expansion_breakout_candidate",
    }
)

# Universo crypto validato (backtest OOS). Esclusi: BNB (negativo), XRP (marginale), BTC (debole).
# Da rivalutare con più dati: DOT, AVAX, FIL.
# ETH WR 73.3% AvgR 0.717 | DOGE WR 80.0% AvgR 1.096 | ADA WR 66.7% AvgR 0.594 | SOL WR 59.1% AvgR 0.282
# WLD WR 81.8% AvgR 0.958 | MATIC WR 63.9% AvgR 0.480 (n=72)
VALIDATED_SYMBOLS_BINANCE: frozenset[str] = frozenset(
    {
        "ETH/USDT",
        "DOGE/USDT",
        "ADA/USDT",
        "SOL/USDT",
        "WLD/USDT",
        "MATIC/USDT",
    }
)

VALIDATED_TIMEFRAMES: frozenset[str] = frozenset({"1h", "5m"})
