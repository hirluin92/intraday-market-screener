#!/usr/bin/env python3
"""
15m Research Analysis Pipeline — Steps 1-6

READ-ONLY: connects to production DB but never writes.
All outputs go to research/datasets/*.csv

Usage (from repo root):
    python research/analyze_15m.py

Requires: psycopg2-binary pandas numpy scipy tabulate pytz
"""
from __future__ import annotations

import os
import sys
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

warnings.filterwarnings("ignore")

# ── Config ───────────────────────────────────────────────────────────────────
DB_DSN = os.environ.get(
    "RESEARCH_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/intraday_market_screener",
)
OUTPUT_DIR = Path(__file__).parent / "datasets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TZ_ET = ZoneInfo("America/New_York")

# Universe: 29 Alpaca 5m symbols
SYMBOLS = [
    "META","NVDA","TSLA","AMD","NFLX",
    "COIN","MSTR","HOOD","SHOP","SOFI",
    "ZS","NET","CELH","RBLX","PLTR",
    "MDB","SMCI","DELL",
    "NVO","LLY","MRNA","NKE","TGT","SCHW",
    "AMZN",
    "MU","LUNR","CAT","GS",
]

# Production constants (faithfully replicated)
COST_RATE       = 0.0015  # fee 0.001 + slippage 0.0005
RANGE_BELOW_SW  = 0.32    # stop buffer fraction of bar range
MIN_STOP_PCT    = 0.0012  # 0.12% of price (floor)
DEFAULT_TP1_R   = 1.5
DEFAULT_TP2_R   = 2.5

# Per-pattern SL/TP config (from trade_plan_engine.py PATTERN_SL_TP_CONFIG)
PATTERN_CONFIG: dict[str, tuple[float, float, float]] = {
    "macd_divergence_bull":   (1.25, 2.0, 3.5),
    "rsi_divergence_bear":    (0.90, 2.0, 3.5),
    "double_top":             (0.75, 1.8, 3.5),
    "double_bottom":          (1.00, 2.0, 3.5),
    "rsi_divergence_bull":    (1.25, 1.8, 3.5),
    "macd_divergence_bear":   (0.75, 2.0, 3.5),
    "engulfing_bullish":      (0.60, 2.0, 3.5),
}

MAX_BARS_ENTRY  = 4   # 15m: up to 4 bars (1h) to fill entry
MAX_BARS_HOLD   = 20  # 15m: max 20 bars (5h) holding
MIN_HOUR_ET     = 11  # same as 5m: no trades before 11 ET
SWING_WINDOW    = 5   # ±5 bars for swing high/low detection (same as production)

# Analysis
ALL_PATTERNS = [
    "double_bottom","double_top","engulfing_bullish",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
]

# ── DB helpers ────────────────────────────────────────────────────────────────

def connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(DB_DSN)

def read_candles(provider: str, timeframe: str, symbols: list[str] | None = None) -> pd.DataFrame:
    sym_filter = ""
    params: list = [provider, timeframe]
    if symbols:
        sym_filter = "AND symbol = ANY(%s)"
        params.append(symbols)
    sql = f"""
        SELECT symbol, timestamp, open, high, low, close, volume
        FROM candles
        WHERE provider = %s AND timeframe = %s {sym_filter}
        ORDER BY symbol, timestamp ASC
    """
    print(f"  Reading {provider}/{timeframe} candles from DB...")
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=cols)
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    print(f"  -> {len(df):,} rows, {df['symbol'].nunique()} symbols")
    return df

# ── STEP 1: Aggregate 5m → 15m ───────────────────────────────────────────────

def step1_aggregate() -> pd.DataFrame:
    print("\n" + "="*70)
    print("STEP 1 — Aggregate 5m → 15m")
    print("="*70)

    df5 = read_candles("alpaca", "5m", SYMBOLS)
    if df5.empty:
        print("ERROR: no 5m candles found. Check DB connection.")
        sys.exit(1)

    # Filter RTH (9:30–16:00 ET) — ensures clean 15m boundaries
    ts_et = df5["timestamp"].dt.tz_convert(TZ_ET)
    rth = (
        (ts_et.dt.weekday < 5) &
        (ts_et.dt.time >= pd.Timestamp("09:30").time()) &
        (ts_et.dt.time < pd.Timestamp("16:00").time())
    )
    df5 = df5[rth].copy()
    print(f"  After RTH filter: {len(df5):,} rows")

    # Floor to 15m boundary
    df5["ts_15m"] = df5["timestamp"].dt.floor("15min")

    # Aggregate: group by symbol + 15m bucket
    g = df5.groupby(["symbol", "ts_15m"])
    agg = g.agg(
        open  = ("open",   "first"),
        high  = ("high",   "max"),
        low   = ("low",    "min"),
        close = ("close",  "last"),
        volume= ("volume", "sum"),
        n_bars= ("open",   "count"),
    ).reset_index()

    # Keep only complete groups (exactly 3 × 5m bars)
    complete = agg[agg["n_bars"] == 3].copy()
    dropped  = len(agg) - len(complete)
    if dropped:
        print(f"  Dropped {dropped:,} partial 15m candles (incomplete groups)")

    complete = complete.rename(columns={"ts_15m": "timestamp"})
    complete["timeframe"] = "15m"
    complete["provider"]  = "alpaca"
    complete = complete.drop(columns=["n_bars"])
    complete = complete.sort_values(["symbol","timestamp"]).reset_index(drop=True)

    # Stats
    n5  = len(df5)
    n15 = len(complete)
    ratio = n5 / n15 if n15 else 0
    print(f"  5m candles   : {n5:,}")
    print(f"  15m candles  : {n15:,}  (ratio: {ratio:.2f}×, expected ~3)")
    print(f"  Symbols      : {complete['symbol'].nunique()}")
    if not complete.empty:
        print(f"  Period       : {complete['timestamp'].min().date()} → {complete['timestamp'].max().date()}")

    out = OUTPUT_DIR / "candles_15m_aggregated.csv"
    complete.to_csv(out, index=False)
    print(f"  Saved: {out}")
    return complete

# ── Indicators ────────────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1/n, adjust=False).mean()
    avg_l = loss.ewm(alpha=1/n, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_c).abs(),
        (low  - prev_c).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def _swing_high(high: pd.Series, w: int = 5) -> pd.Series:
    """True where bar is local high over ±w bars."""
    return high == high.rolling(2*w+1, center=True).max()

