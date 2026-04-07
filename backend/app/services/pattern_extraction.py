"""
MVP pattern engine v1: detects simple intraday labels from CandleFeature + CandleContext.

Heuristics are explicit, threshold-based, and ordered for readability — no ML.
Processing is per (exchange, symbol, timeframe), timestamp ascending, with optional
look-back at the previous bar's context for transition-style patterns.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_indicator import CandleIndicator
from app.models.candle_pattern import CandlePattern
from app.schemas.patterns import PatternExtractRequest, PatternExtractResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern refinement v1 — tune thresholds here (explicit, no ML).
# Goals: fewer weak/contradictory labels; require cleaner bodies, closes at extremes,
# alignment with direction_bias where it matters, and avoid dead-low-volatility chop.
# ---------------------------------------------------------------------------

# Impulsive candles: stricter body vs range and close at candle extreme.
_IMPULSIVE_MIN_BODY_RATIO = 0.62  # was 0.55
_IMPULSIVE_BULL_MIN_CLOSE_POS = 0.72  # was 0.65 — close nearer to high
_IMPULSIVE_BEAR_MAX_CLOSE_POS = 0.28  # was 0.35 — close nearer to low
_IMPULSIVE_MIN_VOL_RATIO_BONUS = 1.22  # was 1.15 — volume confirmation slightly stronger

# Reject impulsive signals in very quiet vol (often noise / mean-reversion chop).
_IMPULSIVE_ALLOWED_VOLATILITY = frozenset({"normal", "high"})

# Range expansion breakout: require a real body, close in the trade direction, and no bias clash.
_RE_BREAKOUT_MIN_BODY_RATIO = 0.38
_RE_BREAKOUT_BULL_MIN_CP = 0.55  # bullish breakout closes in upper half
_RE_BREAKOUT_BEAR_MAX_CP = 0.45

# Compression → expansion: expansion bar must show commitment + not low vol; optional bias alignment.
_CT_EXP_MIN_BODY_RATIO = 0.42
_CT_EXP_ALLOWED_VOLATILITY = frozenset({"normal", "high"})
_CT_EXP_ALLOWED_MARKET = frozenset({"trend", "range"})

# Trend continuation pullback: ripresa dopo ritracciamento in trend
_TCP_MIN_BODY_RATIO = 0.40  # corpo minimo barra di ripresa
_TCP_BULL_MIN_CLOSE_POS = 0.55  # chiusura nella metà superiore (ripresa bullish)
_TCP_BEAR_MAX_CLOSE_POS = 0.45  # chiusura nella metà inferiore (ripresa bearish)
_TCP_PULLBACK_BARS = 2  # barre di pullback richieste prima della ripresa
_TCP_ALLOWED_VOLATILITY = frozenset({"normal", "high"})

# EMA pullback: distanza % dal prezzo all'EMA20 per considerare il pullback
_EMP_BULL_EMA20_PCT_MIN = -1.5  # prezzo max 1.5% sotto EMA20
_EMP_BULL_EMA20_PCT_MAX = 0.5  # prezzo max 0.5% sopra EMA20
_EMP_BEAR_EMA20_PCT_MIN = -0.5  # speculare short
_EMP_BEAR_EMA20_PCT_MAX = 1.5
_EMP_RSI_BULL_MIN = 35.0  # RSI in pullback (non oversold estremo)
_EMP_RSI_BULL_MAX = 55.0
_EMP_RSI_BEAR_MIN = 45.0
_EMP_RSI_BEAR_MAX = 65.0
_EMP_MIN_BODY_RATIO = 0.38

# RSI momentum continuation
_RMC_RSI_BULL_MIN = 55.0  # RSI in zona momentum bullish
_RMC_RSI_BEAR_MAX = 45.0  # RSI in zona momentum bearish
_RMC_MIN_VOLUME_RATIO = 1.3  # volume sopra media
_RMC_MIN_BODY_RATIO = 0.42


def _relative_strength_bonus(ind: CandleIndicator | None, direction: str) -> float:
    """Bonus/penalità da RS vs SPY (solo se valorizzato sui CandleIndicator)."""
    if ind is None or ind.rs_signal is None:
        return 0.0
    sig = ind.rs_signal
    if direction == "bullish":
        if sig == "strong_bull":
            return 0.08
        if sig == "bull":
            return 0.04
        if sig == "strong_bear":
            return -0.08
        if sig == "bear":
            return -0.04
    else:
        if sig == "strong_bear":
            return 0.08
        if sig == "bear":
            return 0.04
        if sig == "strong_bull":
            return -0.08
        if sig == "bull":
            return -0.04
    return 0.0


# Pattern multi-candela classici
_ENG_MIN_BODY_RATIO = 0.50  # corpo minimo per engulfing
_ENG_ENGULF_FACTOR = 1.05  # il corpo deve essere > 1.05× quello precedente
_HAMMER_WICK_BODY_RATIO = 2.0  # wick inferiore ≥ 2× corpo
_HAMMER_MAX_UPPER_WICK = 0.30  # wick superiore max 30% del range
_STAR_PROXIMITY_PCT = 1.5  # % max di distanza da swing per hammer/shooting star
_MORNING_STAR_MIN_BODY = 0.40  # corpo terza candela morning star
_FLAG_IMPULSE_BARS = 3  # barre minime per impulso flag
_FLAG_CONSOLIDATION_BARS = 2  # barre minime consolidamento
_FLAG_MAX_RETRACEMENT = 0.50  # max retracement consolidamento vs impulso
_BOUNCE_RSI_MAX = 45.0  # RSI max per support bounce
_REJECTION_RSI_MIN = 55.0  # RSI min per resistance rejection
_BREAKOUT_RETEST_PCT = 0.5  # % max di distanza per retest valido

_PREV_FEATURES_LOOKBACK = max(
    _TCP_PULLBACK_BARS + 1,
    _FLAG_IMPULSE_BARS + _FLAG_CONSOLIDATION_BARS,
)

# VWAP e Opening Range patterns
_VWAP_PROXIMITY_PCT = 0.3  # % max di distanza da VWAP per pattern VWAP
_OR_BREAKOUT_CONFIRM_PCT = 0.1  # % min sopra/sotto OR per conferma breakout
_FIB_PROXIMITY_PCT = 0.4  # % max di distanza da livello Fibonacci

# FVG retest: dentro zona FVG + candela direzionale con corpo sufficiente
_FVG_RETEST_MIN_BODY_RATIO = 0.35
_FVG_RETEST_BULL_MIN_CP = 0.50
_FVG_RETEST_BEAR_MAX_CP = 0.50

_OB_MIN_BODY_RATIO = 0.40
_OB_MIN_CP_BULL = 0.45
_OB_MAX_CP_BEAR = 0.55


def _f(x: Any) -> float:
    if x is None:
        return 0.0
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


_UPSERT_CHUNK_SIZE = 500


async def _chunked_upsert_patterns(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
    """Bulk upsert CandlePattern in chunk (limite parametri asyncpg)."""
    if not rows:
        return 0
    total_rc = 0
    for i in range(0, len(rows), _UPSERT_CHUNK_SIZE):
        chunk = rows[i : i + _UPSERT_CHUNK_SIZE]
        stmt_ins = insert(CandlePattern).values(chunk)
        excluded = stmt_ins.excluded
        stmt_ins = stmt_ins.on_conflict_do_update(
            constraint="uq_candle_patterns_feature_pattern",
            set_={
                "candle_context_id": excluded.candle_context_id,
                "asset_type": excluded.asset_type,
                "provider": excluded.provider,
                "symbol": excluded.symbol,
                "exchange": excluded.exchange,
                "timeframe": excluded.timeframe,
                "market_metadata": excluded.market_metadata,
                "timestamp": excluded.timestamp,
                "pattern_strength": excluded.pattern_strength,
                "direction": excluded.direction,
            },
        )
        result = await session.execute(stmt_ins)
        rc = result.rowcount
        if rc is not None and rc >= 0:
            total_rc += int(rc)
    await session.commit()
    return total_rc


def _body_ratio(feat: CandleFeature) -> float:
    r = _f(feat.range_size)
    if r <= 0:
        return 0.0
    return _f(feat.body_size) / r


def _cvd_strength_adjust(
    strength: float,
    ind: CandleIndicator | None,
    pattern_direction: str,
) -> float:
    """Pesa la strength con cvd_trend (opzionale; non esclude mai il pattern)."""
    if ind is None or ind.cvd_trend is None:
        return min(1.0, strength)
    t = ind.cvd_trend
    if pattern_direction == "bullish":
        if t == "bearish":
            strength *= 0.85
        elif t == "bullish":
            strength *= 1.10
    elif pattern_direction == "bearish":
        if t == "bullish":
            strength *= 0.85
        elif t == "bearish":
            strength *= 1.10
    return min(1.0, strength)


def _direction_from_bias_and_bar(ctx: CandleContext, feat: CandleFeature) -> str:
    """Map stored direction_bias + bar color to a single directional label."""
    if ctx.direction_bias == "bullish":
        return "bullish"
    if ctx.direction_bias == "bearish":
        return "bearish"
    return "bullish" if feat.is_bullish else "bearish"


def _detect_impulsive_bullish(feat: CandleFeature, ctx: CandleContext) -> tuple[float, str] | None:
    """
    Large real body, close near the high: classic impulsive buy-side bar.

    Refinement v1: tighter body/close thresholds; skip bearish context bias (contradictory);
    skip low-volatility regimes (weak participation); slightly higher volume bar for bonus.
    """
    if not feat.is_bullish:
        return None
    # Bullish impulse against explicit bearish bias is usually noise for this MVP label.
    if ctx.direction_bias == "bearish":
        return None
    if ctx.volatility_regime not in _IMPULSIVE_ALLOWED_VOLATILITY:
        return None
    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if br < _IMPULSIVE_MIN_BODY_RATIO or cp < _IMPULSIVE_BULL_MIN_CLOSE_POS:
        return None
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    # Small boost when context already leans bullish (less contradictory).
    bias_bonus = 0.05 if ctx.direction_bias == "bullish" else 0.0
    strength = min(1.0, 0.45 * br + 0.55 * cp + vol_bonus + bias_bonus)
    if feat.volume_ratio_vs_prev is not None and _f(feat.volume_ratio_vs_prev) > _IMPULSIVE_MIN_VOL_RATIO_BONUS:
        strength = min(1.0, strength + 0.05)
    return (strength, "bullish")


def _detect_impulsive_bearish(feat: CandleFeature, ctx: CandleContext) -> tuple[float, str] | None:
    """
    Large real body, close near the low.

    Refinement v1: symmetric to bullish — tighter thresholds, no bullish-bias contradiction,
    no low-vol chop, slightly stricter volume bonus.
    """
    if feat.is_bullish:
        return None
    if ctx.direction_bias == "bullish":
        return None
    if ctx.volatility_regime not in _IMPULSIVE_ALLOWED_VOLATILITY:
        return None
    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if br < _IMPULSIVE_MIN_BODY_RATIO or cp > _IMPULSIVE_BEAR_MAX_CLOSE_POS:
        return None
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    bias_bonus = 0.05 if ctx.direction_bias == "bearish" else 0.0
    strength = min(1.0, 0.45 * br + 0.55 * (1.0 - cp) + vol_bonus + bias_bonus)
    if feat.volume_ratio_vs_prev is not None and _f(feat.volume_ratio_vs_prev) > _IMPULSIVE_MIN_VOL_RATIO_BONUS:
        strength = min(1.0, strength + 0.05)
    return (strength, "bearish")


def _detect_range_expansion_breakout_candidate(
    feat: CandleFeature,
    ctx: CandleContext,
) -> tuple[float, str] | None:
    """
    Range regime but this bar expands in range vs its rolling window — potential
    pre-breakout / volatility expansion from a quiet background.

    Refinement v1: require meaningful body (not wick-only), close in the breakout direction,
    and do not label when direction_bias clearly opposes the breakout side.
    """
    if ctx.market_regime != "range":
        return None
    if ctx.candle_expansion != "expansion":
        return None
    if ctx.volatility_regime not in ("normal", "high"):
        return None
    br = _body_ratio(feat)
    if br < _RE_BREAKOUT_MIN_BODY_RATIO:
        return None
    direction = _direction_from_bias_and_bar(ctx, feat)
    cp = _f(feat.close_position_in_range)
    # Bias conflict: e.g. bearish bias but long breakout bar — skip (noisy).
    if direction == "bullish":
        if ctx.direction_bias == "bearish":
            return None
        if cp < _RE_BREAKOUT_BULL_MIN_CP:
            return None
    else:
        if ctx.direction_bias == "bullish":
            return None
        if cp > _RE_BREAKOUT_BEAR_MAX_CP:
            return None
    bias_bonus = 0.1 if ctx.direction_bias in ("bullish", "bearish") else 0.0
    vol_bonus = 0.1 if ctx.volatility_regime == "high" else 0.0
    if direction == "bullish":
        extreme_score = cp
    else:
        extreme_score = 1.0 - cp
    strength = min(1.0, 0.45 + bias_bonus + vol_bonus + 0.25 * extreme_score)
    return (strength, direction)


def _detect_compression_to_expansion_transition(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_ctx: CandleContext | None,
    ind: CandleIndicator | None = None,
) -> tuple[float, str] | None:
    """
    Prior bar classified as compression; this bar as expansion — regime shift.

    Refinement v1: gate on market + volatility regime, minimum body on the expansion bar,
    and coarse alignment between bar color / close and direction_bias to reduce contradictory
    transition labels.
    """
    if prev_ctx is None:
        return None
    if prev_ctx.candle_expansion != "compression":
        return None
    if ctx.candle_expansion != "expansion":
        return None
    if ctx.market_regime not in _CT_EXP_ALLOWED_MARKET:
        return None
    if ctx.volatility_regime not in _CT_EXP_ALLOWED_VOLATILITY:
        return None
    br = _body_ratio(feat)
    if br < _CT_EXP_MIN_BODY_RATIO:
        return None
    cp = _f(feat.close_position_in_range)
    direction = _direction_from_bias_and_bar(ctx, feat)
    # When bias is directional, require the expansion candle to agree (bar + close quadrant).
    if ctx.direction_bias == "bullish":
        if not feat.is_bullish or cp < 0.52:
            return None
    elif ctx.direction_bias == "bearish":
        if feat.is_bullish or cp > 0.48:
            return None
    else:
        # Neutral bias: still require a decisive close (avoid doji-like transitions).
        if not (cp >= 0.58 or cp <= 0.42):
            return None
    vol_bonus = 0.15 if ctx.volatility_regime == "high" else 0.0
    align = 0.08 if (
        (direction == "bullish" and feat.is_bullish) or (direction == "bearish" and not feat.is_bullish)
    ) else 0.0
    rs_bonus = _relative_strength_bonus(ind, direction)
    strength = min(1.0, 0.52 + vol_bonus + align + rs_bonus)
    return (strength, direction)


def _detect_trend_continuation_pullback(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """
    Pullback in trend seguito da ripresa direzionale.

    Richiede:
    - market_regime = trend e direction_bias direzionale (non neutrale)
    - Ultime _TCP_PULLBACK_BARS barre con pct_return_1 contro la direzione del trend
      (pullback: prezzi scendono in trend bullish, salgono in trend bearish)
    - Barra corrente: corpo solido, chiusura all'estremo della direzione del trend,
      allineata con direction_bias

    prev_features: lista barre precedenti disponibili (oldest→newest), esclusa la corrente.
    Richiede almeno _TCP_PULLBACK_BARS barre precedenti con pct_return_1 valorizzato.
    """
    if ctx.market_regime != "trend":
        return None
    if ctx.direction_bias not in ("bullish", "bearish"):
        return None
    if ctx.volatility_regime not in _TCP_ALLOWED_VOLATILITY:
        return None

    prev_with_return = [f for f in prev_features if f.pct_return_1 is not None]
    if len(prev_with_return) < _TCP_PULLBACK_BARS:
        return None

    pullback_bars = prev_with_return[-_TCP_PULLBACK_BARS:]

    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)

    if ctx.direction_bias == "bullish":
        pullback_ok = all(_f(f.pct_return_1) < 0 for f in pullback_bars)
        if not pullback_ok:
            return None
        if not feat.is_bullish:
            return None
        if br < _TCP_MIN_BODY_RATIO:
            return None
        if cp < _TCP_BULL_MIN_CLOSE_POS:
            return None
        vol_bonus = 0.08 if ctx.volatility_regime == "high" else 0.0
        avg_pullback = sum(_f(f.pct_return_1) for f in pullback_bars) / len(pullback_bars)
        depth_bonus = min(0.08, abs(avg_pullback) * 2.0)
        strength = min(1.0, 0.50 + 0.20 * br + 0.15 * cp + vol_bonus + depth_bonus)
        return (strength, "bullish")

    pullback_ok = all(_f(f.pct_return_1) > 0 for f in pullback_bars)
    if not pullback_ok:
        return None
    if feat.is_bullish:
        return None
    if br < _TCP_MIN_BODY_RATIO:
        return None
    if cp > _TCP_BEAR_MAX_CLOSE_POS:
        return None
    vol_bonus = 0.08 if ctx.volatility_regime == "high" else 0.0
    avg_pullback = sum(_f(f.pct_return_1) for f in pullback_bars) / len(pullback_bars)
    depth_bonus = min(0.08, abs(avg_pullback) * 2.0)
    strength = min(1.0, 0.50 + 0.20 * br + 0.15 * (1.0 - cp) + vol_bonus + depth_bonus)
    return (strength, "bearish")


def _detect_ema_pullback_to_support(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Buy the dip su EMA20 in uptrend."""
    if ind is None:
        return None
    if ind.ema_20 is None or ind.ema_50 is None:
        return None
    if ind.rsi_14 is None:
        return None
    if ind.price_vs_ema20_pct is None or ind.price_vs_ema50_pct is None:
        return None

    ema20 = float(ind.ema_20)
    ema50 = float(ind.ema_50)
    rsi = float(ind.rsi_14)
    pct_vs_ema20 = float(ind.price_vs_ema20_pct)

    if ema20 <= ema50:
        return None

    if not (_EMP_BULL_EMA20_PCT_MIN <= pct_vs_ema20 <= _EMP_BULL_EMA20_PCT_MAX):
        return None

    if not (_EMP_RSI_BULL_MIN <= rsi <= _EMP_RSI_BULL_MAX):
        return None

    if ctx.volatility_regime == "low":
        return None

    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if not feat.is_bullish:
        return None
    if br < _EMP_MIN_BODY_RATIO:
        return None
    if cp < 0.52:
        return None

    rsi_factor = (55.0 - rsi) / 20.0
    strength = min(1.0, 0.52 + 0.18 * br + 0.15 * rsi_factor + 0.08 * cp)
    return (strength, "bullish")


