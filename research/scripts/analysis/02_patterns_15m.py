"""
Step 2 -- Calcola indicatori e rileva pattern sui dati 15m aggregati.
Legge: research/datasets/candles_15m_aggregated.csv
Scrive: research/datasets/patterns_15m.csv

I 7 pattern validati:
  1. double_bottom        bullish
  2. double_top           bearish
  3. engulfing_bullish    bullish
  4. rsi_divergence_bull  bullish
  5. rsi_divergence_bear  bearish
  6. macd_divergence_bull bullish
  7. macd_divergence_bear bearish

NON scrive nulla al DB di produzione.

Uso:
  cd backend
  python research/02_patterns_15m.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

INPUT  = Path(__file__).parent / "datasets" / "candles_15m_aggregated.csv"
OUTPUT = Path(__file__).parent / "datasets" / "patterns_15m.csv"

# -- Parametri indicatori -----------------------------------------------------
EMA_SHORT    = 9
EMA_MID      = 20
EMA_LONG     = 50
RSI_PERIOD   = 14
ATR_PERIOD   = 14
SWING_WINDOW = 2   # barre su ciascun lato per swing point (es. 2 -> finestra 5 barre)

# -- Parametri pattern --------------------------------------------------------
DBOT_LOOKBACK         = 40
DBOT_PRICE_TOL_PCT    = 2.0
DBOT_MIN_SEP          = 5
DBOT_RECENT_BARS      = 12

ENG_MIN_BODY_RATIO    = 0.50
ENG_ENGULF_FACTOR     = 1.05

RSIDIV_LOOKBACK       = 30
RSIDIV_RSI_DIFF_MIN   = 3.0
RSIDIV_PRICE_DIFF_MIN = 0.3
RSIDIV_BULL_RSI_MAX   = 55.0
RSIDIV_BEAR_RSI_MIN   = 45.0

MACDDIV_LOOKBACK      = 30
MACDDIV_HIST_DIFF_MIN = 0.00015
MACDDIV_PRICE_DIFF_MIN= 0.3


# -- Calcolo indicatori (vettorizzato) ----------------------------------------

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0.0)
    loss  = (-delta).clip(lower=0.0)
    avg_g = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift(1)).abs()
    lcp = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _swing_lows(low: pd.Series, window: int = 2) -> pd.Series:
    """Vettorizzato: True se il punto e' il minimo locale nella finestra centrata 2*window+1."""
    roll_min = low.rolling(window=2 * window + 1, center=True, min_periods=2 * window + 1).min()
    return (low == roll_min).fillna(False)


def _swing_highs(high: pd.Series, window: int = 2) -> pd.Series:
    """Vettorizzato: True se il punto e' il massimo locale nella finestra centrata 2*window+1."""
    roll_max = high.rolling(window=2 * window + 1, center=True, min_periods=2 * window + 1).max()
    return (high == roll_max).fillna(False)


def _vwap_session(df: pd.DataFrame) -> pd.Series:
    """VWAP reset ogni giorno di trading."""
    try:
        from zoneinfo import ZoneInfo
        tz_et = ZoneInfo("America/New_York")
    except Exception:
        tz_et = None

    tp  = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"]

    ts = df["timestamp"]
    if ts.dtype == "object":
        ts = pd.to_datetime(ts, utc=True)

    if tz_et:
        ts_et   = ts.dt.tz_convert(tz_et)
        session = ts_et.dt.date.astype(str)
    else:
        session = ts.dt.date.astype(str)

    cum_tp_vol = (tp * vol).groupby(session).cumsum()
    cum_vol    = vol.groupby(session).cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)

    df["ema9"]  = _ema(df["close"], EMA_SHORT)
    df["ema20"] = _ema(df["close"], EMA_MID)
    df["ema50"] = _ema(df["close"], EMA_LONG)
    df["rsi14"] = _rsi(df["close"], RSI_PERIOD)
    df["atr14"] = _atr(df, ATR_PERIOD)

    df["macd"]   = df["ema9"] - df["ema20"]
    df["signal"] = _ema(df["macd"], 9)
    df["hist"]   = df["macd"] - df["signal"]

    df["vwap"] = _vwap_session(df)

    # Vettorizzato: rolling min/max centrato invece di loop Python
    df["is_swing_low"]  = _swing_lows(df["low"],  SWING_WINDOW)
    df["is_swing_high"] = _swing_highs(df["high"], SWING_WINDOW)

    df["body"]       = (df["close"] - df["open"]).abs()
    df["range_size"] = df["high"] - df["low"]
    df["body_ratio"] = (df["body"] / df["range_size"].replace(0, np.nan)).fillna(0.0)
    df["close_pos"]  = ((df["close"] - df["low"]) / df["range_size"].replace(0, np.nan)).fillna(0.5)

    df["vol_sma20"]  = df["volume"].rolling(20, min_periods=5).mean()
    df["vol_ratio"]  = (df["volume"] / df["vol_sma20"].replace(0, np.nan)).fillna(1.0)

    return df