def _swing_low(low: pd.Series, w: int = 5) -> pd.Series:
    """True where bar is local low over ±w bars."""
    return low == low.rolling(2*w+1, center=True).min()

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-symbol indicators. Returns df with added columns."""
    dfs = []
    for sym, g in df.groupby("symbol"):
        g = g.copy().sort_values("timestamp").reset_index(drop=True)
        g["ema9"]   = _ema(g["close"], 9)
        g["ema20"]  = _ema(g["close"], 20)
        g["ema50"]  = _ema(g["close"], 50)
        g["rsi14"]  = _rsi(g["close"], 14)
        g["atr14"]  = _atr(g["high"], g["low"], g["close"], 14)
        g["macd"]   = g["ema9"] - g["ema20"]  # proxy (production: ema9-ema20)
        g["vol_ma20"] = g["volume"].rolling(20).mean()
        g["vol_ratio"] = g["volume"] / g["vol_ma20"].replace(0, np.nan)

        # Features
        g["range"]   = g["high"] - g["low"]
        g["body"]    = (g["close"] - g["open"]).abs()
        g["body_ratio"] = g["body"] / g["range"].replace(0, np.nan)
        g["upper_wick"]  = g["high"] - g[["open","close"]].max(axis=1)
        g["lower_wick"]  = g[["open","close"]].min(axis=1) - g["low"]
        g["close_pos"]   = (g["close"] - g["low"]) / g["range"].replace(0, np.nan)
        g["is_bull"]  = g["close"] > g["open"]
        g["pct_ret"]  = g["close"].pct_change()
        g["vol_ratio_prev"] = g["volume"] / g["volume"].shift(1).replace(0, np.nan)

        # Swing detection
        g["is_swing_high"] = _swing_high(g["high"], SWING_WINDOW)
        g["is_swing_low"]  = _swing_low(g["low"],  SWING_WINDOW)

        # Last swing high/low price (for use in pattern detectors)
        # rolling: last swing low within 40 bars
        last_swing_low  = pd.Series(np.nan, index=g.index)
        last_swing_high = pd.Series(np.nan, index=g.index)
        for i in range(len(g)):
            window = g.iloc[max(0,i-40):i+1]
            sl = window[window["is_swing_low"]]["low"]
            if not sl.empty:
                last_swing_low.iloc[i] = sl.iloc[-1]
            sh = window[window["is_swing_high"]]["high"]
            if not sh.empty:
                last_swing_high.iloc[i] = sh.iloc[-1]
        g["last_swing_low"]  = last_swing_low
        g["last_swing_high"] = last_swing_high

        # Price position in 20-bar range (for double_top/bottom recovery check)
        g["price_pos_range"] = (g["close"] - g["low"].rolling(20).min()) / (
            (g["high"].rolling(20).max() - g["low"].rolling(20).min()).replace(0, np.nan)
        )

        dfs.append(g)

    return pd.concat(dfs, ignore_index=True).sort_values(["symbol","timestamp"])

# ── STEP 2: Pattern detection ─────────────────────────────────────────────────

def _detect_engulfing_bullish_row(row: pd.Series, prev: pd.Series) -> float | None:
    if not row["is_bull"] or prev["is_bull"]: return None
    if row["body_ratio"] < 0.50: return None
    if row["body"] < prev["body"] * 1.05: return None
    if row["atr14"] <= 0: return None  # skip low-vol (proxy for volatility_regime != low)
    strength = min(1.0, 0.55 + 0.20 * row["body_ratio"])
    return strength

def _detect_rsi_div_bull_row(row: pd.Series, prev_rows: pd.DataFrame) -> float | None:
    if not row["is_swing_low"]: return None
    if row["rsi14"] > 55: return None
    curr_sw = row["last_swing_low"]
    if pd.isna(curr_sw) or curr_sw <= 0: return None
    # Search previous swing low in last 30 bars
    candidates = prev_rows[prev_rows["is_swing_low"] & prev_rows["rsi14"].notna()].tail(30)
    if candidates.empty: return None
    prev_row = candidates.iloc[-1]
    prev_rsi  = prev_row["rsi14"]
    prev_sw   = prev_row["last_swing_low"] if not pd.isna(prev_row["last_swing_low"]) else prev_row["low"]
    if pd.isna(prev_sw) or prev_sw <= 0: return None
    price_diff_pct = (curr_sw - prev_sw) / prev_sw * 100
    rsi_diff = row["rsi14"] - prev_rsi
    if price_diff_pct > -0.3: return None   # price must have fallen
    if rsi_diff < 3.0: return None          # RSI must have risen
    rsi_bonus   = min(0.10, rsi_diff * 0.008)
    price_bonus = min(0.08, abs(price_diff_pct) * 0.015)
    vol_bonus   = min(0.08, (row["vol_ratio"]-1)*0.05) if row["vol_ratio"] > 1 else 0
    br = row["body_ratio"] if not pd.isna(row["body_ratio"]) else 0
    return min(1.0, 0.56 + 0.10*br + rsi_bonus + price_bonus + vol_bonus)

def _detect_rsi_div_bear_row(row: pd.Series, prev_rows: pd.DataFrame) -> float | None:
    if not row["is_swing_high"]: return None
    if row["rsi14"] < 45: return None
    curr_sw = row["last_swing_high"]
    if pd.isna(curr_sw) or curr_sw <= 0: return None
    candidates = prev_rows[prev_rows["is_swing_high"] & prev_rows["rsi14"].notna()].tail(30)
    if candidates.empty: return None
    prev_row = candidates.iloc[-1]
    prev_rsi = prev_row["rsi14"]
    prev_sw  = prev_row["last_swing_high"] if not pd.isna(prev_row["last_swing_high"]) else prev_row["high"]
    if pd.isna(prev_sw) or prev_sw <= 0: return None
    price_diff_pct = (curr_sw - prev_sw) / prev_sw * 100
    rsi_diff = prev_rsi - row["rsi14"]
    if price_diff_pct < 0.3: return None    # price must have risen
    if rsi_diff < 3.0: return None          # RSI must have fallen
    rsi_bonus   = min(0.10, rsi_diff * 0.008)
    price_bonus = min(0.08, price_diff_pct * 0.015)
    vol_bonus   = min(0.08, (row["vol_ratio"]-1)*0.05) if row["vol_ratio"] > 1 else 0
    br = row["body_ratio"] if not pd.isna(row["body_ratio"]) else 0
    return min(1.0, 0.56 + 0.10*br + rsi_bonus + price_bonus + vol_bonus)

def _detect_macd_div_bull_row(row: pd.Series, prev_rows: pd.DataFrame) -> float | None:
    if not row["is_swing_low"]: return None
    if not row["is_bull"]: return None
    if row["rsi14"] > 55: return None
    curr_macd = row["macd"]
    if pd.isna(curr_macd): return None
    candidates = prev_rows[prev_rows["is_swing_low"] & prev_rows["macd"].notna()].tail(30)
    if candidates.empty: return None
    prev_row  = candidates.iloc[-1]
    prev_macd = prev_row["macd"]
    macd_diff = curr_macd - prev_macd
    if macd_diff > 0.0002:
        br = row["body_ratio"] if not pd.isna(row["body_ratio"]) else 0
        rsi_bonus  = min(0.08, (55 - row["rsi14"]) * 0.003)
        macd_bonus = min(0.08, abs(macd_diff) * 50)
        return min(1.0, 0.53 + rsi_bonus + macd_bonus + 0.08*br)
    return None

def _detect_macd_div_bear_row(row: pd.Series, prev_rows: pd.DataFrame) -> float | None:
    if not row["is_swing_high"]: return None
    if row["is_bull"]: return None
    if row["rsi14"] < 45: return None
    curr_macd = row["macd"]
    if pd.isna(curr_macd): return None
    candidates = prev_rows[prev_rows["is_swing_high"] & prev_rows["macd"].notna()].tail(30)
    if candidates.empty: return None
    prev_row  = candidates.iloc[-1]
    prev_macd = prev_row["macd"]
    macd_diff = prev_macd - curr_macd
    if macd_diff > 0.0002:
        br = row["body_ratio"] if not pd.isna(row["body_ratio"]) else 0
        rsi_bonus  = min(0.08, (row["rsi14"] - 45) * 0.003)
        macd_bonus = min(0.08, abs(macd_diff) * 50)
        return min(1.0, 0.53 + rsi_bonus + macd_bonus + 0.08*br)
    return None

def _detect_double_bottom_row(row: pd.Series, prev_rows: pd.DataFrame) -> float | None:
    if not row["is_swing_low"]: return None
    if row["rsi14"] > 55: return None
    curr_sw = row["last_swing_low"]
    if pd.isna(curr_sw) or curr_sw <= 0: return None
    # Need: recovery (price_pos_range > 0.55) then prev swing low within 40 bars
    found_recovery = False
    found_first_low = False
    first_low_price = None
    first_low_vol   = None
    for i in range(len(prev_rows)-1, max(-1, len(prev_rows)-40), -1):
        prow = prev_rows.iloc[i]
        if not found_recovery:
            if not pd.isna(prow["price_pos_range"]) and prow["price_pos_range"] > 0.55:
                found_recovery = True
        elif not found_first_low:
            if prow["is_swing_low"] and not pd.isna(prow["last_swing_low"]):
                first_low_price = prow["last_swing_low"]
                first_low_vol   = prow["vol_ratio_prev"] if not pd.isna(prow["vol_ratio_prev"]) else None
                found_first_low = True
                break
    if not found_first_low or first_low_price is None or not found_recovery: return None
    price_diff_pct = abs(curr_sw - first_low_price) / first_low_price * 100
    if price_diff_pct > 2.0: return None
    br = row["body_ratio"] if not pd.isna(row["body_ratio"]) else 0
    if br < 0.35: return None
    curr_vol = row["vol_ratio_prev"] if not pd.isna(row["vol_ratio_prev"]) else 1.0
    vol_div_bonus = 0.08 if (first_low_vol is not None and curr_vol < first_low_vol * 0.85) else 0
    rsi_bonus = min(0.08, (50 - row["rsi14"]) * 0.003)
    price_match_bonus = max(0, 0.06 * (1 - price_diff_pct / 2.0))
    return min(1.0, 0.55 + vol_div_bonus + rsi_bonus + price_match_bonus + 0.08*br)

def _detect_double_top_row(row: pd.Series, prev_rows: pd.DataFrame) -> float | None:
    if not row["is_swing_high"]: return None
    if row["rsi14"] < 45: return None
    curr_sw = row["last_swing_high"]
    if pd.isna(curr_sw) or curr_sw <= 0: return None
    found_pullback = False
    found_first_high = False
    first_high_price = None
    first_high_vol   = None
    for i in range(len(prev_rows)-1, max(-1, len(prev_rows)-40), -1):
        prow = prev_rows.iloc[i]
        if not found_pullback:
            if not pd.isna(prow["price_pos_range"]) and prow["price_pos_range"] < 0.45:
                found_pullback = True
        elif not found_first_high:
            if prow["is_swing_high"] and not pd.isna(prow["last_swing_high"]):
                first_high_price = prow["last_swing_high"]
                first_high_vol   = prow["vol_ratio_prev"] if not pd.isna(prow["vol_ratio_prev"]) else None
                found_first_high = True
                break
    if not found_first_high or first_high_price is None or not found_pullback: return None
    price_diff_pct = abs(curr_sw - first_high_price) / first_high_price * 100
    if price_diff_pct > 2.0: return None
    br = row["body_ratio"] if not pd.isna(row["body_ratio"]) else 0
    if br < 0.35: return None
    curr_vol = row["vol_ratio_prev"] if not pd.isna(row["vol_ratio_prev"]) else 1.0
    vol_div_bonus = 0.08 if (first_high_vol is not None and curr_vol < first_high_vol * 0.85) else 0
    rsi_bonus = min(0.08, (row["rsi14"] - 50) * 0.003)
    price_match_bonus = max(0, 0.06 * (1 - price_diff_pct / 2.0))
    return min(1.0, 0.55 + vol_div_bonus + rsi_bonus + price_match_bonus + 0.08*br)


def detect_patterns_for_symbol(g: pd.DataFrame) -> list[dict]:
    """Run all 7 detectors on a single symbol's 15m DataFrame."""
    g = g.sort_values("timestamp").reset_index(drop=True)
    records = []
    lookback = 45  # max lookback needed

    for i in range(lookback, len(g)):
        row      = g.iloc[i]
        prev_row = g.iloc[i-1]
        prev_rows = g.iloc[max(0,i-lookback):i]

        # Hour ET filter (≥ 11 ET, same as 5m rule)
        ts_et = row["timestamp"].astimezone(TZ_ET)
        if ts_et.hour < MIN_HOUR_ET:
            continue
        # Skip bad rows
        if pd.isna(row["rsi14"]) or pd.isna(row["atr14"]):
            continue

        # 1. engulfing_bullish
        s = _detect_engulfing_bullish_row(row, prev_row)
        if s is not None and s >= 0.45:
            records.append({"symbol": row["symbol"], "timestamp": row["timestamp"],
                            "pattern_name": "engulfing_bullish", "strength": s, "direction": "bullish"})

        # 2. rsi_divergence_bull
        s = _detect_rsi_div_bull_row(row, prev_rows)
        if s is not None and s >= 0.45:
            records.append({"symbol": row["symbol"], "timestamp": row["timestamp"],
                            "pattern_name": "rsi_divergence_bull", "strength": s, "direction": "bullish"})

        # 3. rsi_divergence_bear
        s = _detect_rsi_div_bear_row(row, prev_rows)
        if s is not None and s >= 0.45:
            records.append({"symbol": row["symbol"], "timestamp": row["timestamp"],
                            "pattern_name": "rsi_divergence_bear", "strength": s, "direction": "bearish"})

        # 4. macd_divergence_bull
        s = _detect_macd_div_bull_row(row, prev_rows)
        if s is not None and s >= 0.45:
            records.append({"symbol": row["symbol"], "timestamp": row["timestamp"],
                            "pattern_name": "macd_divergence_bull", "strength": s, "direction": "bullish"})

        # 5. macd_divergence_bear
        s = _detect_macd_div_bear_row(row, prev_rows)
        if s is not None and s >= 0.45:
            records.append({"symbol": row["symbol"], "timestamp": row["timestamp"],
                            "pattern_name": "macd_divergence_bear", "strength": s, "direction": "bearish"})

        # 6. double_bottom
        s = _detect_double_bottom_row(row, prev_rows)
        if s is not None and s >= 0.45:
            records.append({"symbol": row["symbol"], "timestamp": row["timestamp"],
                            "pattern_name": "double_bottom", "strength": s, "direction": "bullish"})

        # 7. double_top
        s = _detect_double_top_row(row, prev_rows)
        if s is not None and s >= 0.45:
            records.append({"symbol": row["symbol"], "timestamp": row["timestamp"],
                            "pattern_name": "double_top", "strength": s, "direction": "bearish"})

    return records


