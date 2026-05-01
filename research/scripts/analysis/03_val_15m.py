"""
Step 3 — Costruisce il dataset di validazione 15m.
Simula entry/stop/TP per ogni pattern rilevato.
Aggiunge: MFE, MAE, volume_relative, SPY regime, slippage.
Applica filtro orario (>= 11 ET, come da policy 5m).

Legge:  research/datasets/patterns_15m.csv
        research/datasets/candles_15m_aggregated.csv
Scrive: research/datasets/val_15m.csv

NON scrive nulla al DB di produzione.

Uso:
  cd backend
  python research/03_val_15m.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

PATTERNS_PATH = Path(__file__).parent / "datasets" / "patterns_15m.csv"
CANDLES_PATH  = Path(__file__).parent / "datasets" / "candles_15m_aggregated.csv"
OUTPUT        = Path(__file__).parent / "datasets" / "val_15m.csv"

# -- Parametri simulazione ----------------------------------------------------
TP1_R               = 1.5    # TP1 in R-multipli
TP2_R               = 2.5    # TP2 in R-multipli
MAX_BARS_ENTRY_SCAN = 4      # max barre per trovare entry (= 60 min per 15m)
MAX_BARS_HOLDING    = 16     # max barre in posizione (= 4 ore)
SLIPPAGE_RATE       = 0.0015 # round-trip 0.15% (stesso di produzione)
MIN_HOUR_ET         = 11     # filtra apertura (9:30-11 ET rumorosa, come 5m)
MIN_ATR_MULT        = 0.5    # stop minimo come multiplo dell'ATR
MAX_ATR_MULT        = 3.0    # stop massimo come multiplo dell'ATR

# Simboli bloccati per Alpaca 5m (stesso set del sistema in produzione)
SYMBOLS_BLOCKED = frozenset({"SPY", "AAPL", "MSFT", "GOOGL", "WMT", "DELL"})


def _tz_et():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        return None


TZ_ET = _tz_et()


def hour_et(ts: pd.Timestamp) -> int:
    """Ora in Eastern Time dalla timestamp UTC."""
    if TZ_ET:
        return ts.tz_convert(TZ_ET).hour
    # Fallback: approssima UTC-4 (EDT estivo)
    return (ts.hour - 4) % 24


def build_candle_index(candles_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Dict: symbol -> DataFrame candele ordinate per timestamp."""
    result = {}
    for sym, g in candles_df.groupby("symbol"):
        result[sym] = g.sort_values("timestamp").reset_index(drop=True)
    return result