# -- Detector pattern (numpy arrays per accesso rapido) -----------------------

def detect_double_bottom(df: pd.DataFrame) -> list[dict]:
    n = len(df)
    low_arr   = df["low"].values
    high_arr  = df["high"].values
    close_arr = df["close"].values
    rsi_arr   = df["rsi14"].values
    ts_arr    = df["timestamp"].values
    sw_low    = df["is_swing_low"].values.astype(bool)
    sw_indices = np.where(sw_low)[0]  # precomputed once

    patterns = []

    for i in range(DBOT_LOOKBACK + SWING_WINDOW, n - SWING_WINDOW):
        lo = int(np.searchsorted(sw_indices, max(0, i - DBOT_LOOKBACK)))
        hi = int(np.searchsorted(sw_indices, i))
        sw_idx = sw_indices[lo:hi]

        if len(sw_idx) < 2:
            continue

        found = False
        for k in range(len(sw_idx) - 1, 0, -1):
            sl2_i = int(sw_idx[k])
            if i - sl2_i > DBOT_RECENT_BARS:
                break
            for m in range(k - 1, -1, -1):
                sl1_i = int(sw_idx[m])
                if sl2_i - sl1_i < DBOT_MIN_SEP:
                    continue

                sl1 = low_arr[sl1_i]
                sl2 = low_arr[sl2_i]

                price_diff = abs(sl1 - sl2) / min(sl1, sl2) * 100
                if price_diff > DBOT_PRICE_TOL_PCT:
                    continue

                neckline = high_arr[sl1_i : sl2_i + 1].max()

                if close_arr[i] <= neckline:
                    continue

                rsi1    = rsi_arr[sl1_i]
                rsi2    = rsi_arr[sl2_i]
                rsi_div = (not np.isnan(rsi1) and not np.isnan(rsi2) and rsi2 > rsi1 + 1.0)

                symmetry = 1.0 - price_diff / DBOT_PRICE_TOL_PCT
                depth    = min(1.0, (neckline - min(sl1, sl2)) / neckline * 100 / 3.0)
                strength = round(max(0.0, min(1.0,
                    0.40 + 0.25 * symmetry + 0.20 * (1.0 if rsi_div else 0.0) + 0.15 * depth)), 4)

                patterns.append({
                    "bar_index":        i,
                    "timestamp":        ts_arr[i],
                    "pattern_name":     "double_bottom",
                    "direction":        "bullish",
                    "pattern_strength": strength,
                    "entry_ref_price":  float(close_arr[i]),
                    "stop_ref_price":   float(min(sl1, sl2)),
                })
                found = True
                break
            if found:
                break

    return patterns