def step2_detect_patterns(df15: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "="*70)
    print("STEP 2 — Compute indicators + detect patterns on 15m")
    print("="*70)

    print("  Computing indicators per symbol...")
    df15 = compute_indicators(df15)

    print("  Detecting patterns...")
    all_records = []
    symbols = df15["symbol"].unique()
    for sym in sorted(symbols):
        g = df15[df15["symbol"] == sym]
        recs = detect_patterns_for_symbol(g)
        all_records.extend(recs)
        if recs:
            print(f"    {sym}: {len(recs)} patterns")

    df_pat = pd.DataFrame(all_records)
    if df_pat.empty:
        print("  WARNING: no patterns detected")
        return pd.DataFrame()

    # Summary
    print(f"\n  Total patterns: {len(df_pat):,}")
    print(df_pat.groupby("pattern_name").size().to_string())

    out = OUTPUT_DIR / "patterns_15m.csv"
    df_pat.to_csv(out, index=False)
    print(f"\n  Saved: {out}")
    return df_pat, df15


# ── STEP 3: Trade simulation ──────────────────────────────────────────────────

def _compute_entry_stop_tp(row: pd.Series, direction: str, pattern_name: str):
    """Compute entry, stop, TP1, TP2 for a pattern bar."""
    sl_mult, tp1_r, tp2_r = PATTERN_CONFIG.get(pattern_name, (1.0, DEFAULT_TP1_R, DEFAULT_TP2_R))

    entry = float(row["close"])  # entry at close of pattern bar
    rng   = float(row["high"] - row["low"])
    price = entry

    # Stop buffer: max(RANGE_BELOW_SW * range, MIN_STOP_PCT * price)
    buffer = max(RANGE_BELOW_SW * rng, MIN_STOP_PCT * price) * sl_mult

    if direction == "bullish":
        stop  = float(row["low"])  - buffer
        risk  = abs(entry - stop)
        tp1   = entry + tp1_r * risk
        tp2   = entry + tp2_r * risk
    else:  # bearish
        stop  = float(row["high"]) + buffer
        risk  = abs(entry - stop)
        tp1   = entry - tp1_r * risk
        tp2   = entry - tp2_r * risk

    return entry, stop, tp1, tp2, risk