def compute_spy_regime(candles_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcola il regime SPY a ogni timestamp 15m:
      bull   = EMA20 > EMA50
      bear   = EMA20 < EMA50
      neutral = altrimenti
    Restituisce DataFrame con colonne [timestamp, spy_regime].
    """
    spy = candles_df[candles_df["symbol"] == "SPY"].sort_values("timestamp").copy()
    if spy.empty:
        return pd.DataFrame(columns=["timestamp", "spy_regime"])

    spy["ema20"] = spy["close"].ewm(span=20, adjust=False).mean()
    spy["ema50"] = spy["close"].ewm(span=50, adjust=False).mean()

    def _regime(row):
        if pd.isna(row["ema20"]) or pd.isna(row["ema50"]):
            return "neutral"
        if row["ema20"] > row["ema50"]:
            return "bull"
        if row["ema20"] < row["ema50"]:
            return "bear"
        return "neutral"

    spy["spy_regime"] = spy.apply(_regime, axis=1)
    return spy[["timestamp", "spy_regime"]].copy()


def simulate_trade(
    pat_row: pd.Series,
    candles: pd.DataFrame,
) -> dict:
    """
    Simula un singolo trade da un pattern 15m.

    Logica:
    - Entry = open della barra SUCCESSIVA al pattern (market order)
    - Stop = derivato dalla logica del pattern (entry_ref e stop_ref)
    - TP1  = entry + TP1_R × risk  (bullish) o entry - TP1_R × risk (bearish)
    - TP2  = entry + TP2_R × risk  (bullish) o entry - TP2_R × risk (bearish)
    - Scansione: fino a MAX_BARS_HOLDING barre dall'entry
    - Outcome: tp2 > tp1 > stop > timeout

    MFE/MAE calcolati durante la vita del trade.
    """
    ts   = pat_row["timestamp"]
    direction = pat_row["direction"]

    # Trova la posizione del pattern nel DataFrame delle candele
    idx_arr = candles.index[candles["timestamp"] == ts].tolist()
    if not idx_arr:
        return _no_entry()

    pat_pos = idx_arr[0]  # posizione nel DataFrame (0-based dopo reset_index)

    # Entry = open della barra successiva
    entry_pos = pat_pos + 1
    if entry_pos >= len(candles):
        return _no_entry()

    entry_bar = candles.iloc[entry_pos]
    entry_px  = float(entry_bar["open"])
    if entry_px <= 0:
        return _no_entry()

    # Stop loss dalla struttura del pattern
    atr = float(pat_row.get("atr14", np.nan) or 0.0)
    nat_stop = float(pat_row.get("stop_ref_price", np.nan) or 0.0)

    if direction == "bullish":
        nat_risk = entry_px - nat_stop
        # Clamp: min ATR*0.5, max ATR*3.0
        if atr > 0:
            nat_risk = max(nat_risk, atr * MIN_ATR_MULT)
            nat_risk = min(nat_risk, atr * MAX_ATR_MULT)
        nat_risk = max(nat_risk, entry_px * 0.003)  # min 0.3%
        stop_px  = entry_px - nat_risk
    else:
        nat_risk = nat_stop - entry_px
        if atr > 0:
            nat_risk = max(nat_risk, atr * MIN_ATR_MULT)
            nat_risk = min(nat_risk, atr * MAX_ATR_MULT)
        nat_risk = max(nat_risk, entry_px * 0.003)
        stop_px  = entry_px + nat_risk

    risk    = abs(entry_px - stop_px)
    if risk < 1e-9:
        return _no_entry()

    risk_pct = risk / entry_px * 100.0

    if direction == "bullish":
        tp1_px = entry_px + TP1_R * risk
        tp2_px = entry_px + TP2_R * risk
    else:
        tp1_px = entry_px - TP1_R * risk
        tp2_px = entry_px - TP2_R * risk

    # Scansione barre in avanti
    outcome       = "timeout"
    pnl_r         = 0.0
    bars_to_exit  = MAX_BARS_HOLDING
    mfe_r         = 0.0
    mae_r         = 0.0
    bars_to_mfe   = 0

    scan_end = min(entry_pos + 1 + MAX_BARS_HOLDING, len(candles))
    trade_bars = candles.iloc[entry_pos + 1 : scan_end]

    best_r = 0.0  # MFE tracker
    worst_r = 0.0  # MAE tracker

    for bar_offset, (_, bar) in enumerate(trade_bars.iterrows()):
        h = float(bar["high"])
        l = float(bar["low"])

        if direction == "bullish":
            current_best  = (h - entry_px) / risk
            current_worst = (entry_px - l) / risk
            hit_stop = l <= stop_px
            hit_tp1  = h >= tp1_px
            hit_tp2  = h >= tp2_px
        else:
            current_best  = (entry_px - l) / risk
            current_worst = (h - entry_px) / risk
            hit_stop = h >= stop_px
            hit_tp1  = l <= tp1_px
            hit_tp2  = l <= tp2_px

        if current_best > best_r:
            best_r    = current_best
            bars_to_mfe = bar_offset
        if current_worst > worst_r:
            worst_r = current_worst

        if hit_stop and hit_tp2:
            # Ambiguo: chi prima? Assumiamo stop
            outcome      = "stop"
            pnl_r        = -1.0
            bars_to_exit = bar_offset + 1
            break
        elif hit_tp2:
            outcome      = "tp2"
            pnl_r        = TP2_R
            bars_to_exit = bar_offset + 1
            break
        elif hit_tp1:
            outcome      = "tp1"
            pnl_r        = TP1_R
            bars_to_exit = bar_offset + 1
            break
        elif hit_stop:
            outcome      = "stop"
            pnl_r        = -1.0
            bars_to_exit = bar_offset + 1
            break

    mfe_r = round(max(0.0, best_r), 4)
    mae_r = round(max(0.0, worst_r), 4)

    # Slippage round-trip: 0.15% del valore posizione / risk per share
    slippage_r = (SLIPPAGE_RATE * entry_px) / risk
    pnl_r_slip = round(pnl_r - slippage_r, 4)
    pnl_r      = round(pnl_r, 4)

    return {
        "entry_filled":  True,
        "entry_price":   round(entry_px, 6),
        "stop_price":    round(stop_px, 6),
        "tp1_price":     round(tp1_px, 6),
        "tp2_price":     round(tp2_px, 6),
        "risk_pct":      round(risk_pct, 4),
        "outcome":       outcome,
        "pnl_r":         pnl_r,
        "pnl_r_slip":    pnl_r_slip,
        "bars_to_entry": 1,
        "bars_to_exit":  bars_to_exit,
        "mfe_r":         mfe_r,
        "mae_r":         mae_r,
        "bars_to_mfe":   bars_to_mfe,
    }


def _no_entry() -> dict:
    return {
        "entry_filled":  False,
        "entry_price":   None,
        "stop_price":    None,
        "tp1_price":     None,
        "tp2_price":     None,
        "risk_pct":      None,
        "outcome":       "no_entry",
        "pnl_r":         0.0,
        "pnl_r_slip":    0.0,
        "bars_to_entry": None,
        "bars_to_exit":  None,
        "mfe_r":         None,
        "mae_r":         None,
        "bars_to_mfe":   None,
    }


def main():
    print("=" * 60)
    print("STEP 3 — Simulazione trade 15m")
    print("=" * 60)

    for p in [PATTERNS_PATH, CANDLES_PATH]:
        if not p.exists():
            print(f"ERRORE: file non trovato: {p}")
            sys.exit(1)

    print(f"Caricamento pattern: {PATTERNS_PATH}")
    patterns = pd.read_csv(PATTERNS_PATH, parse_dates=["timestamp"])
    patterns["timestamp"] = pd.to_datetime(patterns["timestamp"], utc=True)
    print(f"  Pattern totali: {len(patterns):,}")

    print(f"Caricamento candele: {CANDLES_PATH}")
    candles_all = pd.read_csv(CANDLES_PATH, parse_dates=["timestamp"])
    candles_all["timestamp"] = pd.to_datetime(candles_all["timestamp"], utc=True)

    # Indice candele per simbolo
    candle_idx = build_candle_index(candles_all)

    # Regime SPY
    print("Calcolo regime SPY...")
    spy_regime_df = compute_spy_regime(candles_all)
    spy_regime_map = dict(zip(spy_regime_df["timestamp"], spy_regime_df["spy_regime"]))

    # Filtro orario
    patterns["hour_et"] = patterns["timestamp"].apply(hour_et)
    mask_hour = patterns["hour_et"] >= MIN_HOUR_ET
    print(f"  Pattern dopo filtro ora ET >= {MIN_HOUR_ET}: {mask_hour.sum():,} / {len(patterns):,}")
    patterns = patterns[mask_hour].copy()

    # Calcola confluenza (n° pattern diversi sullo stesso simbolo e timestamp)
    conf = (
        patterns.groupby(["symbol", "timestamp"])["pattern_name"]
        .nunique()
        .rename("confluence")
        .reset_index()
    )
    patterns = patterns.merge(conf, on=["symbol", "timestamp"], how="left")

    records = []
    skipped = 0

    for _, pat in patterns.iterrows():
        sym = pat["symbol"]
        candles = candle_idx.get(sym)
        if candles is None or candles.empty:
            skipped += 1
            continue

        sim = simulate_trade(pat, candles)

        # Volume relativo alla media 20 barre della serie
        ts = pat["timestamp"]
        vol_rel = float(pat.get("vol_ratio", np.nan) or np.nan)

        # Regime SPY al timestamp più vicino
        spy_reg = spy_regime_map.get(ts, "neutral")

        records.append({
            "symbol":           sym,
            "exchange":         pat.get("exchange", ""),
            "provider":         pat.get("provider", "alpaca"),
            "timeframe":        "15m",
            "timestamp":        ts.isoformat(),
            "year":             ts.year,
            "hour_et":          pat["hour_et"],
            "pattern_name":     pat["pattern_name"],
            "direction":        pat["direction"],
            "pattern_strength": pat.get("pattern_strength", 0.0),
            "confluence":       pat.get("confluence", 1),
            "rsi14":            round(float(pat.get("rsi14", np.nan) or np.nan), 2)
                                if pd.notna(pat.get("rsi14")) else None,
            "atr14":            round(float(pat.get("atr14", np.nan) or np.nan), 6)
                                if pd.notna(pat.get("atr14")) else None,
            "vol_ratio":        round(vol_rel, 4) if pd.notna(vol_rel) else None,
            "spy_regime":       spy_reg,
            "is_blocked":       sym in SYMBOLS_BLOCKED,
            **sim,
        })

    print(f"\n  Simulazioni: {len(records):,}  (skip: {skipped})")

    val = pd.DataFrame(records)

    # Statistiche summary
    filled = val[val["entry_filled"] == True]
    n_filled = len(filled)
    if n_filled > 0:
        wr = (filled["pnl_r"] > 0).mean() * 100
        avg_r = filled["pnl_r"].mean()
        avg_r_slip = filled["pnl_r_slip"].mean()
        print(f"  Entry fill rate:   {n_filled / len(val) * 100:.1f}%")
        print(f"  Win rate (filled): {wr:.1f}%")
        print(f"  Avg R:             {avg_r:.4f}R")
        print(f"  Avg R + slippage:  {avg_r_slip:.4f}R")

        print("\n  Outcome distribution:")
        for oc, cnt in filled["outcome"].value_counts().items():
            print(f"    {oc:10s}: {cnt:5,}  ({cnt/n_filled*100:.1f}%)")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    val.to_csv(OUTPUT, index=False)
    print(f"\n  Salvato in: {OUTPUT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