def detect_double_top(df: pd.DataFrame) -> list[dict]:
    n = len(df)
    low_arr    = df["low"].values
    high_arr   = df["high"].values
    close_arr  = df["close"].values
    rsi_arr    = df["rsi14"].values
    ts_arr     = df["timestamp"].values
    sw_high    = df["is_swing_high"].values.astype(bool)
    sw_indices = np.where(sw_high)[0]

    patterns = []

    for i in range(DBOT_LOOKBACK + SWING_WINDOW, n - SWING_WINDOW):
        lo = int(np.searchsorted(sw_indices, max(0, i - DBOT_LOOKBACK)))
        hi = int(np.searchsorted(sw_indices, i))
        sh_idx = sw_indices[lo:hi]

        if len(sh_idx) < 2:
            continue

        found = False
        for k in range(len(sh_idx) - 1, 0, -1):
            sh2_i = int(sh_idx[k])
            if i - sh2_i > DBOT_RECENT_BARS:
                break
            for m in range(k - 1, -1, -1):
                sh1_i = int(sh_idx[m])
                if sh2_i - sh1_i < DBOT_MIN_SEP:
                    continue

                sh1 = high_arr[sh1_i]
                sh2 = high_arr[sh2_i]

                price_diff = abs(sh1 - sh2) / max(sh1, sh2) * 100
                if price_diff > DBOT_PRICE_TOL_PCT:
                    continue

                neckline = low_arr[sh1_i : sh2_i + 1].min()

                if close_arr[i] >= neckline:
                    continue

                rsi1    = rsi_arr[sh1_i]
                rsi2    = rsi_arr[sh2_i]
                rsi_div = (not np.isnan(rsi1) and not np.isnan(rsi2) and rsi2 < rsi1 - 1.0)

                symmetry = 1.0 - price_diff / DBOT_PRICE_TOL_PCT
                depth    = min(1.0, (max(sh1, sh2) - neckline) / max(sh1, sh2) * 100 / 3.0)
                strength = round(max(0.0, min(1.0,
                    0.40 + 0.25 * symmetry + 0.20 * (1.0 if rsi_div else 0.0) + 0.15 * depth)), 4)

                patterns.append({
                    "bar_index":        i,
                    "timestamp":        ts_arr[i],
                    "pattern_name":     "double_top",
                    "direction":        "bearish",
                    "pattern_strength": strength,
                    "entry_ref_price":  float(close_arr[i]),
                    "stop_ref_price":   float(max(sh1, sh2)),
                })
                found = True
                break
            if found:
                break

    return patterns


def detect_engulfing_bullish(df: pd.DataFrame) -> list[dict]:
    n         = len(df)
    open_arr  = df["open"].values
    close_arr = df["close"].values
    low_arr   = df["low"].values
    ts_arr    = df["timestamp"].values
    br_arr    = df["body_ratio"].values
    vr_arr    = df["vol_ratio"].values

    patterns = []
    for i in range(1, n):
        po = open_arr[i - 1];  pc = close_arr[i - 1]
        co = open_arr[i];      cc = close_arr[i]

        if not (pc < po and cc > co):
            continue

        prev_body = po - pc
        curr_body = cc - co

        if prev_body <= 0 or curr_body <= 0:
            continue
        if not (co <= pc and cc >= po):
            continue
        if curr_body < ENG_ENGULF_FACTOR * prev_body:
            continue
        if br_arr[i] < ENG_MIN_BODY_RATIO:
            continue

        engulf_ratio = min(curr_body / prev_body, 3.0) / 3.0
        vr           = vr_arr[i]
        vol_bonus    = min(vr / 1.5, 1.0) * 0.15 if vr > 1.0 else 0.0
        strength     = round(max(0.0, min(1.0, 0.50 + 0.35 * engulf_ratio + vol_bonus)), 4)

        patterns.append({
            "bar_index":        i,
            "timestamp":        ts_arr[i],
            "pattern_name":     "engulfing_bullish",
            "direction":        "bullish",
            "pattern_strength": strength,
            "entry_ref_price":  float(cc),
            "stop_ref_price":   float(low_arr[i]),
        })

    return patterns