def _simulate_trade(
    entry_price: float,
    stop_price:  float,
    tp1_price:   float,
    tp2_price:   float,
    direction:   str,
    future_bars: pd.DataFrame,
    cost_rate:   float = COST_RATE,
) -> dict:
    """
    Simulate trade outcome on future_bars.
    Returns outcome, pnl_r, bars_to_entry, bars_to_exit.
    """
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return {"outcome": "no_entry", "pnl_r": np.nan, "bars_to_entry": np.nan, "bars_to_exit": np.nan, "entry_filled": False}

    cr = cost_rate * entry_price / risk  # cost in R units

    # Phase 1: find entry fill (entry_price touched)
    entry_filled = False
    entry_bar    = -1
    for k in range(min(MAX_BARS_ENTRY, len(future_bars))):
        bar = future_bars.iloc[k]
        lo, hi = float(bar["low"]), float(bar["high"])
        if direction == "bullish":
            if lo <= entry_price <= hi or hi >= entry_price:
                entry_filled = True
                entry_bar = k
                break
        else:
            if lo <= entry_price <= hi or lo <= entry_price:
                entry_filled = True
                entry_bar = k
                break

    if not entry_filled:
        return {"outcome": "no_entry", "pnl_r": np.nan, "bars_to_entry": entry_bar+1 if entry_bar>=0 else MAX_BARS_ENTRY, "bars_to_exit": np.nan, "entry_filled": False}

    # Phase 2: scan for stop/TP from entry bar
    for k in range(entry_bar, min(entry_bar + MAX_BARS_HOLD, len(future_bars))):
        bar = future_bars.iloc[k]
        lo, hi = float(bar["low"]), float(bar["high"])

        if direction == "bullish":
            # Stop triggers first (conservative: same bar)
            if lo <= stop_price:
                return {"outcome": "stop", "pnl_r": -1.0 - cr, "bars_to_entry": entry_bar+1, "bars_to_exit": k - entry_bar + 1, "entry_filled": True}
            if hi >= tp2_price:
                return {"outcome": "tp2", "pnl_r": (tp2_price - entry_price)/risk - cr, "bars_to_entry": entry_bar+1, "bars_to_exit": k - entry_bar + 1, "entry_filled": True}
            if hi >= tp1_price:
                return {"outcome": "tp1", "pnl_r": (tp1_price - entry_price)/risk - cr, "bars_to_entry": entry_bar+1, "bars_to_exit": k - entry_bar + 1, "entry_filled": True}
        else:
            if hi >= stop_price:
                return {"outcome": "stop", "pnl_r": -1.0 - cr, "bars_to_entry": entry_bar+1, "bars_to_exit": k - entry_bar + 1, "entry_filled": True}
            if lo <= tp2_price:
                return {"outcome": "tp2", "pnl_r": (entry_price - tp2_price)/risk - cr, "bars_to_entry": entry_bar+1, "bars_to_exit": k - entry_bar + 1, "entry_filled": True}
            if lo <= tp1_price:
                return {"outcome": "tp1", "pnl_r": (entry_price - tp1_price)/risk - cr, "bars_to_entry": entry_bar+1, "bars_to_exit": k - entry_bar + 1, "entry_filled": True}

    return {"outcome": "timeout", "pnl_r": -cr, "bars_to_entry": entry_bar+1, "bars_to_exit": MAX_BARS_HOLD, "entry_filled": True}


