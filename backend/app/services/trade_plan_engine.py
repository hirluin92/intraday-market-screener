"""
Trade Plan Engine v1.1 — logica esplicita e tunabile (nessun ML).

Input: metriche già calcolate dallo screener + OHLC ultima candela.
Mercati: crypto, stock, ETF (stesse regole; scala prezzo adattiva).

v1.1 (rispetto a v1): entry per strategia, stop con buffer strutturale + volatilità,
TP2 adattivo in range, R/R allineato ai livelli, invalidazione più leggibile.

Tuning: solo costanti in cima a questo modulo.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.schemas.trade_plan import TradePlanV1

# --- Soglie direzione (modificare qui) ---
MIN_FINAL_SCORE_FOR_LEVELS: Decimal = Decimal("28")
MIN_FINAL_LABELS: frozenset[str] = frozenset({"strong", "moderate"})
CONFLICT_PENALTY: bool = True

# Stop sotto il minimo (long) / sopra il massimo (short):
# buffer = max(RANGE_BELOW_SWING * range_barra, MIN_STOP_PCT_OF_PRICE * |close|)
RANGE_BELOW_SWING: Decimal = Decimal("0.32")
MIN_STOP_PCT_OF_PRICE: Decimal = Decimal("0.0012")  # 0.12% — floor su titoli liquidi

# Take profit come multipli del rischio R = |entry - stop| (parametri DEFAULT)
TP1_R_MULT: Decimal = Decimal("1.5")
TP2_R_MULT: Decimal = Decimal("2.5")
# In mercato laterale: target più conservativi (meno estensione attesa)
TP2_R_MULT_IN_RANGE: Decimal = Decimal("2.0")

# ---------------------------------------------------------------------------
# Parametri SL/TP ottimizzati per-pattern (MAE/MFE walk-forward, aprile 2026).
# Formato: pattern_name → (sl_buffer_mult, tp1_r, tp2_r)
# Solo pattern con almeno 3 blocchi walk-forward positivi vengono inclusi.
# - sl_buffer_mult: moltiplica il buffer strutturale calcolato da _stop_buffer
# - tp1_r / tp2_r: sostituiscono TP1_R_MULT / TP2_R_MULT per questo pattern
# Fonte: optimize_sl_tp.py — EV test positivo e coerente su train/val/test.
# ---------------------------------------------------------------------------
PATTERN_SL_TP_CONFIG: dict[str, tuple[float, float, float]] = {
    # (sl_mult, tp1_r, tp2_r) — ottimizzati con MAE/MFE walk-forward, aprile 2026.
    # Tutti i pattern hanno EV test positivo e robusto su train/val/test.
    "macd_divergence_bull":                (1.25, 2.0, 3.5),  # EV test=+0.835R WR=47.5%
    "rsi_divergence_bear":                 (0.90, 2.0, 3.5),  # EV test=+0.685R WR=38.9%
    "double_top":                          (0.75, 1.8, 3.5),  # EV test=+0.649R WR=35.0%
    "double_bottom":                       (1.00, 2.0, 3.5),  # EV test=+0.479R WR=35.7%
    "rsi_divergence_bull":                 (1.25, 1.8, 3.5),  # EV test=+0.350R WR=37.0%
    "compression_to_expansion_transition": (1.50, 1.8, 3.5),  # EV test=+0.347R WR=39.6%
    "rsi_momentum_continuation":           (1.50, 1.5, 3.5),  # EV test=+0.312R WR=42.3%
    "macd_divergence_bear":                (0.75, 2.0, 3.5),  # EV test=+0.240R WR=22.7%
    "engulfing_bullish":                   (0.60, 2.0, 3.5),  # EV test=+0.034R WR=16.9%
}

# --- Varianti esecuzione (backtest confronto) — moltiplicatore sul buffer stop dopo _stop_buffer ---
STOP_PROFILE_MULT: dict[str, Decimal] = {
    "tighter": Decimal("0.72"),
    "structural": Decimal("1.0"),
    "wider": Decimal("1.32"),
}

EntryStrategy = Literal["breakout", "retest", "close"]
StopProfile = Literal["tighter", "structural", "wider"]


def _d(x: object) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _volatility_stop_multiplier(volatility_regime: str) -> Decimal:
    """Allarga il buffer in alta vol, stringe leggermente in bassa (con nota già separata)."""
    v = (volatility_regime or "").lower()
    if v == "high":
        return Decimal("1.18")
    if v == "low":
        return Decimal("0.92")
    return Decimal("1.0")


def _tp2_multiplier(market_regime: str) -> Decimal:
    m = (market_regime or "").lower()
    if m == "range":
        return TP2_R_MULT_IN_RANGE
    return TP2_R_MULT


def _resolve_trade_direction(
    *,
    final_label: str,
    final_score: float,
    score_direction: str,
    pattern_direction: str | None,
) -> str:
    if final_label not in MIN_FINAL_LABELS and _d(final_score) < MIN_FINAL_SCORE_FOR_LEVELS:
        return "none"
    sd = (score_direction or "").lower()
    pd = (pattern_direction or "").lower() if pattern_direction else None

    if sd == "neutral":
        return "none"

    if sd == "bullish":
        if pd is None or pd == "bullish":
            return "long"
        if pd == "bearish" and CONFLICT_PENALTY:
            return "none"
        return "long"

    if sd == "bearish":
        if pd is None or pd == "bearish":
            return "short"
        if pd == "bullish" and CONFLICT_PENALTY:
            return "none"
        return "short"

    return "none"


def _resolve_entry_strategy(pattern_name: str | None, candle_expansion: str) -> str:
    pn = (pattern_name or "").lower()
    if "impulsive" in pn or "breakout" in pn:
        return "breakout"
    if "compression" in pn or candle_expansion == "expansion":
        return "retest"
    return "close"


def _bar_range(high: Decimal, low: Decimal, close: Decimal) -> Decimal:
    rng = high - low
    if rng <= 0:
        return abs(close) * MIN_STOP_PCT_OF_PRICE * Decimal("2")
    return rng


def _stop_buffer(
    close: Decimal,
    high: Decimal,
    low: Decimal,
    volatility_regime: str,
) -> Decimal:
    rng = _bar_range(high, low, close)
    pct_floor = abs(close) * MIN_STOP_PCT_OF_PRICE
    base = max(rng * RANGE_BELOW_SWING, pct_floor)
    return base * _volatility_stop_multiplier(volatility_regime)


def _entry_price(
    *,
    direction: str,
    entry_strat: str,
    high: Decimal,
    low: Decimal,
    close: Decimal,
) -> Decimal:
    """
    Riferimento ingresso coerente con la strategia (stesso schema TradePlanV1).

    - breakout: tra chiusura ed estremo direzionale (meno «tutto sul close»).
    - retest: metà barra verso l’estremo opposto alla direzione (simula attesa pullback).
    - close: ultima chiusura (conferma esplicita).
    """
    if entry_strat == "close":
        return close
    if direction == "long":
        if entry_strat == "breakout":
            return (high + close) / Decimal("2")
        # retest
        return (low + close) / Decimal("2")
    # short
    if entry_strat == "breakout":
        return (low + close) / Decimal("2")
    # retest
    return (high + close) / Decimal("2")


def _format_invalidation_long(stop: Decimal, extra_notes: list[str]) -> str:
    lines = [
        "Invalidazione operativa:",
        f"• chiusura sotto lo stop {stop} (invalidazione strutturale del long);",
        "• perdita del bias rialzista sul timeframe di riferimento.",
    ]
    if extra_notes:
        lines.append("Contesto: " + " ".join(extra_notes))
    return "\n".join(lines)


def _format_invalidation_short(stop: Decimal, extra_notes: list[str]) -> str:
    lines = [
        "Invalidazione operativa:",
        f"• chiusura sopra lo stop {stop} (invalidazione strutturale dello short);",
        "• perdita del bias ribassista sul timeframe di riferimento.",
    ]
    if extra_notes:
        lines.append("Contesto: " + " ".join(extra_notes))
    return "\n".join(lines)


def build_trade_plan_v1(
    *,
    final_opportunity_label: str,
    final_opportunity_score: float,
    score_direction: str,
    latest_pattern_direction: str | None,
    latest_pattern_name: str | None,
    candle_expansion: str,
    pattern_timeframe_gate_label: str,
    volatility_regime: str,
    market_regime: str,
    candle_high: Decimal | None,
    candle_low: Decimal | None,
    candle_close: Decimal | None,
) -> TradePlanV1:
    """
    Costruisce un TradePlanV1. Senza OHLC validi, restituisce livelli null e note esplicative.
    """
    direction = _resolve_trade_direction(
        final_label=final_opportunity_label,
        final_score=final_opportunity_score,
        score_direction=score_direction,
        pattern_direction=latest_pattern_direction,
    )
    entry_strat = _resolve_entry_strategy(latest_pattern_name, candle_expansion)

    notes: list[str] = []
    if pattern_timeframe_gate_label in ("poor", "marginal", "unknown"):
        notes.append(
            f"qualità pattern/timeframe «{pattern_timeframe_gate_label}» — ridurre size o attendere conferme.",
        )
    if volatility_regime == "low":
        notes.append("volatilità bassa: stop stretti possono essere colpiti da rumore.")
    if market_regime == "range" and entry_strat == "breakout":
        notes.append("mercato in range: breakout con rischio maggiore di falsi segnali.")

    if candle_high is None or candle_low is None or candle_close is None:
        return TradePlanV1(
            trade_direction=direction if direction != "none" else "none",
            entry_strategy=entry_strat,
            entry_price=None,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward_ratio=None,
            invalidation_note=(
                "Dati OHLC dell’ultima candela non disponibili: livelli numerici non calcolabili.\n"
                + ("Contesto: " + " ".join(notes) if notes else "")
            ).strip(),
        )

    hi = _d(candle_high)
    lo = _d(candle_low)
    cl = _d(candle_close)
    buf = _stop_buffer(cl, hi, lo, volatility_regime)
    tp2_mult = _tp2_multiplier(market_regime)

    # Parametri per-pattern ottimizzati (override defaults se disponibili)
    _pn = (latest_pattern_name or "").lower()
    _pat_cfg = PATTERN_SL_TP_CONFIG.get(_pn)
    if _pat_cfg is not None:
        _sl_mult, _tp1_r, _tp2_r = _pat_cfg
        buf = buf * Decimal(str(_sl_mult))
        tp1_override: Decimal | None = Decimal(str(_tp1_r))
        tp2_override: Decimal | None = Decimal(str(_tp2_r))
    else:
        tp1_override = None
        tp2_override = None

    if direction == "none":
        return TradePlanV1(
            trade_direction="none",
            entry_strategy=entry_strat,
            entry_price=cl,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward_ratio=None,
            invalidation_note=(
                "Setup non sufficientemente allineato (score finale, label o conflitto pattern/score).\n"
                + ("Contesto: " + " ".join(notes) if notes else "")
            ).strip(),
        )

    if direction == "long":
        entry = _entry_price(
            direction="long",
            entry_strat=entry_strat,
            high=hi,
            low=lo,
            close=cl,
        )
        stop = lo - buf
        if stop >= entry:
            stop = lo * Decimal("0.9995")
        risk = entry - stop
        if risk <= 0:
            return TradePlanV1(
                trade_direction="none",
                entry_strategy=entry_strat,
                entry_price=entry,
                stop_loss=None,
                take_profit_1=None,
                take_profit_2=None,
                risk_reward_ratio=None,
                invalidation_note=(
                    "Stop non valido rispetto al prezzo di ingresso stimato; nessun piano numerico affidabile."
                ),
            )
        _tp1_mult = tp1_override if tp1_override is not None else TP1_R_MULT
        _tp2_mult = tp2_override if tp2_override is not None else tp2_mult
        tp1 = entry + _tp1_mult * risk
        tp2 = entry + _tp2_mult * risk
        reward = tp1 - entry
        rr = reward / risk
        inv = _format_invalidation_long(stop, notes)
        return TradePlanV1(
            trade_direction="long",
            entry_strategy=entry_strat,
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            risk_reward_ratio=rr.quantize(Decimal("0.01")),
            invalidation_note=inv,
        )

    # short
    entry = _entry_price(
        direction="short",
        entry_strat=entry_strat,
        high=hi,
        low=lo,
        close=cl,
    )
    stop = hi + buf
    if stop <= entry:
        stop = hi * Decimal("1.0005")
    risk = stop - entry
    if risk <= 0:
        return TradePlanV1(
            trade_direction="none",
            entry_strategy=entry_strat,
            entry_price=entry,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward_ratio=None,
            invalidation_note=(
                "Stop non valido rispetto al prezzo di ingresso stimato; nessun piano numerico affidabile."
            ),
        )
    _tp1_mult = tp1_override if tp1_override is not None else TP1_R_MULT
    _tp2_mult = tp2_override if tp2_override is not None else tp2_mult
    tp1 = entry - _tp1_mult * risk
    tp2 = entry - _tp2_mult * risk
    reward = entry - tp1
    rr = reward / risk
    inv = _format_invalidation_short(stop, notes)
    return TradePlanV1(
        trade_direction="short",
        entry_strategy=entry_strat,
        entry_price=entry,
        stop_loss=stop,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_reward_ratio=rr.quantize(Decimal("0.01")),
        invalidation_note=inv,
    )


def build_trade_plan_v1_with_execution_variant(
    *,
    final_opportunity_label: str,
    final_opportunity_score: float,
    score_direction: str,
    latest_pattern_direction: str | None,
    pattern_timeframe_gate_label: str,
    volatility_regime: str,
    market_regime: str,
    candle_high: Decimal | None,
    candle_low: Decimal | None,
    candle_close: Decimal | None,
    entry_strategy: EntryStrategy,
    stop_profile: StopProfile,
    tp1_r_mult: Decimal,
    tp2_r_mult: Decimal,
) -> TradePlanV1:
    """
    Stessa logica direzionale e note di v1.1, ma ingresso/stop/TP fissati dalla variante
    (per confronto backtest tra profili di esecuzione). TP2 non usa l’override «range» del motore live.
    """
    direction = _resolve_trade_direction(
        final_label=final_opportunity_label,
        final_score=final_opportunity_score,
        score_direction=score_direction,
        pattern_direction=latest_pattern_direction,
    )
    entry_strat = entry_strategy

    notes: list[str] = []
    if pattern_timeframe_gate_label in ("poor", "marginal", "unknown"):
        notes.append(
            f"qualità pattern/timeframe «{pattern_timeframe_gate_label}» — ridurre size o attendere conferme.",
        )
    if volatility_regime == "low":
        notes.append("volatilità bassa: stop stretti possono essere colpiti da rumore.")
    if market_regime == "range" and entry_strat == "breakout":
        notes.append("mercato in range: breakout con rischio maggiore di falsi segnali.")
    notes.append(
        f"variante esecuzione: entry={entry_strat}, stop={stop_profile}, TP={tp1_r_mult}R/{tp2_r_mult}R.",
    )

    if candle_high is None or candle_low is None or candle_close is None:
        return TradePlanV1(
            trade_direction=direction if direction != "none" else "none",
            entry_strategy=entry_strat,
            entry_price=None,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward_ratio=None,
            invalidation_note=(
                "Dati OHLC dell’ultima candela non disponibili: livelli numerici non calcolabili.\n"
                + ("Contesto: " + " ".join(notes) if notes else "")
            ).strip(),
        )

    hi = _d(candle_high)
    lo = _d(candle_low)
    cl = _d(candle_close)
    buf_base = _stop_buffer(cl, hi, lo, volatility_regime)
    sp_mult = STOP_PROFILE_MULT.get(stop_profile, Decimal("1.0"))
    buf = buf_base * sp_mult

    if direction == "none":
        return TradePlanV1(
            trade_direction="none",
            entry_strategy=entry_strat,
            entry_price=cl,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward_ratio=None,
            invalidation_note=(
                "Setup non sufficientemente allineato (score finale, label o conflitto pattern/score).\n"
                + ("Contesto: " + " ".join(notes) if notes else "")
            ).strip(),
        )

    if direction == "long":
        entry = _entry_price(
            direction="long",
            entry_strat=entry_strat,
            high=hi,
            low=lo,
            close=cl,
        )
        stop = lo - buf
        if stop >= entry:
            stop = lo * Decimal("0.9995")
        risk = entry - stop
        if risk <= 0:
            return TradePlanV1(
                trade_direction="none",
                entry_strategy=entry_strat,
                entry_price=entry,
                stop_loss=None,
                take_profit_1=None,
                take_profit_2=None,
                risk_reward_ratio=None,
                invalidation_note=(
                    "Stop non valido rispetto al prezzo di ingresso stimato; nessun piano numerico affidabile."
                ),
            )
        tp1 = entry + tp1_r_mult * risk
        tp2 = entry + tp2_r_mult * risk
        reward = tp1 - entry
        rr = reward / risk
        inv = _format_invalidation_long(stop, notes)
        return TradePlanV1(
            trade_direction="long",
            entry_strategy=entry_strat,
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            risk_reward_ratio=rr.quantize(Decimal("0.01")),
            invalidation_note=inv,
        )

    entry = _entry_price(
        direction="short",
        entry_strat=entry_strat,
        high=hi,
        low=lo,
        close=cl,
    )
    stop = hi + buf
    if stop <= entry:
        stop = hi * Decimal("1.0005")
    risk = stop - entry
    if risk <= 0:
        return TradePlanV1(
            trade_direction="none",
            entry_strategy=entry_strat,
            entry_price=entry,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            risk_reward_ratio=None,
            invalidation_note=(
                "Stop non valido rispetto al prezzo di ingresso stimato; nessun piano numerico affidabile."
            ),
        )
    tp1 = entry - tp1_r_mult * risk
    tp2 = entry - tp2_r_mult * risk
    reward = entry - tp1
    rr = reward / risk
    inv = _format_invalidation_short(stop, notes)
    return TradePlanV1(
        trade_direction="short",
        entry_strategy=entry_strat,
        entry_price=entry,
        stop_loss=stop,
        take_profit_1=tp1,
        take_profit_2=tp2,
        risk_reward_ratio=rr.quantize(Decimal("0.01")),
        invalidation_note=inv,
    )