def detect_rsi_divergence_bull(df: pd.DataFrame) -> list[dict]:
    n         = len(df)
    low_arr   = df["low"].values
    close_arr = df["close"].values
    rsi_arr   = df["rsi14"].values
    ts_arr    = df["timestamp"].values
    sw_low    = df["is_swing_low"].values.astype(bool)
    sw_indices = np.where(sw_low)[0]

    patterns = []

    for i in range(RSIDIV_LOOKBACK + SWING_WINDOW, n - SWING_WINDOW):
        rsi_i = rsi_arr[i]
        if np.isnan(rsi_i) or rsi_i > RSIDIV_BULL_RSI_MAX:
            continue

        lo = int(np.searchsorted(sw_indices, max(0, i - RSIDIV_LOOKBACK)))
        hi = int(np.searchsorted(sw_indices, i - SWING_WINDOW))
        sw_idx = sw_indices[lo:hi]

        if len(sw_idx) < 2:
            continue

        sl2_i = int(sw_idx[-1])
        sl1_i = int(sw_idx[-2])

        sl1_price = low_arr[sl1_i]
        sl2_price = low_arr[sl2_i]
        sl1_rsi   = rsi_arr[sl1_i]
        sl2_rsi   = rsi_arr[sl2_i]

        if np.isnan(sl1_rsi) or np.isnan(sl2_rsi):
            continue

        price_diff_pct = (sl1_price - sl2_price) / sl1_price * 100
        rsi_diff       = sl2_rsi - sl1_rsi

        if price_diff_pct < RSIDIV_PRICE_DIFF_MIN:
            continue
        if rsi_diff < RSIDIV_RSI_DIFF_MIN:
            continue
        if i - sl2_i > 8:
            continue

        div_magnitude = min(rsi_diff / 20.0, 1.0)
        price_dep     = min(price_diff_pct / 3.0, 1.0)
        strength      = round(max(0.0, min(1.0, 0.45 + 0.35 * div_magnitude + 0.20 * price_dep)), 4)

        patterns.append({
            "bar_index":        i,
            "timestamp":        ts_arr[i],
            "pattern_name":     "rsi_divergence_bull",
            "direction":        "bullish",
            "pattern_strength": strength,
            "entry_ref_price":  float(close_arr[i]),
            "stop_ref_price":   float(sl2_price),
        })

    return patterns


def detect_rsi_divergence_bear(df: pd.DataFrame) -> list[dict]:
    n          = len(df)
    high_arr   = df["high"].values
    close_arr  = df["close"].values
    rsi_arr    = df["rsi14"].values
    ts_arr     = df["timestamp"].values
    sw_high    = df["is_swing_high"].values.astype(bool)
    sw_indices = np.where(sw_high)[0]

    patterns = []

    for i in range(RSIDIV_LOOKBACK + SWING_WINDOW, n - SWING_WINDOW):
        rsi_i = rsi_arr[i]
        if np.isnan(rsi_i) or rsi_i < RSIDIV_BEAR_RSI_MIN:
            continue

        lo = int(np.searchsorted(sw_indices, max(0, i - RSIDIV_LOOKBACK)))
        hi = int(np.searchsorted(sw_indices, i - SWING_WINDOW))
        sh_idx = sw_indices[lo:hi]

        if len(sh_idx) < 2:
            continue

        sh2_i = int(sh_idx[-1])
        sh1_i = int(sh_idx[-2])

        sh1_price = high_arr[sh1_i]
        sh2_price = high_arr[sh2_i]
        sh1_rsi   = rsi_arr[sh1_i]
        sh2_rsi   = rsi_arr[sh2_i]

        if np.isnan(sh1_rsi) or np.isnan(sh2_rsi):
            continue

        price_diff_pct = (sh2_price - sh1_price) / sh1_price * 100
        rsi_diff       = sh1_rsi - sh2_rsi

        if price_diff_pct < RSIDIV_PRICE_DIFF_MIN:
            continue
        if rsi_diff < RSIDIV_RSI_DIFF_MIN:
            continue
        if i - sh2_i > 8:
            continue

        div_magnitude = min(rsi_diff / 20.0, 1.0)
        price_dep     = min(price_diff_pct / 3.0, 1.0)
        strength      = round(max(0.0, min(1.0, 0.45 + 0.35 * div_magnitude + 0.20 * price_dep)), 4)

        patterns.append({
            "bar_index":        i,
            "timestamp":        ts_arr[i],
            "pattern_name":     "rsi_divergence_bear",
            "direction":        "bearish",
            "pattern_strength": strength,
            "entry_ref_price":  float(close_arr[i]),
            "stop_ref_price":   float(sh2_price),
        })

    return patterns