def _load_spy_regime() -> pd.Series:
    """Load SPY 1h Yahoo Finance → daily bullish/bearish regime via EMA50."""
    sql = """
        SELECT timestamp, close
        FROM candles
        WHERE provider='yahoo_finance' AND symbol='SPY' AND timeframe='1h'
        ORDER BY timestamp ASC
    """
    with connect() as conn:
        df = pd.read_sql(sql, conn, parse_dates=["timestamp"])
    if df.empty:
        print("  WARNING: SPY 1h not found, regime filter disabled")
        return pd.Series(dtype=str)

    df["close"] = df["close"].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["ema50"] = _ema(df["close"], 50)
    df["regime"] = np.where(df["close"] > df["ema50"], "bullish", "bearish")
    df["date_et"] = df["timestamp"].dt.tz_convert(TZ_ET).dt.date

    # Daily: last bar of day gives regime
    daily = df.groupby("date_et").last()["regime"]
    print(f"  SPY regime loaded: {len(daily)} days")
    return daily


def step3_simulate(df_pat: pd.DataFrame, df15: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "="*70)
    print("STEP 3 — Simulate trades → val_15m.csv")
    print("="*70)

    if df_pat.empty:
        print("  No patterns to simulate.")
        return pd.DataFrame()

    spy_regime = _load_spy_regime()

    # Build per-symbol index for fast future-bar lookup
    sym_dfs = {sym: g.sort_values("timestamp").reset_index(drop=True)
               for sym, g in df15.groupby("symbol")}

    rows = []
    total = len(df_pat)
    print(f"  Simulating {total:,} pattern trades...")

    for idx, pat in df_pat.iterrows():
        sym       = pat["symbol"]
        ts        = pat["timestamp"]
        pattern   = pat["pattern_name"]
        direction = pat["direction"]
        strength  = pat["strength"]

        if sym not in sym_dfs:
            continue

        gdf = sym_dfs[sym]
        pat_idx = gdf.index[gdf["timestamp"] == ts]
        if len(pat_idx) == 0:
            continue
        pat_i = pat_idx[0]
        pattern_row = gdf.iloc[pat_i]

        # Regime filter (apply same as production: only allow aligned trades)
        ts_et = ts.astimezone(TZ_ET)
        trade_date = ts_et.date()
        regime = spy_regime.get(trade_date, "unknown")
        regime_ok = (
            (direction == "bullish" and regime == "bullish") or
            (direction == "bearish" and regime == "bearish") or
            regime == "unknown"
        )

        # Compute levels
        entry, stop, tp1, tp2, risk = _compute_entry_stop_tp(pattern_row, direction, pattern)
        risk_pct = (risk / entry * 100) if entry > 0 else np.nan

        # Simulate on future bars
        future = gdf.iloc[pat_i+1 : pat_i+1+MAX_BARS_ENTRY+MAX_BARS_HOLD].copy()
        sim = _simulate_trade(entry, stop, tp1, tp2, direction, future)

        rows.append({
            "symbol":          sym,
            "timeframe":       "15m",
            "provider":        "alpaca",
            "exchange":        "ALPACA_US",
            "pattern_name":    pattern,
            "direction":       direction,
            "pattern_timestamp": ts,
            "entry_price":     round(entry, 4),
            "stop_price":      round(stop,  4),
            "tp1_price":       round(tp1,   4),
            "tp2_price":       round(tp2,   4),
            "risk_pct":        round(risk_pct, 4) if not pd.isna(risk_pct) else np.nan,
            "pattern_strength": round(strength, 4),
            "regime_spy":      regime,
            "regime_ok":       regime_ok,
            "hour_et":         ts_et.hour,
            "date_et":         str(trade_date),
            "year":            ts_et.year,
            **sim,
        })

    df_val = pd.DataFrame(rows)
    print(f"  Total trades simulated   : {len(df_val):,}")
    if not df_val.empty:
        filled = df_val[df_val["entry_filled"] == True]
        print(f"  Entry filled             : {len(filled):,} ({len(filled)/len(df_val)*100:.1f}%)")

        out = OUTPUT_DIR / "val_15m.csv"
        df_val.to_csv(out, index=False)
        print(f"  Saved: {out}")
    return df_val


# ── STEP 4: Analysis tables ───────────────────────────────────────────────────

def _print_table(title: str, df: pd.DataFrame):
    try:
        from tabulate import tabulate
        print(f"\n{'─'*70}")
        print(f"  {title}")
        print(f"{'─'*70}")
        print(tabulate(df, headers="keys", tablefmt="rounded_grid", floatfmt=".3f", showindex=False))
    except ImportError:
        print(f"\n── {title} ──")
        print(df.to_string(index=False))


def _filter_structural(df: pd.DataFrame) -> pd.DataFrame:
    """Apply structural filters identical to production:
    - entry_filled = True
    - hour_et >= 11
    - outcome not null / no_entry
    """
    d = df[
        (df["entry_filled"] == True) &
        (df["outcome"].notna()) &
        (~df["outcome"].isin(["no_entry"]))
    ].copy()
    return d


def _agg_stats(df: pd.DataFrame, group_col: str | list[str]) -> pd.DataFrame:
    cols = [group_col] if isinstance(group_col, str) else group_col
    agg = df.groupby(cols).agg(
        n       = ("pnl_r", "count"),
        avg_r   = ("pnl_r", "mean"),
        median_r= ("pnl_r", "median"),
        wr_pct  = ("pnl_r", lambda x: (x > 0).mean() * 100),
        tp1_pct = ("outcome", lambda x: (x == "tp1").mean() * 100),
        tp2_pct = ("outcome", lambda x: (x == "tp2").mean() * 100),
        stop_pct= ("outcome", lambda x: (x == "stop").mean() * 100),
    ).reset_index()
    agg["avg_r+slip"] = (agg["avg_r"] - COST_RATE).round(3)
    return agg.sort_values("avg_r+slip", ascending=False)


