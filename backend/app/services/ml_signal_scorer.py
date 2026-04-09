"""
ML Signal Scorer — integrazione modello LightGBM nel live screener.

Carica un modello addestrato da ``analyze_and_train.py`` (joblib .pkl) e produce
un ``ml_score`` (probabilità 0-1 che tp1_hit=1) per ogni segnale in arrivo.

Configurazione (.env / Settings):
  ML_MODEL_PATH = path assoluto o relativo al file .pkl
                  Se vuoto (default) il scorer è disabilitato (no-op).
  ML_MIN_SCORE  = soglia minima (0.0-1.0) per mantenere decisione "execute".
                  0.0 = solo annotazione, nessun filtro aggiuntivo (default).

Il modello è completamente opzionale e non-breaking:
  - ML_MODEL_PATH vuoto  → ml_score = None, sistema invariato.
  - File non trovato     → warning al primo call, ml_score = None.
  - Dipendenze assenti   → ml_score = None.

Encoding:
  Le feature categoriche vengono one-hot encoded con pd.get_dummies e poi
  riallineate alle feature_names del modello (colonne mancanti → 0, extra → drop).

Aggiornamento modello senza riavvio:
  Chiama ``reload_model()`` dopo aver sostituito il file .pkl su disco.
"""

from __future__ import annotations

import calendar as _calendar
import logging
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ─── Colonne categoriche (identiche ad analyze_and_train.py) ─────────────────
_CAT_COLS = frozenset({
    "direction", "timeframe", "symbol_group",
    "regime_spy", "ctx_market_regime", "ctx_volatility_regime",
    "ctx_candle_expansion", "ctx_direction_bias",
    "rs_signal", "cvd_trend", "session",
    "vix_regime",
})

# ─── FOMC dates 2022-2025 (stesse di build_trade_dataset.py) ─────────────────
_FOMC_DATES: list[date] = sorted([
    date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15), date(2022, 7, 27),
    date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14),
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
    date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13),
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
])

# ─── Symbol group hints (identici a build_trade_dataset.py) ──────────────────
_SYMBOL_HINTS: list[tuple[str, str]] = [
    ("GOOGL", "tech"), ("GOOG", "tech"), ("META", "tech"), ("AMZN", "tech"),
    ("MSFT", "tech"), ("AAPL", "tech"), ("NFLX", "tech"), ("SHOP", "tech"),
    ("DELL", "tech"), ("HPE", "tech"),
    ("NVDA", "semis"), ("AMD", "semis"), ("SMCI", "semis"),
    ("COIN", "crypto_fintech"), ("HOOD", "crypto_fintech"), ("SCHW", "broker"),
    ("MSTR", "crypto_proxy"),
    ("ZS", "saas"), ("NET", "saas"), ("MDB", "saas"), ("PLTR", "saas"),
    ("NVO", "biotech"), ("LLY", "biotech"), ("MRNA", "biotech"),
    ("RXRX", "biotech"), ("CELH", "biotech"),
    ("TSLA", "ev_mobility"),
    ("ACHR", "space_defense"), ("ASTS", "space_defense"),
    ("JOBY", "space_defense"), ("RKLB", "space_defense"),
    ("NNE", "nuclear_energy"), ("OKLO", "nuclear_energy"), ("SMR", "nuclear_energy"),
    ("WULF", "crypto_mining"), ("APLD", "crypto_mining"),
    ("NKE", "consumer"), ("TGT", "consumer"), ("WMT", "consumer"),
    ("NEM", "commodities"),
    ("RBLX", "gaming"), ("SOFI", "fintech"),
    ("SPY", "etf_index"), ("QQQ", "etf_index"), ("IWM", "etf_index"),
    ("BTC", "crypto"), ("ETH", "crypto"), ("SOL", "crypto"),
    ("WLD", "crypto"), ("DOGE", "crypto"), ("ADA", "crypto"), ("MATIC", "crypto"),
]

# ─── Singleton del modello (thread-safe) ─────────────────────────────────────
_lock = threading.Lock()
_model: Any | None = None
_model_features: list[str] | None = None
_model_loaded = False


# ─────────────────────────────────────────────────────────────────────────────
# API pubblica
# ─────────────────────────────────────────────────────────────────────────────

def reload_model() -> bool:
    """
    Forza il reload del modello dal disco.
    Utile dopo aggiornamento del .pkl senza riavviare il backend.
    Restituisce True se il caricamento ha avuto successo.
    """
    global _model, _model_features, _model_loaded
    with _lock:
        _model_loaded = False
        _model = None
        _model_features = None
    return _get_model() is not None