def _detect_ema_pullback_to_resistance(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Sell the bounce su EMA20 in downtrend."""
    if ind is None:
        return None
    if ind.ema_20 is None or ind.ema_50 is None:
        return None
    if ind.rsi_14 is None:
        return None
    if ind.price_vs_ema20_pct is None:
        return None

    ema20 = float(ind.ema_20)
    ema50 = float(ind.ema_50)
    rsi = float(ind.rsi_14)
    pct_vs_ema20 = float(ind.price_vs_ema20_pct)

    if ema20 >= ema50:
        return None

    if not (_EMP_BEAR_EMA20_PCT_MIN <= pct_vs_ema20 <= _EMP_BEAR_EMA20_PCT_MAX):
        return None

    if not (_EMP_RSI_BEAR_MIN <= rsi <= _EMP_RSI_BEAR_MAX):
        return None

    if ctx.volatility_regime == "low":
        return None

    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)
    if feat.is_bullish:
        return None
    if br < _EMP_MIN_BODY_RATIO:
        return None
    if cp > 0.48:
        return None

    rsi_factor = (rsi - 45.0) / 20.0
    strength = min(1.0, 0.52 + 0.18 * br + 0.15 * rsi_factor + 0.08 * (1.0 - cp))
    return (strength, "bearish")


def _detect_rsi_momentum_continuation(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
    prev_indicators: list[CandleIndicator],
) -> tuple[float, str] | None:
    """Breakout con momentum RSI e volume sopra media."""
    if ind is None:
        return None
    if ind.rsi_14 is None:
        return None
    if ind.volume_ratio_vs_ma20 is None:
        return None
    if ind.atr_14 is None:
        return None

    if ctx.market_regime != "trend":
        return None
    if ctx.volatility_regime == "low":
        return None

    rsi = float(ind.rsi_14)
    vol_ratio = float(ind.volume_ratio_vs_ma20)
    atr = float(ind.atr_14)

    if vol_ratio < _RMC_MIN_VOLUME_RATIO:
        return None

    if prev_indicators:
        prev_atrs = [float(p.atr_14) for p in prev_indicators if p.atr_14 is not None]
        if prev_atrs:
            avg_atr = sum(prev_atrs) / len(prev_atrs)
            if avg_atr > 0 and atr <= avg_atr * 1.05:
                return None

    br = _body_ratio(feat)
    cp = _f(feat.close_position_in_range)

    if ctx.direction_bias == "bullish":
        if rsi < _RMC_RSI_BULL_MIN:
            return None
        if not feat.is_bullish:
            return None
        if br < _RMC_MIN_BODY_RATIO:
            return None
        if cp < 0.55:
            return None
        vol_bonus = min(0.10, (vol_ratio - 1.3) * 0.15)
        rs_bonus = _relative_strength_bonus(ind, "bullish")
        strength = min(1.0, 0.55 + 0.15 * br + vol_bonus + rs_bonus)
        return (strength, "bullish")

    if ctx.direction_bias == "bearish":
        if rsi > _RMC_RSI_BEAR_MAX:
            return None
        if feat.is_bullish:
            return None
        if br < _RMC_MIN_BODY_RATIO:
            return None
        if cp > 0.45:
            return None
        vol_bonus = min(0.10, (vol_ratio - 1.3) * 0.15)
        rs_bonus = _relative_strength_bonus(ind, "bearish")
        strength = min(1.0, 0.55 + 0.15 * br + vol_bonus + rs_bonus)
        return (strength, "bearish")

    return None


def _prev_candle_data(
    prev_features: list[CandleFeature],
    n: int = 1,
) -> CandleFeature | None:
    """Ritorna la N-esima barra precedente (1=ultima, 2=penultima, ecc.)."""
    if len(prev_features) < n:
        return None
    return prev_features[-n]


def _detect_engulfing_bullish(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """
    Candela bullish che ingloba completamente il corpo della candela bearish precedente.
    Condizioni: candela corrente bullish, precedente bearish,
    body corrente > body precedente × _ENG_ENGULF_FACTOR,
    apertura corrente < chiusura precedente, chiusura corrente > apertura precedente.
    """
    prev = _prev_candle_data(prev_features, 1)
    if prev is None:
        return None
    if not feat.is_bullish or prev.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _ENG_MIN_BODY_RATIO:
        return None
    if _f(feat.body_size) < _f(prev.body_size) * _ENG_ENGULF_FACTOR:
        return None
    if ctx.volatility_regime == "low":
        return None
    vol_bonus = 0.08 if ctx.volatility_regime == "high" else 0.0
    strength = min(1.0, 0.55 + 0.20 * br + vol_bonus)
    strength = _cvd_strength_adjust(strength, ind, "bullish")
    return (strength, "bullish")


def _detect_engulfing_bearish(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Speculare bearish di engulfing_bullish."""
    prev = _prev_candle_data(prev_features, 1)
    if prev is None:
        return None
    if feat.is_bullish or not prev.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _ENG_MIN_BODY_RATIO:
        return None
    if _f(feat.body_size) < _f(prev.body_size) * _ENG_ENGULF_FACTOR:
        return None
    if ctx.volatility_regime == "low":
        return None
    vol_bonus = 0.08 if ctx.volatility_regime == "high" else 0.0
    strength = min(1.0, 0.55 + 0.20 * br + vol_bonus)
    strength = _cvd_strength_adjust(strength, ind, "bearish")
    return (strength, "bearish")


def _detect_hammer_reversal(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """
    Hammer vicino a swing low: corpo piccolo in alto, wick inferiore lungo.
    Richiede: wick_lower >= 2× body, upper_wick piccolo,
    prezzo vicino a swing low (dist_to_swing_low_pct < _STAR_PROXIMITY_PCT).
    """
    rng = _f(feat.range_size)
    if rng <= 0:
        return None
    body = _f(feat.body_size)
    lower_wick = _f(feat.lower_wick)
    upper_wick = _f(feat.upper_wick)
    if body <= 0:
        return None
    if lower_wick < body * _HAMMER_WICK_BODY_RATIO:
        return None
    if upper_wick / rng > _HAMMER_MAX_UPPER_WICK:
        return None
    # Vicino a swing low
    if ind is not None and ind.dist_to_swing_low_pct is not None:
        if float(ind.dist_to_swing_low_pct) > _STAR_PROXIMITY_PCT:
            return None
    if ctx.volatility_regime == "low":
        return None
    wick_ratio = lower_wick / rng
    strength = min(1.0, 0.50 + 0.25 * wick_ratio)
    return (strength, "bullish")


def _detect_shooting_star_reversal(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Shooting star vicino a swing high: speculare al hammer."""
    rng = _f(feat.range_size)
    if rng <= 0:
        return None
    body = _f(feat.body_size)
    upper_wick = _f(feat.upper_wick)
    lower_wick = _f(feat.lower_wick)
    if body <= 0:
        return None
    if upper_wick < body * _HAMMER_WICK_BODY_RATIO:
        return None
    if lower_wick / rng > _HAMMER_MAX_UPPER_WICK:
        return None
    if ind is not None and ind.dist_to_swing_high_pct is not None:
        if float(ind.dist_to_swing_high_pct) > _STAR_PROXIMITY_PCT:
            return None
    if ctx.volatility_regime == "low":
        return None
    wick_ratio = upper_wick / rng
    strength = min(1.0, 0.50 + 0.25 * wick_ratio)
    return (strength, "bearish")


def _detect_morning_star(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """
    Morning star: 3 candele.
    Candela -2: bearish grande (corpo >= 0.50)
    Candela -1: piccola (corpo <= 0.30 del range) — doji o indecisione
    Candela 0 (corrente): bullish grande (corpo >= _MORNING_STAR_MIN_BODY)
    """
    prev1 = _prev_candle_data(prev_features, 1)  # doji
    prev2 = _prev_candle_data(prev_features, 2)  # bearish grande
    if prev1 is None or prev2 is None:
        return None
    if prev2.is_bullish:
        return None
    if _body_ratio(prev2) < 0.50:
        return None
    if _body_ratio(prev1) > 0.30:
        return None
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _MORNING_STAR_MIN_BODY:
        return None
    if ctx.volatility_regime == "low":
        return None
    strength = min(1.0, 0.58 + 0.18 * br)
    return (strength, "bullish")


def _detect_evening_star(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """Evening star: speculare al morning star."""
    prev1 = _prev_candle_data(prev_features, 1)
    prev2 = _prev_candle_data(prev_features, 2)
    if prev1 is None or prev2 is None:
        return None
    if not prev2.is_bullish:
        return None
    if _body_ratio(prev2) < 0.50:
        return None
    if _body_ratio(prev1) > 0.30:
        return None
    if feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _MORNING_STAR_MIN_BODY:
        return None
    if ctx.volatility_regime == "low":
        return None
    strength = min(1.0, 0.58 + 0.18 * br)
    return (strength, "bearish")


def _detect_bull_flag(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """
    Bull flag: impulso rialzista seguito da consolidamento, poi breakout.
    Richiede almeno _FLAG_IMPULSE_BARS + _FLAG_CONSOLIDATION_BARS barre precedenti.
    Impulso: le prime N barre sono prevalentemente bullish con avg return positivo.
    Consolidamento: le ultime M barre hanno range compresso (body ratio < 0.35).
    Barra corrente: bullish che rompe il massimo del consolidamento.
    """
    needed = _FLAG_IMPULSE_BARS + _FLAG_CONSOLIDATION_BARS
    if len(prev_features) < needed:
        return None
    if not feat.is_bullish:
        return None

    consolidation = prev_features[-_FLAG_CONSOLIDATION_BARS:]
    impulse = prev_features[-needed : -_FLAG_CONSOLIDATION_BARS]

    # Impulso: maggioranza bullish
    impulse_bullish = sum(1 for f in impulse if f.is_bullish)
    if impulse_bullish < len(impulse) * 0.6:
        return None

    # Consolidamento: corpo compresso
    consol_body_avg = sum(_body_ratio(f) for f in consolidation) / len(consolidation)
    if consol_body_avg > 0.35:
        return None

    # Retracement non troppo profondo
    impulse_returns = [
        _f(f.pct_return_1) for f in impulse if f.pct_return_1 is not None
    ]
    if not impulse_returns:
        return None
    total_impulse = sum(r for r in impulse_returns if r > 0)
    if total_impulse <= 0:
        return None

    consol_returns = [
        _f(f.pct_return_1) for f in consolidation if f.pct_return_1 is not None
    ]
    total_retracement = abs(sum(r for r in consol_returns if r < 0))
    if total_retracement > total_impulse * _FLAG_MAX_RETRACEMENT:
        return None

    br = _body_ratio(feat)
    if br < 0.35:
        return None

    strength = min(1.0, 0.55 + 0.15 * br)
    return (strength, "bullish")


def _detect_bear_flag(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """Bear flag: speculare al bull flag."""
    needed = _FLAG_IMPULSE_BARS + _FLAG_CONSOLIDATION_BARS
    if len(prev_features) < needed:
        return None
    if feat.is_bullish:
        return None

    consolidation = prev_features[-_FLAG_CONSOLIDATION_BARS:]
    impulse = prev_features[-needed : -_FLAG_CONSOLIDATION_BARS]

    impulse_bearish = sum(1 for f in impulse if not f.is_bullish)
    if impulse_bearish < len(impulse) * 0.6:
        return None

    consol_body_avg = sum(_body_ratio(f) for f in consolidation) / len(consolidation)
    if consol_body_avg > 0.35:
        return None

    impulse_returns = [
        _f(f.pct_return_1) for f in impulse if f.pct_return_1 is not None
    ]
    if not impulse_returns:
        return None
    total_impulse = abs(sum(r for r in impulse_returns if r < 0))
    if total_impulse <= 0:
        return None

    consol_returns = [
        _f(f.pct_return_1) for f in consolidation if f.pct_return_1 is not None
    ]
    total_retracement = sum(r for r in consol_returns if r > 0)
    if total_retracement > total_impulse * _FLAG_MAX_RETRACEMENT:
        return None

    br = _body_ratio(feat)
    if br < 0.35:
        return None

    strength = min(1.0, 0.55 + 0.15 * br)
    return (strength, "bearish")


def _detect_inside_bar_breakout_bull(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """
    Inside bar seguita da breakout bullish.
    Barra -1: inside bar (range contenuto nella barra -2).
    Barra 0: bullish che rompe verso l'alto con corpo solido.
    """
    prev1 = _prev_candle_data(prev_features, 1)  # inside bar
    prev2 = _prev_candle_data(prev_features, 2)  # madre
    if prev1 is None or prev2 is None:
        return None
    # prev1 deve essere inside bar rispetto a prev2
    if _f(prev1.range_size) >= _f(prev2.range_size) * 0.9:
        return None
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < 0.40:
        return None
    cp = _f(feat.close_position_in_range)
    if cp < 0.55:
        return None
    if ctx.volatility_regime == "low":
        return None
    strength = min(1.0, 0.55 + 0.20 * br)
    return (strength, "bullish")


def _detect_support_bounce(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
    _prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """
    Rimbalzo da supporto (swing low) con conferma RSI.
    Richiede: prezzo vicino a swing low, RSI < _BOUNCE_RSI_MAX,
    candela corrente bullish con corpo solido.
    """
    if ind is None:
        return None
    if ind.dist_to_swing_low_pct is None or ind.rsi_14 is None:
        return None
    dist = float(ind.dist_to_swing_low_pct)
    rsi = float(ind.rsi_14)
    if dist > 1.5:
        return None
    if rsi > _BOUNCE_RSI_MAX:
        return None
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < 0.35:
        return None
    cp = _f(feat.close_position_in_range)
    if cp < 0.50:
        return None
    if ctx.volatility_regime == "low":
        return None
    rsi_factor = (_BOUNCE_RSI_MAX - rsi) / _BOUNCE_RSI_MAX
    strength = min(1.0, 0.52 + 0.15 * br + 0.10 * rsi_factor)
    strength = _cvd_strength_adjust(strength, ind, "bullish")
    return (strength, "bullish")


def _detect_resistance_rejection(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
    _prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """
    Rejection da resistenza (swing high) con conferma RSI.
    Speculare a support_bounce.
    """
    if ind is None:
        return None
    if ind.dist_to_swing_high_pct is None or ind.rsi_14 is None:
        return None
    dist = float(ind.dist_to_swing_high_pct)
    rsi = float(ind.rsi_14)
    if dist > 1.5:
        return None
    if rsi < _REJECTION_RSI_MIN:
        return None
    if feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < 0.35:
        return None
    cp = _f(feat.close_position_in_range)
    if cp > 0.50:
        return None
    if ctx.volatility_regime == "low":
        return None
    rsi_factor = (rsi - _REJECTION_RSI_MIN) / (100.0 - _REJECTION_RSI_MIN)
    strength = min(1.0, 0.52 + 0.15 * br + 0.10 * rsi_factor)
    strength = _cvd_strength_adjust(strength, ind, "bearish")
    return (strength, "bearish")


def _detect_breakout_with_retest(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
    _prev_features: list[CandleFeature],
) -> tuple[float, str] | None:
    """
    Rottura di swing high/low con retest e ripresa.
    Pattern: il prezzo ha rotto un livello, è tornato a testarlo
    (dist_to_swing_high/low_pct < _BREAKOUT_RETEST_PCT)
    e ora riprende la direzione del breakout.

    Bullish: prezzo sopra swing high, ritorna vicino, poi candela bullish.
    Bearish: prezzo sotto swing low, rimbalza vicino, poi candela bearish.
    """
    if ind is None:
        return None

    br = _body_ratio(feat)
    if br < 0.38:
        return None

    # Bullish breakout retest
    if (
        ind.dist_to_swing_high_pct is not None
        and float(ind.dist_to_swing_high_pct) <= _BREAKOUT_RETEST_PCT
        and feat.is_bullish
        and ind.price_vs_ema20_pct is not None
        and float(ind.price_vs_ema20_pct) > 0  # sopra EMA20
    ):
        cp = _f(feat.close_position_in_range)
        if cp >= 0.55:
            strength = min(1.0, 0.55 + 0.18 * br)
            return (strength, "bullish")

    # Bearish breakout retest
    if (
        ind.dist_to_swing_low_pct is not None
        and float(ind.dist_to_swing_low_pct) <= _BREAKOUT_RETEST_PCT
        and not feat.is_bullish
        and ind.price_vs_ema20_pct is not None
        and float(ind.price_vs_ema20_pct) < 0  # sotto EMA20
    ):
        cp = _f(feat.close_position_in_range)
        if cp <= 0.45:
            strength = min(1.0, 0.55 + 0.18 * br)
            return (strength, "bearish")

    return None


def _detect_vwap_bounce_bull(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """
    Rimbalzo bullish da VWAP.
    Prezzo tocca VWAP (dist < _VWAP_PROXIMITY_PCT) e rimbalza con candela bullish.
    """
    if ind is None or ind.price_vs_vwap_pct is None or ind.vwap is None:
        return None
    dist = abs(float(ind.price_vs_vwap_pct))
    if dist > _VWAP_PROXIMITY_PCT:
        return None
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < 0.35:
        return None
    cp = _f(feat.close_position_in_range)
    if cp < 0.50:
        return None
    if ctx.volatility_regime == "low":
        return None
    strength = min(1.0, 0.52 + 0.20 * br)
    strength = _cvd_strength_adjust(strength, ind, "bullish")
    return (strength, "bullish")


def _detect_vwap_bounce_bear(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Rejection bearish da VWAP: speculare."""
    if ind is None or ind.price_vs_vwap_pct is None or ind.vwap is None:
        return None
    dist = abs(float(ind.price_vs_vwap_pct))
    if dist > _VWAP_PROXIMITY_PCT:
        return None
    if feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < 0.35:
        return None
    cp = _f(feat.close_position_in_range)
    if cp > 0.50:
        return None
    if ctx.volatility_regime == "low":
        return None
    strength = min(1.0, 0.52 + 0.20 * br)
    strength = _cvd_strength_adjust(strength, ind, "bearish")
    return (strength, "bearish")


def _detect_opening_range_breakout_bull(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """
    Breakout rialzista dell'Opening Range.
    Prezzo supera opening_range_high con candela bullish e corpo solido.
    """
    if ind is None:
        return None
    if ind.opening_range_high is None or ind.price_vs_or_high_pct is None:
        return None
    # Prezzo è sopra OR high (price_vs_or_high_pct < 0 significa price > or_high)
    if float(ind.price_vs_or_high_pct) > -_OR_BREAKOUT_CONFIRM_PCT:
        return None
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < 0.40:
        return None
    if ctx.volatility_regime == "low":
        return None
    vol_bonus = 0.08 if ctx.volatility_regime == "high" else 0.0
    strength = min(1.0, 0.58 + 0.15 * br + vol_bonus)
    strength = _cvd_strength_adjust(strength, ind, "bullish")
    return (strength, "bullish")


def _detect_opening_range_breakout_bear(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Breakout ribassista dell'Opening Range: speculare."""
    if ind is None:
        return None
    if ind.opening_range_low is None or ind.price_vs_or_low_pct is None:
        return None
    # Prezzo è sotto OR low (price_vs_or_low_pct < 0 significa price < or_low)
    if float(ind.price_vs_or_low_pct) > -_OR_BREAKOUT_CONFIRM_PCT:
        return None
    if feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < 0.40:
        return None
    if ctx.volatility_regime == "low":
        return None
    vol_bonus = 0.08 if ctx.volatility_regime == "high" else 0.0
    strength = min(1.0, 0.58 + 0.15 * br + vol_bonus)
    strength = _cvd_strength_adjust(strength, ind, "bearish")
    return (strength, "bearish")


def _detect_fibonacci_bounce(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """
    Rimbalzo da livello Fibonacci (38.2%, 50%, 61.8%).
    Prezzo tocca uno dei livelli Fibonacci e rimbalza nella direzione del trend.
    Usare il livello più vicino tra i tre.
    """
    if ind is None:
        return None

    # Trovare il livello Fibonacci più vicino
    fib_dists: list[tuple[float, str]] = []
    for d, name in [
        (ind.dist_to_fib_382_pct, "382"),
        (ind.dist_to_fib_500_pct, "500"),
        (ind.dist_to_fib_618_pct, "618"),
    ]:
        if d is not None:
            fib_dists.append((float(d), name))

    if not fib_dists:
        return None

    min_dist, _ = min(fib_dists, key=lambda x: x[0])
    if min_dist > _FIB_PROXIMITY_PCT:
        return None

    br = _body_ratio(feat)
    if br < 0.35:
        return None

    cp = _f(feat.close_position_in_range)

    # Direzione: se siamo in trend bullish e tocchiamo fib, rimbalzo bullish
    if ctx.direction_bias == "bullish" and feat.is_bullish and cp >= 0.52:
        if ctx.volatility_regime == "low":
            return None
        fib_bonus = 0.618 - min_dist / _FIB_PROXIMITY_PCT * 0.618
        strength = min(1.0, 0.52 + 0.15 * br + fib_bonus * 0.10)
        return (strength, "bullish")

    if ctx.direction_bias == "bearish" and not feat.is_bullish and cp <= 0.48:
        if ctx.volatility_regime == "low":
            return None
        fib_bonus = 0.618 - min_dist / _FIB_PROXIMITY_PCT * 0.618
        strength = min(1.0, 0.52 + 0.15 * br + fib_bonus * 0.10)
        return (strength, "bearish")

    return None


def _detect_fvg_retest_bull(
    feat: CandleFeature,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Retest rialzista in zona FVG bullish (indicatori)."""
    if ind is None or not ind.in_fvg_bullish:
        return None
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _FVG_RETEST_MIN_BODY_RATIO:
        return None
    cp = _f(feat.close_position_in_range)
    if cp < _FVG_RETEST_BULL_MIN_CP:
        return None
    strength = min(1.0, 0.42 * br + 0.48 * cp + 0.10)
    strength = _cvd_strength_adjust(strength, ind, "bullish")
    return (strength, "bullish")


def _detect_fvg_retest_bear(
    feat: CandleFeature,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Retest ribassista in zona FVG bearish (indicatori)."""
    if ind is None or not ind.in_fvg_bearish:
        return None
    if feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _FVG_RETEST_MIN_BODY_RATIO:
        return None
    cp = _f(feat.close_position_in_range)
    if cp > _FVG_RETEST_BEAR_MAX_CP:
        return None
    strength = min(1.0, 0.42 * br + 0.48 * (1.0 - cp) + 0.10)
    strength = _cvd_strength_adjust(strength, ind, "bearish")
    return (strength, "bearish")


def _detect_ob_retest_bull(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Retest rialzista in zona Order Block bullish."""
    if ind is None or not ind.in_ob_bullish:
        return None
    if not feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _OB_MIN_BODY_RATIO:
        return None
    cp = _f(feat.close_position_in_range)
    if cp < _OB_MIN_CP_BULL:
        return None
    if ctx.volatility_regime == "low":
        return None

    cvd_bonus = 0.0
    if ind.cvd_trend == "bullish":
        cvd_bonus = 0.08
    elif ind.cvd_trend == "bearish":
        cvd_bonus = -0.06

    ob_s = float(ind.ob_strength) if ind.ob_strength is not None else 0.5
    ob_bonus = (ob_s - 0.5) * 0.1

    strength = min(1.0, 0.60 + 0.15 * br + cvd_bonus + ob_bonus)
    return (strength, "bullish")


def _detect_ob_retest_bear(
    feat: CandleFeature,
    ctx: CandleContext,
    ind: CandleIndicator | None,
) -> tuple[float, str] | None:
    """Retest ribassista in zona Order Block bearish."""
    if ind is None or not ind.in_ob_bearish:
        return None
    if feat.is_bullish:
        return None
    br = _body_ratio(feat)
    if br < _OB_MIN_BODY_RATIO:
        return None
    cp = _f(feat.close_position_in_range)
    if cp > _OB_MAX_CP_BEAR:
        return None
    if ctx.volatility_regime == "low":
        return None

    cvd_bonus = 0.0
    if ind.cvd_trend == "bearish":
        cvd_bonus = 0.08
    elif ind.cvd_trend == "bullish":
        cvd_bonus = -0.06

    ob_s = float(ind.ob_strength) if ind.ob_strength is not None else 0.5
    ob_bonus = (ob_s - 0.5) * 0.1

    strength = min(1.0, 0.60 + 0.15 * br + cvd_bonus + ob_bonus)
    return (strength, "bearish")


def _run_detectors(
    feat: CandleFeature,
    ctx: CandleContext,
    prev_ctx: CandleContext | None,
    prev_features: list[CandleFeature] | None = None,
    ind: CandleIndicator | None = None,
    prev_indicators: list[CandleIndicator] | None = None,
) -> list[tuple[str, float, str]]:
    """Return list of (pattern_name, strength, direction) for this bar."""
    out: list[tuple[str, float, str]] = []

    r = _detect_impulsive_bullish(feat, ctx)
    if r:
        out.append(("impulsive_bullish_candle", r[0], r[1]))

    r = _detect_impulsive_bearish(feat, ctx)
    if r:
        out.append(("impulsive_bearish_candle", r[0], r[1]))

    r = _detect_range_expansion_breakout_candidate(feat, ctx)
    if r:
        out.append(("range_expansion_breakout_candidate", r[0], r[1]))

    r = _detect_compression_to_expansion_transition(feat, ctx, prev_ctx, ind)
    if r:
        out.append(("compression_to_expansion_transition", r[0], r[1]))

    r = _detect_trend_continuation_pullback(feat, ctx, prev_features or [])
    if r:
        out.append(("trend_continuation_pullback", r[0], r[1]))

    r = _detect_ema_pullback_to_support(feat, ctx, ind)
    if r:
        out.append(("ema_pullback_to_support", r[0], r[1]))

    r = _detect_ema_pullback_to_resistance(feat, ctx, ind)
    if r:
        out.append(("ema_pullback_to_resistance", r[0], r[1]))

    r = _detect_rsi_momentum_continuation(feat, ctx, ind, prev_indicators or [])
    if r:
        out.append(("rsi_momentum_continuation", r[0], r[1]))

    # Pattern multi-candela classici
    r = _detect_engulfing_bullish(feat, ctx, prev_features or [], ind)
    if r:
        out.append(("engulfing_bullish", r[0], r[1]))

    r = _detect_engulfing_bearish(feat, ctx, prev_features or [], ind)
    if r:
        out.append(("engulfing_bearish", r[0], r[1]))

    r = _detect_hammer_reversal(feat, ctx, ind)
    if r:
        out.append(("hammer_reversal", r[0], r[1]))

    r = _detect_shooting_star_reversal(feat, ctx, ind)
    if r:
        out.append(("shooting_star_reversal", r[0], r[1]))

    r = _detect_morning_star(feat, ctx, prev_features or [])
    if r:
        out.append(("morning_star", r[0], r[1]))

    r = _detect_evening_star(feat, ctx, prev_features or [])
    if r:
        out.append(("evening_star", r[0], r[1]))

    r = _detect_bull_flag(feat, ctx, prev_features or [])
    if r:
        out.append(("bull_flag", r[0], r[1]))

    r = _detect_bear_flag(feat, ctx, prev_features or [])
    if r:
        out.append(("bear_flag", r[0], r[1]))

    r = _detect_inside_bar_breakout_bull(feat, ctx, prev_features or [])
    if r:
        out.append(("inside_bar_breakout_bull", r[0], r[1]))

    r = _detect_support_bounce(feat, ctx, ind, prev_features or [])
    if r:
        out.append(("support_bounce", r[0], r[1]))

    r = _detect_resistance_rejection(feat, ctx, ind, prev_features or [])
    if r:
        out.append(("resistance_rejection", r[0], r[1]))

    r = _detect_breakout_with_retest(feat, ctx, ind, prev_features or [])
    if r:
        out.append(("breakout_with_retest", r[0], r[1]))

    # VWAP, Opening Range, Fibonacci
    r = _detect_vwap_bounce_bull(feat, ctx, ind)
    if r:
        out.append(("vwap_bounce_bull", r[0], r[1]))

    r = _detect_vwap_bounce_bear(feat, ctx, ind)
    if r:
        out.append(("vwap_bounce_bear", r[0], r[1]))

    r = _detect_opening_range_breakout_bull(feat, ctx, ind)
    if r:
        out.append(("opening_range_breakout_bull", r[0], r[1]))

    r = _detect_opening_range_breakout_bear(feat, ctx, ind)
    if r:
        out.append(("opening_range_breakout_bear", r[0], r[1]))

    r = _detect_fibonacci_bounce(feat, ctx, ind)
    if r:
        out.append(("fibonacci_bounce", r[0], r[1]))

    r = _detect_fvg_retest_bull(feat, ind)
    if r:
        out.append(("fvg_retest_bull", r[0], r[1]))

    r = _detect_fvg_retest_bear(feat, ind)
    if r:
        out.append(("fvg_retest_bear", r[0], r[1]))

    r = _detect_ob_retest_bull(feat, ctx, ind)
    if r:
        out.append(("ob_retest_bull", r[0], r[1]))

    r = _detect_ob_retest_bear(feat, ctx, ind)
    if r:
        out.append(("ob_retest_bear", r[0], r[1]))

    return out


async def _distinct_series(
    session: AsyncSession,
    *,
    exchange: str | None,
    provider: str | None,
    symbol: str | None,
    timeframe: str | None,
) -> list[tuple[str, str, str]]:
    stmt = select(CandleFeature.exchange, CandleFeature.symbol, CandleFeature.timeframe).distinct()
    conditions = []
    if exchange is not None:
        conditions.append(CandleFeature.exchange == exchange)
    if provider is not None:
        conditions.append(CandleFeature.provider == provider)
    if symbol is not None:
        conditions.append(CandleFeature.symbol == symbol)
    if timeframe is not None:
        conditions.append(CandleFeature.timeframe == timeframe)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.order_by(CandleFeature.exchange, CandleFeature.symbol, CandleFeature.timeframe)
    result = await session.execute(stmt)
    return [(r[0], r[1], r[2]) for r in result.all()]


async def extract_patterns(
    session: AsyncSession,
    request: PatternExtractRequest,
) -> PatternExtractResponse:
    series = await _distinct_series(
        session,
        exchange=request.exchange,
        provider=request.provider,
        symbol=request.symbol,
        timeframe=request.timeframe,
    )

    rows_to_upsert: list[dict[str, Any]] = []
    rows_read = 0
    patterns_detected = 0
    features_skipped_no_context = 0

    for ex, sym, tf in series:
        stmt_feats = (
            select(CandleFeature)
            .where(
                CandleFeature.exchange == ex,
                CandleFeature.symbol == sym,
                CandleFeature.timeframe == tf,
            )
            .order_by(CandleFeature.timestamp.asc())
            .limit(request.limit)
        )
        result_f = await session.execute(stmt_feats)
        features = list(result_f.scalars().all())
        if not features:
            continue

        ids = [f.id for f in features]
        stmt_ctx = select(CandleContext).where(CandleContext.candle_feature_id.in_(ids))
        result_c = await session.execute(stmt_ctx)
        ctx_by_feature_id: dict[int, CandleContext] = {
            c.candle_feature_id: c for c in result_c.scalars().all()
        }

        candle_ids = [f.candle_id for f in features]
        stmt_ind = select(CandleIndicator).where(CandleIndicator.candle_id.in_(candle_ids))
        result_ind = await session.execute(stmt_ind)
        ind_by_candle_id: dict[int, CandleIndicator] = {
            ind.candle_id: ind for ind in result_ind.scalars().all()
        }

        prev_ctx: CandleContext | None = None
        seen_features: list[CandleFeature] = []
        seen_indicators: list[CandleIndicator] = []
        for feat in features:
            ctx = ctx_by_feature_id.get(feat.id)
            ind = ind_by_candle_id.get(feat.candle_id)

            if ctx is None:
                features_skipped_no_context += 1
                seen_features.append(feat)
                if ind is not None:
                    seen_indicators.append(ind)
                continue

            rows_read += 1
            prev_feats = seen_features[-_PREV_FEATURES_LOOKBACK:]
            prev_inds = seen_indicators[-5:]
            detected = _run_detectors(
                feat,
                ctx,
                prev_ctx,
                prev_feats,
                ind,
                prev_inds,
            )
            prev_ctx = ctx
            seen_features.append(feat)
            if ind is not None:
                seen_indicators.append(ind)
            for pattern_name, strength, direction in detected:
                patterns_detected += 1
                rows_to_upsert.append(
                    {
                        "candle_feature_id": feat.id,
                        "candle_context_id": ctx.id,
                        "asset_type": feat.asset_type,
                        "provider": feat.provider,
                        "symbol": feat.symbol,
                        "exchange": feat.exchange,
                        "timeframe": feat.timeframe,
                        "market_metadata": feat.market_metadata,
                        "timestamp": feat.timestamp,
                        "pattern_name": pattern_name,
                        "pattern_strength": Decimal(str(round(strength, 8))),
                        "direction": direction,
                    }
                )

    if features_skipped_no_context > 0:
        logger.warning(
            "pattern extract: %s feature row(s) had no matching CandleContext (run context/extract first)",
            features_skipped_no_context,
        )

    if not rows_to_upsert:
        return PatternExtractResponse(
            series_processed=len(series),
            rows_read=rows_read,
            features_skipped_no_context=features_skipped_no_context,
            patterns_upserted=0,
            patterns_detected=patterns_detected,
        )

    patterns_upserted = await _chunked_upsert_patterns(session, rows_to_upsert)

    return PatternExtractResponse(
        series_processed=len(series),
        rows_read=rows_read,
        features_skipped_no_context=features_skipped_no_context,
        patterns_upserted=patterns_upserted,
        patterns_detected=patterns_detected,
    )