def detect_macd_divergence_bull(df: pd.DataFrame) -> list[dict]:
    n          = len(df)
    low_arr    = df["low"].values
    close_arr  = df["close"].values
    hist_arr   = df["hist"].values
    ts_arr     = df["timestamp"].values
    sw_low     = df["is_swing_low"].values.astype(bool)
    sw_indices = np.where(sw_low)[0]

    patterns = []

    for i in range(MACDDIV_LOOKBACK + SWING_WINDOW, n - SWING_WINDOW):
        h_i = hist_arr[i]
        if np.isnan(h_i) or h_i >= 0:
            continue

        lo = int(np.searchsorted(sw_indices, max(0, i - MACDDIV_LOOKBACK)))
        hi = int(np.searchsorted(sw_indices, i - SWING_WINDOW))
        sw_idx = sw_indices[lo:hi]

        if len(sw_idx) < 2:
            continue

        sl2_i = int(sw_idx[-1])
        sl1_i = int(sw_idx[-2])

        sl1_price = low_arr[sl1_i]
        sl2_price = low_arr[sl2_i]
        sl1_hist  = hist_arr[sl1_i]
        sl2_hist  = hist_arr[sl2_i]

        if np.isnan(sl1_hist) or np.isnan(sl2_hist):
            continue

        price_diff_pct = (sl1_price - sl2_price) / sl1_price * 100
        hist_diff      = sl2_hist - sl1_hist

        if price_diff_pct < MACDDIV_PRICE_DIFF_MIN:
            continue
        if hist_diff < MACDDIV_HIST_DIFF_MIN:
            continue
        if i - sl2_i > 8:
            continue

        hist_mag  = min(abs(hist_diff) / 0.005, 1.0)
        price_dep = min(price_diff_pct / 3.0, 1.0)
        strength  = round(max(0.0, min(1.0, 0.45 + 0.35 * hist_mag + 0.20 * price_dep)), 4)

        patterns.append({
            "bar_index":        i,
            "timestamp":        ts_arr[i],
            "pattern_name":     "macd_divergence_bull",
            "direction":        "bullish",
            "pattern_strength": strength,
            "entry_ref_price":  float(close_arr[i]),
            "stop_ref_price":   float(sl2_price),
        })

    return patterns


def detect_macd_divergence_bear(df: pd.DataFrame) -> list[dict]:
    n          = len(df)
    high_arr   = df["high"].values
    close_arr  = df["close"].values
    hist_arr   = df["hist"].values
    ts_arr     = df["timestamp"].values
    sw_high    = df["is_swing_high"].values.astype(bool)
    sw_indices = np.where(sw_high)[0]

    patterns = []

    for i in range(MACDDIV_LOOKBACK + SWING_WINDOW, n - SWING_WINDOW):
        h_i = hist_arr[i]
        if np.isnan(h_i) or h_i <= 0:
            continue

        lo = int(np.searchsorted(sw_indices, max(0, i - MACDDIV_LOOKBACK)))
        hi = int(np.searchsorted(sw_indices, i - SWING_WINDOW))
        sh_idx = sw_indices[lo:hi]

        if len(sh_idx) < 2:
            continue

        sh2_i = int(sh_idx[-1])
        sh1_i = int(sh_idx[-2])

        sh1_price = high_arr[sh1_i]
        sh2_price = high_arr[sh2_i]
        sh1_hist  = hist_arr[sh1_i]
        sh2_hist  = hist_arr[sh2_i]

        if np.isnan(sh1_hist) or np.isnan(sh2_hist):
            continue

        price_diff_pct = (sh2_price - sh1_price) / sh1_price * 100
        hist_diff      = sh1_hist - sh2_hist

        if price_diff_pct < MACDDIV_PRICE_DIFF_MIN:
            continue
        if hist_diff < MACDDIV_HIST_DIFF_MIN:
            continue
        if i - sh2_i > 8:
            continue

        hist_mag  = min(abs(hist_diff) / 0.005, 1.0)
        price_dep = min(price_diff_pct / 3.0, 1.0)
        strength  = round(max(0.0, min(1.0, 0.45 + 0.35 * hist_mag + 0.20 * price_dep)), 4)

        patterns.append({
            "bar_index":        i,
            "timestamp":        ts_arr[i],
            "pattern_name":     "macd_divergence_bear",
            "direction":        "bearish",
            "pattern_strength": strength,
            "entry_ref_price":  float(close_arr[i]),
            "stop_ref_price":   float(sh2_price),
        })

    return patterns