def is_enabled() -> bool:
    """True se il modello è configurato e caricato correttamente."""
    return _get_model() is not None


def score_signal(raw_feature_dict: dict[str, object]) -> float | None:
    """
    Calcola il ml_score per un vettore di feature (chiavi = colonne del dataset CSV).

    Gestisce internamente one-hot encoding e allineamento alle feature del modello.
    Restituisce probabilità 0-1 oppure None se il modello non è disponibile.
    """
    loaded = _get_model()
    if loaded is None:
        return None
    model, features = loaded
    try:
        import pandas as pd  # noqa: PLC0415

        df = pd.DataFrame([raw_feature_dict])

        cat_present = [c for c in _CAT_COLS if c in df.columns]
        if cat_present:
            df = pd.get_dummies(df, columns=list(cat_present), drop_first=False, dummy_na=True)

        # Converti object → numeric
        for c in df.columns:
            if df[c].dtype == object:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # Allinea alle feature del modello
        for f in features:
            if f not in df.columns:
                df[f] = 0.0
        df = df[features].fillna(0.0)

        return round(float(model.predict_proba(df)[0, 1]), 4)
    except Exception as exc:
        logger.debug("ml_signal_scorer.score_signal: %s", exc)
        return None


def build_signal_feature_dict(
    *,
    pat: Any,
    ind: Any | None,
    ctx: Any | None,
    candle: Any | None = None,
    regime_filter: Any | None = None,
    vix_history: dict[str, float] | None = None,
    earnings_cal: dict[str, list[date]] | None = None,
    n_open_positions: int = 0,
    capital_available_pct: float = 100.0,
    pq_score: float | None = None,
    stop_distance_pct: float | None = None,
    rr_tp1: float | None = None,
    rr_tp2: float | None = None,
) -> dict[str, object]:
    """
    Costruisce il dict di feature per l'inferenza live, allineato al dataset di training.

    Parametri opzionali (None = feature assente → fill 0 nel modello):
    - ``candle``           : Candle ORM per calcolo body/wick; None → None per queste feature.
    - ``vix_history``      : dict {YYYY-MM-DD: close} pre-caricato; None → vix_* = None.
    - ``earnings_cal``     : dict {SYMBOL: [date]} pre-caricato; None → earnings_* = None.
    - ``n_open_positions`` : posizioni attualmente aperte (0 = safe default).
    - ``capital_available_pct``: capitale disponibile % (100.0 = safe default).
    """
    def _f(x: object) -> float | None:
        if x is None:
            return None
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    # Normalizza timestamp in UTC
    ts: datetime = pat.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)

    d: date = ts.date()
    hour_utc = ts.hour
    mo = d.month
    last_day = _calendar.monthrange(d.year, mo)[1]
    week_of_year = int(d.isocalendar()[1])
    sess = "open" if hour_utc < 8 else ("midday" if hour_utc < 16 else "close")

    close_px = _f(getattr(candle, "close", None)) or 0.0

    # Regime
    regime_raw = "neutral"
    if regime_filter is not None and hasattr(regime_filter, "get_regime_label"):
        regime_raw = regime_filter.get_regime_label(ts)
    _rm = (regime_raw or "").lower()
    regime_spy = "bull" if _rm == "bullish" else ("bear" if _rm == "bearish" else "neutral")

    # Indicatori tecnici
    ema9 = _f(getattr(ind, "ema_9", None)) if ind else None
    ema9_pct = ((close_px - ema9) / ema9 * 100.0) if ema9 and ema9 != 0 else None
    atr = _f(getattr(ind, "atr_14", None)) if ind else None
    atr_pct = (atr / close_px * 100.0) if atr and close_px else None

    # Candle body/wick (disponibile solo se viene passato il Candle)
    body_pct, uw_pct, lw_pct = _candle_body_metrics(candle)

    # Tranche A: VIX
    vix_val: float | None = None
    vix_pct1y: float | None = None
    vix_reg: str | None = None
    if vix_history:
        import bisect  # noqa: PLC0415
        dates = sorted(vix_history.keys())
        target = ts.strftime("%Y-%m-%d")
        idx = bisect.bisect_right(dates, target) - 1
        if idx >= 0:
            found = dates[idx]
            if (datetime.fromisoformat(target) - datetime.fromisoformat(found)).days <= 5:
                vix_val = vix_history[found]
                if idx >= 30:
                    window = dates[max(0, idx - 252): idx + 1]
                    vals = [vix_history[x] for x in window]
                    vix_pct1y = round(sum(1 for v in vals if v <= vix_val) / len(vals), 4)
        if vix_val is not None:
            vix_reg = ("low" if vix_val < 15 else
                       "normal" if vix_val < 25 else
                       "elevated" if vix_val < 35 else "high")

    # Tranche A: Earnings
    days_to_earn: int | None = None
    days_from_earn: int | None = None
    in_earn_win = 0
    if earnings_cal is not None:
        sym = pat.symbol.upper().replace("/USDT", "").replace("/USD", "")
        earn_dates = earnings_cal.get(sym, [])
        if earn_dates:
            future = [x for x in earn_dates if x > d]
            past = [x for x in earn_dates if x <= d]
            days_to = (min(future) - d).days if future else None
            days_fr = (d - max(past)).days if past else None
            if days_to is not None and days_to > 90:
                days_to = None
            if days_fr is not None and days_fr > 90:
                days_fr = None
            days_to_earn = days_to
            days_from_earn = days_fr
            in_earn_win = int((days_to is not None and days_to <= 5) or
                              (days_fr is not None and days_fr <= 2))

    # Tranche A: FOMC
    fomc_future = [x for x in _FOMC_DATES if x >= d]
    fomc_delta = (fomc_future[0] - d).days if fomc_future else None
    fomc_d = fomc_delta if fomc_delta is not None and fomc_delta <= 60 else None

    # OpEx
    first = date(d.year, d.month, 1)
    first_fri = first + timedelta(days=(4 - first.weekday()) % 7)
    opex = first_fri + timedelta(weeks=2)
    is_opex = int(d.isocalendar()[1] == opex.isocalendar()[1])

    direction_norm = (
        "short"
        if (pat.direction or "").lower() in ("bearish", "short", "sell", "bear")
        else "long"
    )

    return {
        # Identificatori (non feature, solo per debug)
        "symbol": pat.symbol,
        "symbol_group": _symbol_group_for(pat.symbol),
        "provider": pat.provider,
        "pattern_name": pat.pattern_name,
        "direction": direction_norm,
        "timeframe": pat.timeframe,
        # Feature segnale
        "strength": _f(pat.pattern_strength),
        "quality_score": pq_score,
        "has_quality_score": int(pq_score is not None),
        # Regime
        "regime_spy": regime_spy,
        "ctx_market_regime": getattr(ctx, "market_regime", None) if ctx else None,
        "ctx_volatility_regime": getattr(ctx, "volatility_regime", None) if ctx else None,
        "ctx_candle_expansion": getattr(ctx, "candle_expansion", None) if ctx else None,
        "ctx_direction_bias": getattr(ctx, "direction_bias", None) if ctx else None,
        # Momentum
        "rs_vs_spy": _f(getattr(ind, "rs_vs_spy", None)) if ind else None,
        "rs_vs_spy_5": _f(getattr(ind, "rs_vs_spy_5", None)) if ind else None,
        "rs_signal": getattr(ind, "rs_signal", None) if ind else None,
        "rsi_14": _f(getattr(ind, "rsi_14", None)) if ind else None,
        "price_vs_ema9_pct": ema9_pct,
        "ema_20": _f(getattr(ind, "price_vs_ema20_pct", None)) if ind else None,
        "ema_50": _f(getattr(ind, "price_vs_ema50_pct", None)) if ind else None,
        # Volatilità
        "atr_14": atr,
        "atr_pct": atr_pct,
        # Volume
        "volume_ratio": _f(getattr(ind, "volume_ratio_vs_ma20", None)) if ind else None,
        "cvd_trend": getattr(ind, "cvd_trend", None) if ind else None,
        "cvd_normalized": _f(getattr(ind, "cvd_normalized", None)) if ind else None,
        # Prezzi chiave
        "price_vs_vwap_pct": _f(getattr(ind, "price_vs_vwap_pct", None)) if ind else None,
        "price_vs_or_high_pct": _f(getattr(ind, "price_vs_or_high_pct", None)) if ind else None,
        "price_vs_or_low_pct": _f(getattr(ind, "price_vs_or_low_pct", None)) if ind else None,
        # Struttura
        "dist_to_swing_high_pct": _f(getattr(ind, "dist_to_swing_high_pct", None)) if ind else None,
        "dist_to_swing_low_pct": _f(getattr(ind, "dist_to_swing_low_pct", None)) if ind else None,
        "price_position_in_range": _f(getattr(ind, "price_position_in_range", None)) if ind else None,
        "structural_range_pct": _f(getattr(ind, "structural_range_pct", None)) if ind else None,
        # Fibonacci
        "dist_to_fib_382_pct": _f(getattr(ind, "dist_to_fib_382_pct", None)) if ind else None,
        "dist_to_fib_500_pct": _f(getattr(ind, "dist_to_fib_500_pct", None)) if ind else None,
        "dist_to_fib_618_pct": _f(getattr(ind, "dist_to_fib_618_pct", None)) if ind else None,
        # FVG
        "in_fvg_bullish": int(bool(getattr(ind, "in_fvg_bullish", False))) if ind else None,
        "in_fvg_bearish": int(bool(getattr(ind, "in_fvg_bearish", False))) if ind else None,
        "dist_to_fvg_pct": _f(getattr(ind, "dist_to_fvg_pct", None)) if ind else None,
        # Order Block
        "in_ob_bullish": int(bool(getattr(ind, "in_ob_bullish", False))) if ind else None,
        "in_ob_bearish": int(bool(getattr(ind, "in_ob_bearish", False))) if ind else None,
        "dist_to_ob_pct": _f(getattr(ind, "dist_to_ob_pct", None)) if ind else None,
        "ob_strength": _f(getattr(ind, "ob_strength", None)) if ind else None,
        # Trade plan
        "stop_distance_pct": stop_distance_pct,
        "rr_tp1": rr_tp1,
        "rr_tp2": rr_tp2,
        # Candle body/wick
        "candle_body_pct": body_pct,
        "upper_wick_pct": uw_pct,
        "lower_wick_pct": lw_pct,
        # Temporali
        "hour_utc": hour_utc,
        "day_of_week": d.weekday(),
        "session": sess,
        "month_of_year": mo,
        "week_of_year": week_of_year,
        "is_opex_week": is_opex,
        "is_quarter_start": int(mo in (1, 4, 7, 10) and d.day <= 14),
        "is_quarter_end": int(mo in (3, 6, 9, 12) and d.day >= last_day - 13),
        # Macro (Tranche A)
        "vix_close": vix_val,
        "vix_percentile_1y": vix_pct1y,
        "vix_regime": vix_reg,
        "days_to_earnings": days_to_earn,
        "days_from_earnings": days_from_earn,
        "in_earnings_window": in_earn_win,
        "days_to_fomc": fomc_d,
        # Portfolio state
        "n_open_positions": n_open_positions,
        "capital_available_pct": capital_available_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Funzioni interne di supporto
# ─────────────────────────────────────────────────────────────────────────────

def _symbol_group_for(ticker: str) -> str:
    t = (ticker or "").upper().replace("/USDT", "").replace("/USD", "")
    for prefix, grp in _SYMBOL_HINTS:
        if t.startswith(prefix):
            return grp
    return "unknown"


def _candle_body_metrics(candle: Any | None) -> tuple[float | None, float | None, float | None]:
    if candle is None:
        return None, None, None
    try:
        hi = float(candle.high)
        lo = float(candle.low)
        op = float(candle.open)
        cl = float(candle.close)
        rng = hi - lo
        if rng <= 0:
            return None, None, None
        return (
            round(abs(cl - op) / rng, 6),
            round((hi - max(op, cl)) / rng, 6),
            round((min(op, cl) - lo) / rng, 6),
        )
    except Exception:
        return None, None, None


def _get_model() -> tuple[Any, list[str]] | None:
    global _model, _model_features, _model_loaded
    with _lock:
        if _model_loaded:
            return (_model, _model_features) if _model is not None else None
        _model_loaded = True

        try:
            from app.core.config import settings  # noqa: PLC0415
        except Exception:
            return None

        path_str: str = getattr(settings, "ml_model_path", "") or ""
        if not path_str.strip():
            return None

        from pathlib import Path  # noqa: PLC0415
        path = Path(path_str)
        if not path.exists():
            logger.warning("ml_signal_scorer: file non trovato: %s", path)
            return None

        try:
            import joblib  # noqa: PLC0415

            model = joblib.load(path)
            if hasattr(model, "feature_name_"):
                raw = model.feature_name_
                features = list(raw() if callable(raw) else raw)
            elif hasattr(model, "feature_names_in_"):
                features = list(model.feature_names_in_)
            else:
                logger.warning(
                    "ml_signal_scorer: modello senza feature names — scorer disabilitato"
                )
                return None

            _model = model
            _model_features = features
            logger.info(
                "ml_signal_scorer: modello caricato — %s (%d feature)",
                path.name,
                len(features),
            )
            return _model, _model_features
        except Exception as exc:
            logger.error("ml_signal_scorer: errore caricamento: %s", exc)
            return None