def step4_analysis(df_val: pd.DataFrame) -> None:
    print("\n" + "="*70)
    print("STEP 4 — Analysis tables (15m, structural filters applied)")
    print("="*70)

    if df_val.empty:
        print("  No data for analysis.")
        return

    df = _filter_structural(df_val)
    print(f"  Trades after structural filter: {len(df):,}")
    print(f"  (regime_ok filter NOT applied here — shown in Step 4e)")

    if len(df) < 30:
        print("  WARNING: too few trades for meaningful analysis (<30)")

    # ── 4a. Per anno ─────────────────────────────────────────────────────────
    tbl = _agg_stats(df, "year")[["year","n","avg_r+slip","wr_pct","tp1_pct","tp2_pct","stop_pct"]]
    _print_table("4a. Per ANNO", tbl)

    # ── 4b. Per pattern ──────────────────────────────────────────────────────
    tbl = _agg_stats(df, "pattern_name")[["pattern_name","n","avg_r+slip","wr_pct","tp1_pct","tp2_pct","stop_pct"]]
    _print_table("4b. Per PATTERN", tbl)

    # ── 4c. Per ora ET (slot 30 min) ─────────────────────────────────────────
    df["hour_slot"] = df["hour_et"].apply(lambda h: f"{h:02d}:00-{h:02d}:30")
    tbl = _agg_stats(df, "hour_slot")[["hour_slot","n","avg_r+slip","wr_pct"]]
    _print_table("4c. Per ORA ET", tbl)

    # ── 4d. Per simbolo ───────────────────────────────────────────────────────
    tbl = _agg_stats(df, "symbol")[["symbol","n","avg_r+slip","wr_pct"]]
    top5 = tbl.head(5)
    bot5 = tbl.tail(5)
    _print_table("4d. TOP 5 SIMBOLI", top5)
    _print_table("4d. BOT 5 SIMBOLI", bot5)

    # ── 4e. Per regime ────────────────────────────────────────────────────────
    tbl = _agg_stats(df, ["regime_spy","direction"])[["regime_spy","direction","n","avg_r+slip","wr_pct"]]
    _print_table("4e. Per REGIME × DIREZIONE", tbl)

    # Regime-aligned only
    df_aligned = df[df["regime_ok"] == True]
    print(f"\n  Regime-aligned trades: {len(df_aligned):,} ({len(df_aligned)/len(df)*100:.1f}%)")
    if len(df_aligned) >= 10:
        tbl2 = _agg_stats(df_aligned, "pattern_name")[["pattern_name","n","avg_r+slip","wr_pct"]]
        _print_table("4e. Pattern per REGIME ALLINEATO", tbl2)

    # ── 4f. Per risk_pct ─────────────────────────────────────────────────────
    df["risk_pct_bin"] = pd.cut(df["risk_pct"], bins=[0, 0.5, 1.0, 1.5, 2.5, 100],
                                 labels=["0-0.5%","0.5-1%","1-1.5%","1.5-2.5%",">2.5%"])
    tbl = _agg_stats(df, "risk_pct_bin")[["risk_pct_bin","n","avg_r+slip","wr_pct"]]
    _print_table("4f. Per RISK_PCT", tbl)

    # ── 4g. Confluenza ───────────────────────────────────────────────────────
    # Count simultaneous patterns on same symbol × timestamp
    ts_sym = df.groupby(["symbol","pattern_timestamp"])["pattern_name"].count().reset_index()
    ts_sym.columns = ["symbol","pattern_timestamp","confluence"]
    df2 = df.merge(ts_sym, on=["symbol","pattern_timestamp"], how="left")
    df2["confluence_label"] = df2["confluence"].clip(upper=3).map({1:"1",2:"2","3+":3}).fillna("1")
    df2["confluence_label"] = df2["confluence"].clip(upper=3).astype(int).astype(str)
    df2.loc[df2["confluence"] >= 3, "confluence_label"] = "3+"
    tbl = _agg_stats(df2, "confluence_label")[["confluence_label","n","avg_r+slip","wr_pct"]]
    _print_table("4g. CONFLUENZA (N pattern contemporanei)", tbl)

    # ── 4h. Strength ─────────────────────────────────────────────────────────
    df["strength_bin"] = pd.cut(df["pattern_strength"], bins=[0, 0.55, 0.65, 0.75, 0.85, 1.01],
                                 labels=["0.45-0.55","0.55-0.65","0.65-0.75","0.75-0.85","0.85+"])
    tbl = _agg_stats(df, "strength_bin")[["strength_bin","n","avg_r+slip","wr_pct"]]
    _print_table("4h. Per STRENGTH", tbl)

    # ── 4i. MFE/MAE distribuzione ─────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print("  4i. DISTRIBUZIONE PnL_R")
    print(f"{'─'*70}")
    pnl = df["pnl_r"].dropna()
    if len(pnl) >= 5:
        print(f"  n={len(pnl)}  mean={pnl.mean():.3f}R  median={pnl.median():.3f}R")
        print(f"  p10={pnl.quantile(0.10):.3f}R  p25={pnl.quantile(0.25):.3f}R  p75={pnl.quantile(0.75):.3f}R  p90={pnl.quantile(0.90):.3f}R")
        print(f"  min={pnl.min():.3f}R  max={pnl.max():.3f}R")
        print(f"  WR: {(pnl > 0).mean()*100:.1f}%")

    # ── 4j. TP ottimale ───────────────────────────────────────────────────────
    # Show what pnl_r would be if we used TP1 only vs TP2 only vs mixed
    print(f"\n{'─'*70}")
    print("  4j. TP OTTIMALE (per pattern)")
    print(f"{'─'*70}")
    tp_rows = []
    for pat in ALL_PATTERNS:
        sub = df[df["pattern_name"] == pat]
        if len(sub) < 5:
            continue
        # TP1 only: pnl = tp1_r - cost if reached TP1 or TP2, else -1 - cost
        cfg = PATTERN_CONFIG.get(pat, (1.0, DEFAULT_TP1_R, DEFAULT_TP2_R))
        tp1_r, tp2_r = cfg[1], cfg[2]
        tp1_only_pnl = sub["pnl_r"].apply(lambda r: (tp1_r - COST_RATE) if r >= (tp1_r - COST_RATE) else r)
        tp_rows.append({
            "pattern": pat,
            "n": len(sub),
            "avg_r_actual": round(sub["pnl_r"].mean(), 3),
            f"tp1({tp1_r}R)_ev": round(tp1_only_pnl.mean(), 3),
            "tp1_hit%": round((sub["outcome"].isin(["tp1","tp2"])).mean()*100, 1),
            "tp2_hit%": round((sub["outcome"] == "tp2").mean()*100, 1),
        })
    if tp_rows:
        tbl = pd.DataFrame(tp_rows)
        _print_table("TP OTTIMALE", tbl)


