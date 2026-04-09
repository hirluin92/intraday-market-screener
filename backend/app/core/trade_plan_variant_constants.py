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
SIGNAL_MIN_STRENGTH: float = 0.70

# Numero minimo di pattern distinti VALIDATI che devono risultare attivi nella
# stessa barra 1h per lo stesso simbolo prima che il segnale venga promosso
# a "execute". Valore 1 = nessun filtro (backward-compatible).
# Validato via OOS: min_confluence=2 → TEST EV +0.478R (+95.3%), WR 58.4%,
# PF 2.82, DD -19.8% — robusto su walk-forward (apr 2026).
SIGNAL_MIN_CONFLUENCE: int = 2

VALIDATED_PATTERNS_1H: frozenset[str] = frozenset(
    {
        # ── Pattern universali (attivi in qualsiasi regime) ──────────────────────
        # WR 67% / EV +0.45R — top assoluto, confermato OOS
        "compression_to_expansion_transition",
        # WR 56% / EV +0.30R — secondo, confermato OOS
        "rsi_momentum_continuation",
        # WR 65% / EV +0.55R — migliore nuovo pattern v2, robusto in tutti i regimi
        "double_bottom",
        # WR 61% / EV +0.41R — speculare, robusto in tutti i regimi
        "double_top",
        # fibonacci_bounce → SOSPESO (apr 2026): EV isolato +0.218R OOS ma EV portafoglio
        # = -0.580R nel test (apr 2025–apr 2026). Blocca slot track_capital per molte barre
        # con trade aperti a lungo (SL/TP generici + strength bassa → outcompetuto sempre).
        # Da riesaminare con allocazione dedicata + SL/TP ottimizzati per isolamento.
        # ── Pattern regime-dipendenti (attivi solo se regime corretto) ────────────
        # Regime BEAR: WR 67% / EV +0.16R — inversione istituzionale contro trend
        "engulfing_bullish",
        # Regime BEAR: WR 71% / EV +0.86R — divergenza MACD in mercato ribassista
        "macd_divergence_bull",
        # Regime BEAR: WR 64% / EV +0.68R — divergenza RSI in mercato ribassista
        "rsi_divergence_bull",
        # Universale SHORT: WR 58% bull / 58% bear — EV +0.40R bull / +0.22R bear
        "rsi_divergence_bear",
        # Universale SHORT: WR 59% bull / 53% bear — EV +0.37R bull / +0.25R bear
        "macd_divergence_bear",
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

# Simboli US stocks su Alpaca 5m — rispecchiano SCHEDULER_SYMBOLS_YAHOO_1H per coerenza.
# Abilitati solo se ALPACA_ENABLED=true in .env.
# Questi stessi simboli vengono backfillati via POST /api/v1/backtest/alpaca-backfill.
SCHEDULER_SYMBOLS_ALPACA_5M: list[tuple[str, str]] = [
    ("GOOGL", "5m"),
    ("TSLA", "5m"),
    ("AMD", "5m"),
    ("META", "5m"),
    ("NVDA", "5m"),
    ("NFLX", "5m"),
    ("COIN", "5m"),
    ("MSTR", "5m"),
    ("HOOD", "5m"),
    ("SHOP", "5m"),
    ("SOFI", "5m"),
    ("ZS", "5m"),
    ("NET", "5m"),
    ("CELH", "5m"),
    ("RBLX", "5m"),
    ("PLTR", "5m"),
    ("MDB", "5m"),
    ("SMCI", "5m"),
    ("DELL", "5m"),
    ("NVO", "5m"),
    ("LLY", "5m"),
    ("MRNA", "5m"),
    ("NKE", "5m"),
    ("TGT", "5m"),
    ("SCHW", "5m"),
    ("WMT", "5m"),
    ("SPY", "5m"),
    ("AAPL", "5m"),
    ("AMZN", "5m"),
    ("MSFT", "5m"),
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

# ---------------------------------------------------------------------------
# Pattern con edge reale confermato da analisi dataset + simulazione OOS.
# Aggiornato aprile 2026 dopo analisi dataset 26.714 segnali (WR per pattern).
#
# LONG patterns promossi:
#   compression_to_expansion_transition  63% WR (n=932)
#   rsi_momentum_continuation            61% WR (n=581)
#   hammer_reversal                      57% WR (n=69)   ← soglia campione bassa
#   fibonacci_bounce                     54% WR (n=179)
#   engulfing_bullish                    52% WR (n=1331)
#
# SHORT patterns promossi:
#   compression_to_expansion_transition  55% WR (n=898)  ← funziona short!
#   rsi_momentum_continuation            53% WR (n=478)  ← funziona short!
#   engulfing_bearish                    45% WR (n=1263)
#   shooting_star_reversal               45% WR (n=66)   ← soglia campione bassa
#
# ESCLUSI (WR < 40%):
#   impulsive_bearish_candle   32% WR (n=3646) ← il principale trascinatore negativo
#   opening_range_breakout_bear 32% WR (n=1684)
#   breakout_with_retest short  29% WR (n=455)
#   evening_star               37% WR (n=240)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Classificazione aggiornata aprile 2026 dopo analisi per regime SPY su 38k+ segnali v2.
#
# PATTERN UNIVERSALI (EV > +0.40R in tutti i regimi, n > 600):
#   double_bottom   WR=64.5% EV=+0.55R (bull+0.50 / bear+0.60 / late+0.44)
#   double_top      WR=60.9% EV=+0.41R (bull+0.42 / bear+0.39 / late+0.43)
#   [fibonacci_bounce sospeso: EV portafoglio = -0.580R nel test apr 2025–26 → in sviluppo]
#
# PATTERN REGIME-CONDIZIONALI (EV molto diverso per regime):
#   macd_divergence_bull  bear+0.86R★★★  bull+0.18R★★  → attivo solo in BEAR
#   rsi_divergence_bull   bear+0.68R★★★  bull+0.11R★   → attivo solo in BEAR
#   engulfing_bullish     bear+0.155R★★  bull=-0.13R✗  → attivo solo in BEAR
#
# PATTERN SHORT UNIVERSALI (EV positivo in entrambi i regimi — testato apr 2026):
#   rsi_divergence_bear   bull+0.40R★★★  bear+0.22R★★  → attivo in QUALSIASI regime
#   macd_divergence_bear  bull+0.37R★★★  bear+0.25R★★  → attivo in QUALSIASI regime
#
# BLOCCATI (EV ~0 su n > 1000):
#   volatility_squeeze_breakout  EV=+0.04R  n=10211
#   nr7_breakout                 EV=+0.04R  n=3350
# ---------------------------------------------------------------------------
VALIDATED_PATTERNS_OPERATIONAL: frozenset[str] = frozenset(
    {
        # Sempre attivi (qualsiasi regime): WR>50%, EV>+0.15R confermato OOS
        "compression_to_expansion_transition",  # WR 67% / EV +0.45R — top assoluto
        "rsi_momentum_continuation",            # WR 56% / EV +0.30R — secondo
        "double_bottom",                        # WR 65% / EV +0.55R — nuovo top, universale
        "double_top",                           # WR 61% / EV +0.41R — robusto in tutti i regimi
        # fibonacci_bounce → SOSPESO: EV portafoglio = -0.580R OOS test set (apr 2026)
        # Attivo solo in regime BEAR (logica nel validator)
        "engulfing_bullish",                    # WR 67% / EV +0.155R in bear
        "macd_divergence_bull",                 # WR 71% / EV +0.86R in bear
        "rsi_divergence_bull",                  # WR 64% / EV +0.68R in bear
        # SHORT divergenze — attivi in qualsiasi regime (EV positivo in entrambi)
        # bear: WR=58% EV=+0.22R | bull: WR=58% EV=+0.40R  → universo completo
        "rsi_divergence_bear",
        # bear: WR=53% EV=+0.25R | bull: WR=59% EV=+0.37R  → universo completo
        "macd_divergence_bear",
    }
)

# Pattern attivi SOLO in regime BEAR (EV positivo in bear, neutro/negativo in bull)
PATTERNS_BEAR_REGIME_ONLY: frozenset[str] = frozenset(
    {
        "engulfing_bullish",     # bear: WR=67% EV=+0.16R | bull: WR=50% EV=-0.13R
        "macd_divergence_bull",  # bear: WR=71% EV=+0.86R | bull: WR=47% EV=+0.18R
        "rsi_divergence_bull",   # bear: WR=64% EV=+0.68R | bull: WR=44% EV=+0.11R
    }
)

# Pattern con EV più alto in regime BULL ma comunque positivi anche in BEAR.
# Trattati come universali dal validator: fire in qualsiasi regime (EV > 0).
# La differenza di edge per regime viene comunicata nella rationale.
PATTERNS_BULL_REGIME_ONLY: frozenset[str] = frozenset(
    {
        # rsi_divergence_bear   → spostato in universali (EV bear=+0.22R confermato)
        # macd_divergence_bear  → spostato in universali (EV bear=+0.25R confermato)
    }
)

# Pattern in sviluppo — campione insufficiente o EV non ancora confermato OOS.
# Monitorati ma non eseguiti. Valutare dopo 200+ segnali eseguiti.
PATTERNS_IN_DEVELOPMENT: frozenset[str] = frozenset(
    {
        "hammer_reversal",               # WR 57% ctf, n=4 eseguiti — campione troppo piccolo
        # fibonacci_bounce: EV isolato OOS +0.218R (robusto) MA EV portfolio = -0.580R nel test
        # apr 2025–apr 2026. Causa: strength bassa (avg 0.654, max 0.732) → outcompetuto nei
        # bar con competizione, ma quando vince il slot (pochi bar) ha EV negativo.
        # Riesaminare: (1) SL/TP dedicati ottimizzati, (2) allocazione isolata senza concorrenza.
        "fibonacci_bounce",
        "engulfing_bearish",             # WR 45% ctf — da validare
        "shooting_star_reversal",        # WR 45% ctf — da validare
        "morning_star",
        "vwap_bounce_bull",
        "ob_retest_bull",
        "ob_retest_bear",
        "trend_continuation_pullback",
        "ema_pullback_to_support",
        "ema_pullback_to_resistance",
        "fvg_retest_bull",
        "fvg_retest_bear",
        "resistance_rejection",
        "support_bounce",
        # Liquidity sweep: campione troppo piccolo (n=7-10) per decidere
        "liquidity_sweep_bull",          # EV +0.42R ma n=7 — non sufficiente
        "liquidity_sweep_bear",          # EV +0.37R ma n=10 — non sufficiente
    }
)

# Pattern da NON tradare — EV quasi zero su campione grande o WR < 40% confermato.
PATTERNS_BLOCKED: frozenset[str] = frozenset(
    {
        "impulsive_bearish_candle",       # 32% WR, n=3646 — il principale problema
        "opening_range_breakout_bear",    # 32% WR, n=1684
        "breakout_with_retest",           # 37% short (29%), 43% long — edge insufficiente
        "evening_star",                   # 37% WR, n=240
        "impulsive_bullish_candle",       # 41% WR, n=4057 — sotto breakeven
        "vwap_bounce_bear",               # 38% WR
        "bull_flag",
        "bear_flag",
        "range_expansion_breakout_candidate",
        # Nuovi v2 con EV ~0 su campione grande — non producono edge reale
        "volatility_squeeze_breakout",    # EV=+0.04R, n=10211 — troppi segnali, troppo rumore
        "nr7_breakout",                   # EV=+0.04R, n=3350 — definizione troppo generica
        # Quality score alta (84.69) ma EV simulazione NEGATIVO: SL troppo stretto causa
        # troppi stop prima del TP. Rivalutare solo con SL/TP ottimizzati per questo pattern.
        "opening_range_breakout_bull",    # EV train=-0.099R, EV test=-0.148R — OOS apr 2026
        # EV quasi zero in simulazione (train=-0.099R, test=+0.012R) — edge insufficiente.
        "inside_bar_breakout_bull",       # EV train=-0.099R, EV test=+0.012R — OOS apr 2026
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

# ─── Pattern validati per provider+timeframe specifico ────────────────────────
#
# OOS Alpaca 5m (cutoff 2026-02-01, 30 simboli, 7 mesi di dati):
#   double_top              WR=69.5% EV=+0.583R PF=2.37 N=643  ★★★ migliora in OOS
#   macd_divergence_bear    WR=64.4% EV=+0.586R PF=2.20 N=592  ★★★ robusto
#   macd_divergence_bull    WR=56.4% EV=+0.451R PF=1.82 N=489  ★★★ robusto
#   double_bottom           WR=57.0% EV=+0.401R PF=1.69 N=582  ★★  buono
#   rsi_momentum_continuation  WR=42.9% EV=+0.069R PF=1.13 N=515  ★  marginale
#   compression_to_expansion_transition  WR=44.4% EV=+0.056R PF=1.09 N=714  ★  marginale
#
PATTERNS_VALIDATED_ALPACA_5M: frozenset[str] = frozenset(
    {
        "double_top",                           # WR=69.5% EV=+0.583R — il migliore su 5m
        "macd_divergence_bear",                 # WR=64.4% EV=+0.586R — short divergenza MACD
        "macd_divergence_bull",                 # WR=56.4% EV=+0.451R — long divergenza MACD
        "double_bottom",                        # WR=57.0% EV=+0.401R — reversal su supporto
        "rsi_momentum_continuation",            # WR=42.9% EV=+0.069R — marginale, monitorare
        "compression_to_expansion_transition",  # WR=44.4% EV=+0.056R — marginale, monitorare
    }
)

# Pattern con EV negativo confermato su Alpaca 5m — bloccati solo per questo scope.
# (Non includere quelli già in PATTERNS_BLOCKED globale per evitare duplicati.)
PATTERNS_BLOCKED_ALPACA_5M: frozenset[str] = frozenset(
    {
        # Testati esplicitamente su Alpaca 5m OOS — EV negativo
        "engulfing_bullish",                    # WR=40.5% EV=-0.144R
        "trend_continuation_pullback",          # WR=47.7% EV=-0.078R
        "support_bounce",                       # WR=43.2% EV=-0.276R
        "resistance_rejection",                 # WR=50.8% EV=-0.074R
        "hammer_reversal",                      # WR=41.8% EV=-0.343R
        "shooting_star_reversal",               # WR=47.6% EV=-0.186R
        "ema_pullback_to_support",              # WR=46.0% EV=-0.205R
        "ema_pullback_to_resistance",           # WR=45.9% EV=-0.198R
        "fvg_retest_bull",                      # WR=41.2% EV=-0.416R
        "fvg_retest_bear",                      # WR=46.2% EV=-0.272R
        "vwap_bounce_bull",                     # WR=46.9% EV=-0.205R
        "morning_star",                         # WR=46.1% EV=-0.188R
        "ob_retest_bull",                       # WR=43.8% EV=-0.246R
        "ob_retest_bear",                       # WR=46.8% EV=-0.177R
    }
)

# Mappa (provider, timeframe) → frozenset di pattern bloccati per quel contesto.
# Usata da simulation_service in sostituzione di PATTERNS_BLOCKED quando esiste
# una entry per il provider+timeframe corrente.
PATTERNS_BLOCKED_BY_SCOPE: dict[tuple[str, str], frozenset[str]] = {
    ("alpaca", "5m"): PATTERNS_BLOCKED_ALPACA_5M | PATTERNS_BLOCKED,
}