DETECTORS = [
    detect_double_bottom,
    detect_double_top,
    detect_engulfing_bullish,
    detect_rsi_divergence_bull,
    detect_rsi_divergence_bear,
    detect_macd_divergence_bull,
    detect_macd_divergence_bear,
]


def detect_all_patterns(df: pd.DataFrame) -> pd.DataFrame:
    all_pats = []
    for det in DETECTORS:
        pats = det(df)
        for p in pats:
            idx = p["bar_index"]
            row = df.iloc[idx]
            p.update({
                "symbol":    row["symbol"],
                "exchange":  row["exchange"],
                "provider":  row["provider"],
                "timeframe": "15m",
                "open":      row["open"],
                "high":      row["high"],
                "low":       row["low"],
                "close":     row["close"],
                "volume":    row["volume"],
                "ema9":      row["ema9"],
                "ema20":     row["ema20"],
                "ema50":     row["ema50"],
                "rsi14":     row["rsi14"],
                "atr14":     row["atr14"],
                "hist":      row["hist"],
                "vwap":      row["vwap"],
                "vol_ratio": row["vol_ratio"],
            })
        all_pats.extend(pats)

    if not all_pats:
        return pd.DataFrame()

    pat_df = pd.DataFrame(all_pats)
    pat_df = pat_df.drop(columns=["bar_index"])
    return pat_df


def main():
    print("=" * 60)
    print("STEP 2 -- Rilevamento pattern 15m (ottimizzato)")
    print("=" * 60)

    if not INPUT.exists():
        print(f"ERRORE: file non trovato: {INPUT}")
        print("Esegui prima: python research/01_aggregate_15m.py")
        sys.exit(1)

    t0 = time.time()
    print(f"Caricamento: {INPUT}")
    candles = pd.read_csv(INPUT, parse_dates=["timestamp"])
    candles["timestamp"] = pd.to_datetime(candles["timestamp"], utc=True)
    print(f"  Totale candele 15m: {len(candles):,}")
    symbols = sorted(candles["symbol"].unique())
    print(f"  Simboli: {len(symbols)}")
    print()

    all_patterns: list[pd.DataFrame] = []
    n_sym = len(symbols)

    for idx_s, sym in enumerate(symbols, 1):
        t_sym = time.time()
        sym_df = candles[candles["symbol"] == sym].copy()
        sym_df = sym_df.sort_values("timestamp").reset_index(drop=True)
        sym_df = compute_indicators(sym_df)

        pat_df = detect_all_patterns(sym_df)

        elapsed = time.time() - t_sym
        if pat_df.empty:
            print(f"  [{idx_s:2d}/{n_sym}] {sym:8s}: nessun pattern  ({elapsed:.1f}s)")
            continue

        counts  = pat_df["pattern_name"].value_counts()
        summary = "  ".join(f"{k}={v}" for k, v in counts.items())
        print(f"  [{idx_s:2d}/{n_sym}] {sym:8s}: {len(pat_df):4d} pattern  [{summary}]  ({elapsed:.1f}s)")
        all_patterns.append(pat_df)

    if not all_patterns:
        print("\nNessun pattern rilevato.")
        return

    result = pd.concat(all_patterns, ignore_index=True)
    result = result.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    total_elapsed = time.time() - t0
    print()
    print("-" * 60)
    print(f"  Totale pattern:  {len(result):,}")
    print(f"  Tempo totale:    {total_elapsed:.1f}s")
    print()
    print("  Per pattern_name:")
    for pname, cnt in result["pattern_name"].value_counts().items():
        pct = cnt / len(result) * 100
        print(f"    {pname:30s}: {cnt:5,}  ({pct:.1f}%)")

    print()
    print("  Per anno:")
    result["year"] = result["timestamp"].dt.year
    for yr, cnt in result.groupby("year").size().items():
        print(f"    {yr}: {cnt:,}")
    result.drop(columns=["year"], inplace=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False)
    print(f"\n  Salvato in: {OUTPUT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