# ── STEP 5: Confronto 5m vs 15m vs 1h ────────────────────────────────────────

def step5_compare(df_val_15m: pd.DataFrame) -> None:
    print("\n" + "="*70)
    print("STEP 5 — Confronto 5m vs 15m vs 1h")
    print("="*70)

    df15 = _filter_structural(df_val_15m)

    # Try to load existing 5m and 1h validation datasets
    path_5m = OUTPUT_DIR / "val_5m_expanded.csv"
    path_1h = OUTPUT_DIR / "val_1h_expanded.csv"
    df5  = pd.read_csv(path_5m)  if path_5m.exists()  else pd.DataFrame()
    df1h = pd.read_csv(path_1h)  if path_1h.exists()  else pd.DataFrame()

    if not df5.empty:
        df5  = df5[df5["entry_filled"] == True].copy() if "entry_filled" in df5.columns else df5
        df5  = df5[~df5["outcome"].isin(["no_entry"])].copy() if "outcome" in df5.columns else df5
    if not df1h.empty:
        df1h = df1h[df1h["entry_filled"] == True].copy() if "entry_filled" in df1h.columns else df1h
        df1h = df1h[~df1h["outcome"].isin(["no_entry"])].copy() if "outcome" in df1h.columns else df1h

    def _summary(df: pd.DataFrame, label: str) -> dict:
        if df.empty:
            return {"timeframe": label, "n": "N/A", "avg_r": "N/A", "WR%": "N/A",
                    "tp1%": "N/A", "tp2%": "N/A", "stop%": "N/A"}
        pnl = df["pnl_r"].dropna()
        return {
            "timeframe": label,
            "n":      len(pnl),
            "avg_r":  round(pnl.mean(), 3),
            "WR%":    round((pnl > 0).mean() * 100, 1),
            "tp1%":   round((df["outcome"] == "tp1").mean() * 100, 1) if "outcome" in df else "N/A",
            "tp2%":   round((df["outcome"] == "tp2").mean() * 100, 1) if "outcome" in df else "N/A",
            "stop%":  round((df["outcome"] == "stop").mean() * 100, 1) if "outcome" in df else "N/A",
        }

    comparison = [_summary(df1h, "1h"), _summary(df15, "15m"), _summary(df5, "5m")]
    _print_table("CONFRONTO 1h vs 15m vs 5m", pd.DataFrame(comparison))

    # Best hours per timeframe
    for label, df in [("15m", df15), ("5m", df5)]:
        if df.empty or "hour_et" not in df.columns:
            continue
        best = (df.groupby("hour_et")["pnl_r"]
                .agg(n="count", avg_r="mean")
                .reset_index()
                .query("n >= 10")
                .sort_values("avg_r", ascending=False)
                .head(5))
        best["avg_r"] = best["avg_r"].round(3)
        if not best.empty:
            _print_table(f"ORI MIGLIORI ({label})", best)

    # Best patterns per timeframe
    for label, df in [("15m", df15), ("5m", df5)]:
        if df.empty or "pattern_name" not in df.columns:
            continue
        best = (df.groupby("pattern_name")["pnl_r"]
                .agg(n="count", avg_r="mean")
                .reset_index()
                .query("n >= 10")
                .sort_values("avg_r", ascending=False))
        best["avg_r"] = best["avg_r"].round(3)
        _print_table(f"PATTERN MIGLIORI ({label})", best)

    # ATR% comparison (5m vs 15m vs 1h by symbol)
    print("\n── ATR% per simbolo (media) ──────────────────────────────────────────")
    if not df15.empty and "symbol" in df15.columns:
        # ATR as % of price = risk_pct / RANGE_BELOW_SW (approximation)
        # Better: load candles and compute directly
        for sym in sorted(df15["symbol"].unique())[:10]:
            s15 = df15[df15["symbol"] == sym]["risk_pct"].mean() if "risk_pct" in df15.columns else np.nan
            s5  = df5[df5["symbol"] == sym]["risk_pct"].mean()  if (not df5.empty and "risk_pct" in df5.columns and "symbol" in df5.columns) else np.nan
            print(f"  {sym:8s}  5m_risk%={s5:.3f}  15m_risk%={s15:.3f}")


# ── STEP 6: Monte Carlo ───────────────────────────────────────────────────────

def _monte_carlo(
    pnl_series: np.ndarray,
    n_trades_year: int,
    n_sims: int = 5000,
    risk_pct: float = 0.01,
) -> dict:
    """Bootstrap Monte Carlo. Uses log-space compounding to avoid overflow.
    n_trades_year is capped at 500 (realistic with slot constraints).
    """
    if len(pnl_series) < 5:
        return {}
    # Cap: even if 19K patterns exist, at most ~500/year get through slots+filters
    n = min(n_trades_year, 500)
    rng = np.random.default_rng(42)
    # Pre-sample all at once: shape (n_sims, n)
    idx = rng.integers(0, len(pnl_series), size=(n_sims, n))
    samples = pnl_series[idx]  # (n_sims, n)
    # Log-space compounding: log(1 + r * risk_pct) per trade
    log_returns = np.log1p(np.clip(samples * risk_pct, -0.99, 5.0))
    total_log = log_returns.sum(axis=1)
    results_pct = (np.exp(total_log) - 1.0) * 100.0  # final % gain on capital
    return {
        "n_trades_year": n,
        "mean_return%":  round(float(np.mean(results_pct)), 1),
        "median_return%":round(float(np.median(results_pct)), 1),
        "p10_return%":   round(float(np.percentile(results_pct, 10)), 1),
        "p90_return%":   round(float(np.percentile(results_pct, 90)), 1),
        "pct_profitable":round(float((results_pct > 0).mean() * 100), 1),
    }


