"""
Pattern name sets — validated, blocked, and in-development pattern identifiers.
"""

# ---------------------------------------------------------------------------
# Pattern operativi validati per timeframe (whitelist screener/validator/alerts).
# ---------------------------------------------------------------------------
VALIDATED_PATTERNS_1H: frozenset[str] = frozenset(
    {
        # ── Pattern universali (attivi in qualsiasi regime) ──────────────────────
        "double_bottom",
        "double_top",
        # ── Pattern regime-dipendenti (attivi solo se regime corretto) ────────────
        "engulfing_bullish",
        "macd_divergence_bull",
        "rsi_divergence_bull",
        "rsi_divergence_bear",
        "macd_divergence_bear",
    }
)

VALIDATED_PATTERNS_5M: frozenset[str] = frozenset(
    {
        "double_bottom",
        "double_top",
        "macd_divergence_bull",    # solo regime BEAR
        "rsi_divergence_bull",     # solo regime BEAR
        "rsi_divergence_bear",     # universale SHORT
        "macd_divergence_bear",    # universale SHORT
    }
)

# Pattern con edge reale confermato (superset degli operativi, include engulfing su 1h).
VALIDATED_PATTERNS_OPERATIONAL: frozenset[str] = frozenset(
    {
        "double_bottom",
        "double_top",
        "engulfing_bullish",
        "macd_divergence_bull",
        "rsi_divergence_bull",
        "rsi_divergence_bear",
        "macd_divergence_bear",
    }
)

# Pattern attivi SOLO in regime BEAR.
PATTERNS_BEAR_REGIME_ONLY: frozenset[str] = frozenset(
    {
        "engulfing_bullish",
    }
)

# Pattern con EV più alto in regime BULL ma universali (trattati come universali).
PATTERNS_BULL_REGIME_ONLY: frozenset[str] = frozenset()

# Pattern in sviluppo — campione insufficiente o EV non confermato OOS.
PATTERNS_IN_DEVELOPMENT: frozenset[str] = frozenset(
    {
        "hammer_reversal",
        "fibonacci_bounce",
        "engulfing_bearish",
        "shooting_star_reversal",
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
        "liquidity_sweep_bull",
        "liquidity_sweep_bear",
    }
)

# Pattern da NON tradare — EV quasi zero su campione grande o WR < 40% confermato.
PATTERNS_BLOCKED: frozenset[str] = frozenset(
    {
        "compression_to_expansion_transition",
        "impulsive_bearish_candle",
        "opening_range_breakout_bear",
        "breakout_with_retest",
        "evening_star",
        "impulsive_bullish_candle",
        "vwap_bounce_bear",
        "bull_flag",
        "bear_flag",
        "range_expansion_breakout_candidate",
        "volatility_squeeze_breakout",
        "nr7_breakout",
        "opening_range_breakout_bull",
        "inside_bar_breakout_bull",
    }
)

# Pattern con EV negativo confermato su Alpaca 5m.
PATTERNS_BLOCKED_ALPACA_5M: frozenset[str] = frozenset(
    {
        "engulfing_bullish",
        "trend_continuation_pullback",
        "support_bounce",
        "resistance_rejection",
        "hammer_reversal",
        "shooting_star_reversal",
        "ema_pullback_to_support",
        "ema_pullback_to_resistance",
        "fvg_retest_bull",
        "fvg_retest_bear",
        "vwap_bounce_bull",
        "morning_star",
        "ob_retest_bull",
        "ob_retest_bear",
    }
)

# OOS Alpaca 5m validated patterns.
PATTERNS_VALIDATED_ALPACA_5M: frozenset[str] = frozenset(
    {
        "double_top",
        "macd_divergence_bear",
        "macd_divergence_bull",
        "double_bottom",
        "rsi_momentum_continuation",
    }
)

# Mappa (provider, timeframe) → frozenset di pattern bloccati per quel contesto.
PATTERNS_BLOCKED_BY_SCOPE: dict[tuple[str, str], frozenset[str]] = {
    ("alpaca", "5m"): PATTERNS_BLOCKED_ALPACA_5M | PATTERNS_BLOCKED,
}

# Gate ranking per engulfing_bullish (unico pattern con AUC interna > 0.55).
STRADA_A_ENGULFING_MIN_FINAL_SCORE: float = 84.0