def step6_montecarlo(df_val_15m: pd.DataFrame) -> None:
    print("\n" + "="*70)
    print("STEP 6 -- Monte Carlo 1h + 5m + 15m combinato")
    print("="*70)

    # Build realistic 15m PnL: regime-aligned, non-engulfing (actual edge subset)
    df15_full = _filter_structural(df_val_15m)
    df15_edge = df15_full[
        (df15_full["pattern_name"] != "engulfing_bullish") &
        (df15_full["regime_ok"] == True)
    ]

    path_5m = OUTPUT_DIR / "val_5m_expanded.csv"
    path_1h = OUTPUT_DIR / "val_1h_expanded.csv"
    df5_raw  = pd.read_csv(path_5m)  if path_5m.exists()  else pd.DataFrame()
    df1h_raw = pd.read_csv(path_1h)  if path_1h.exists()  else pd.DataFrame()

    def _prep(d: pd.DataFrame) -> pd.DataFrame:
        if d.empty:
            return d
        if "entry_filled" in d.columns:
            d = d[d["entry_filled"].astype(str).str.lower().isin(["true", "1"])]
        if "outcome" in d.columns:
            d = d[~d["outcome"].isin(["no_entry", None, ""])]
        return d

    df5  = _prep(df5_raw)
    df1h = _prep(df1h_raw)

    def _date_range_years(df: pd.DataFrame) -> float:
        for col in ("pattern_timestamp", "entry_time", "timestamp"):
            if col in df.columns:
                ts = pd.to_datetime(df[col], errors="coerce").dropna()
                days = (ts.max() - ts.min()).days
                return max(days / 365.25, 0.01)
        return 3.0  # assume 3-year dataset

    # Realistic annual trade counts (slot-constrained: max 2 trades/day for 15m)
    TRADING_DAYS_YEAR = 252
    MAX_DAILY_15M = 2   # max 2 slots dedicated to 15m
    MAX_DAILY_5M  = 2   # current allocation
    MAX_DAILY_1H  = 3   # current allocation

    n_15m_raw    = int(len(df15_edge) / _date_range_years(df15_edge)) if not df15_edge.empty else 0
    n_15m_capped = min(n_15m_raw, MAX_DAILY_15M * TRADING_DAYS_YEAR)

    n_5m_raw     = int(len(df5) / _date_range_years(df5)) if not df5.empty else 0
    n_5m_capped  = min(n_5m_raw, MAX_DAILY_5M * TRADING_DAYS_YEAR)

    n_1h_raw     = int(len(df1h) / _date_range_years(df1h)) if not df1h.empty else 0
    n_1h_capped  = min(n_1h_raw, MAX_DAILY_1H * TRADING_DAYS_YEAR)

    print(f"\n  Trade counts per anno (capped):")
    print(f"    15m (edge subset): {n_15m_raw} raw -> {n_15m_capped} capped")
    print(f"    5m:  {n_5m_raw} raw -> {n_5m_capped} capped")
    print(f"    1h:  {n_1h_raw} raw -> {n_1h_capped} capped")

    # MC scenarios
    scenarios = []

    pnl1h  = df1h["pnl_r"].dropna().values  if (not df1h.empty  and "pnl_r" in df1h.columns)  else np.array([])
    pnl5m  = df5["pnl_r"].dropna().values   if (not df5.empty   and "pnl_r" in df5.columns)    else np.array([])
    pnl15m = df15_edge["pnl_r"].dropna().values if not df15_edge.empty else np.array([])
    pnl15m_all = df15_full["pnl_r"].dropna().values if not df15_full.empty else np.array([])

    if len(pnl1h) > 0:
        mc = _monte_carlo(pnl1h, n_1h_capped)
        if mc:
            scenarios.append({"scenario": "1h solo", **mc})

    if len(pnl5m) > 0:
        pnl_combo = np.concatenate([pnl1h, pnl5m]) if len(pnl1h) > 0 else pnl5m
        n_combo = n_1h_capped + n_5m_capped
        mc = _monte_carlo(pnl_combo, n_combo)
        if mc:
            scenarios.append({"scenario": "1h + 5m (corrente)", **mc})

    if len(pnl15m) > 0:
        pnl_all = np.concatenate([x for x in [pnl1h, pnl5m, pnl15m] if len(x) > 0])
        n_all   = n_1h_capped + n_5m_capped + n_15m_capped
        mc = _monte_carlo(pnl_all, n_all)
        if mc:
            scenarios.append({"scenario": "1h + 5m + 15m", **mc})

    # 15m solo (regime-aligned, no engulfing)
    if len(pnl15m) > 0:
        mc = _monte_carlo(pnl15m, n_15m_capped)
        if mc:
            scenarios.append({"scenario": "15m solo (edge)", **mc})

    # 15m solo unfiltered (for comparison)
    if len(pnl15m_all) > 0:
        n_all_capped = min(int(len(df15_full) / _date_range_years(df15_full)), 500)
        mc = _monte_carlo(pnl15m_all, n_all_capped)
        if mc:
            scenarios.append({"scenario": "15m solo (tutti pattern)", **mc})

    if scenarios:
        tbl = pd.DataFrame(scenarios)
        _print_table("MONTE CARLO -- Rendimento annuo su $100k capitale, risk 1%/trade", tbl)
        print("\n  Nota: bootstrap 5000 sim, log-space compounding, n capped a slot constraints.")
        print("  '15m edge' = no engulfing + regime allineato.")
        print("  p10/p90 = range in 8 simulazioni su 10.")
    else:
        print("  Dati insufficienti per Monte Carlo — servono i file val_1h/val_5m_expanded.csv")
        print("  15m solo:")
        if not df15.empty and "pnl_r" in df15.columns:
            pnl15m = df15["pnl_r"].dropna().values
            mc = _monte_carlo(pnl15m, n_15m)
            if mc:
                for k,v in mc.items():
                    print(f"    {k}: {v}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*70)
    print("  15m RESEARCH ANALYSIS -- READ-ONLY (production DB not modified)")
    print("="*70)

    # Step 1
    df15 = step1_aggregate()
    if df15.empty:
        print("ABORT: no 15m candles.")
        return

    # Step 2
    result2 = step2_detect_patterns(df15)
    if isinstance(result2, tuple):
        df_pat, df15_ind = result2
    else:
        print("ABORT: pattern detection failed.")
        return

    if df_pat.empty:
        print("ABORT: no patterns detected.")
        return

    # Step 3
    df_val = step3_simulate(df_pat, df15_ind)
    if df_val.empty:
        print("ABORT: no trades simulated.")
        return

    # Step 4
    step4_analysis(df_val)

    # Step 5
    step5_compare(df_val)

    # Step 6
    step6_montecarlo(df_val)

    print("\n" + "="*70)
    print("  ANALISI COMPLETATA")
    print(f"  Output: {OUTPUT_DIR}")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
