"""
Step 4 — Analisi completa del dataset di validazione 15m.
Applica gli stessi filtri strutturali del sistema 5m in produzione:
  - entry_filled = True
  - not is_blocked (escludi simboli con EV negativo)
  - regime SPY applicato dove indicato

Stampa:
  4a. Per anno
  4b. Per pattern (tutti e 7)
  4c. Per ora ET (slot 30 min)
  4d. Per simbolo (top e bottom performer)
  4e. Per regime SPY
  4f. Per risk_pct (fasce)
  4g. Per confluenza (N pattern)
  4h. Per strength (fasce)
  4i. MFE/MAE distribuzione
  4j. TP ottimale + trailing stop da MFE

Legge: research/datasets/val_15m.csv

Uso:
  cd backend
  python research/04_analysis_15m.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

VAL_PATH = Path(__file__).parent / "datasets" / "val_15m.csv"

# --- helpers -----------------------------------------------------------------

def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 100.0
    p = wins / n
    center = (p + z**2 / (2*n)) / (1 + z**2/n)
    margin = z * ((p*(1-p)/n + z**2/(4*n**2))**0.5) / (1 + z**2/n)
    return round(max(0.0, center - margin)*100, 1), round(min(1.0, center + margin)*100, 1)


def table_row(label: str, subset: pd.DataFrame, col_r: str = "pnl_r_slip") -> str:
    n    = len(subset)
    if n == 0:
        return f"  {label:35s} {'—':>6} {'—':>7} {'—':>8} {'—':>15}"
    wins = (subset[col_r] > 0).sum()
    wr   = wins / n * 100
    avg  = subset[col_r].mean()
    lo, hi = _wilson_ci(int(wins), n)
    ci   = f"[{lo:.1f}%-{hi:.1f}%]"
    return f"  {label:35s} {n:>6,} {wr:>6.1f}% {avg:>+8.3f}R {ci:>15}"


def sep(width: int = 75) -> str:
    return "  " + "-" * width


def hdr(label: str, col_r: str = "pnl_r_slip") -> str:
    return (f"  {'Categoria':35s} {'n':>6} {'WR':>7} {'avg R+slip':>8} {'CI 95%':>15}\n"
            + sep())


# --- main --------------------------------------------------------------------

def main():
    print("=" * 75)
    print("STEP 4 — Analisi 15m — filtri strutturali applicati")
    print("=" * 75)

    if not VAL_PATH.exists():
        print(f"ERRORE: {VAL_PATH} non trovato. Esegui prima lo Step 3.")
        sys.exit(1)

    raw = pd.read_csv(VAL_PATH)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)

    total_raw = len(raw)
    filled = raw[raw["entry_filled"] == True].copy()
    n_filled = len(filled)

    print(f"\n  Record totali:     {total_raw:,}")
    print(f"  Entry filled:      {n_filled:,}  ({n_filled/total_raw*100:.1f}%)")

    # Filtro simboli bloccati
    df = filled[filled["is_blocked"] == False].copy()
    n_unblocked = len(df)
    print(f"  Dopo filtro block: {n_unblocked:,}  ({n_unblocked/n_filled*100:.1f}%)")

    # Statistiche base
    wr_glob   = (df["pnl_r_slip"] > 0).mean() * 100
    avg_r     = df["pnl_r"].mean()
    avg_r_slip = df["pnl_r_slip"].mean()
    lo, hi    = _wilson_ci(int((df["pnl_r_slip"] > 0).sum()), len(df))

    print(f"\n  Win rate globale:  {wr_glob:.1f}%  CI 95% [{lo}%-{hi}%]")
    print(f"  Avg R:             {avg_r:+.4f}R")
    print(f"  Avg R + slippage:  {avg_r_slip:+.4f}R")

    # -- 4a. Per anno ----------------------------------------------------------
    print(f"\n{'-'*75}")
    print("  4a. Per ANNO")
    print(hdr(""), end="")
    for yr in sorted(df["year"].dropna().unique()):
        sub = df[df["year"] == yr]
        print(table_row(str(int(yr)), sub))

    # -- 4b. Per pattern -------------------------------------------------------
    print(f"\n{'-'*75}")
    print("  4b. Per PATTERN")
    print(hdr(""), end="")
    patterns_ordered = [
        "double_bottom", "double_top", "engulfing_bullish",
        "rsi_divergence_bull", "rsi_divergence_bear",
        "macd_divergence_bull", "macd_divergence_bear",
    ]
    for pname in patterns_ordered:
        sub = df[df["pattern_name"] == pname]
        print(table_row(pname, sub))

    # -- 4c. Per ora ET (slot 30 min) ------------------------------------------
    print(f"\n{'-'*75}")
    print("  4c. Per ORA ET (slot 30 min)")
    print(hdr(""), end="")
    # Crea slot 30-min dal timestamp
    try:
        from zoneinfo import ZoneInfo
        tz_et = ZoneInfo("America/New_York")
        df["ts_et"] = df["timestamp"].dt.tz_convert(tz_et)
    except Exception:
        df["ts_et"] = df["timestamp"] - pd.Timedelta(hours=4)

    df["slot_30m"] = df["ts_et"].dt.hour * 60 + (df["ts_et"].dt.minute // 30) * 30
    df["slot_label"] = df["ts_et"].apply(
        lambda x: f"{x.hour:02d}:{(x.minute//30)*30:02d}"
    )
    for slot in sorted(df["slot_30m"].unique()):
        sub  = df[df["slot_30m"] == slot]
        lbl  = sub.iloc[0]["slot_label"] + " ET"
        print(table_row(lbl, sub))

    # -- 4d. Per simbolo --------------------------------------------------------
    print(f"\n{'-'*75}")
    print("  4d. Per SIMBOLO (top 10 e bottom 5)")
    print(hdr(""), end="")
    sym_stats = []
    for sym in df["symbol"].unique():
        sub = df[df["symbol"] == sym]
        if len(sub) < 20:
            continue
        avg_rs = sub["pnl_r_slip"].mean()
        sym_stats.append((sym, sub, avg_rs))
    sym_stats.sort(key=lambda x: x[2], reverse=True)

    print("  -- Top 10 --")
    for sym, sub, _ in sym_stats[:10]:
        print(table_row(sym, sub))
    print("  -- Bottom 5 --")
    for sym, sub, _ in sym_stats[-5:]:
        print(table_row(sym, sub))

    # -- 4e. Per regime SPY -----------------------------------------------------
    print(f"\n{'-'*75}")
    print("  4e. Per REGIME SPY  ×  DIRECTION")
    print(hdr(""), end="")
    for reg in ["bull", "bear", "neutral"]:
        for direction in ["bullish", "bearish"]:
            sub = df[(df["spy_regime"] == reg) & (df["direction"] == direction)]
            lbl = f"{reg.upper():6s} × {direction}"
            print(table_row(lbl, sub))

    # -- 4f. Per risk_pct ------------------------------------------------------
    print(f"\n{'-'*75}")
    print("  4f. Per RISK_PCT (fasce)")
    print(hdr(""), end="")
    bins_risk = [(0, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 1.2), (1.2, 2.0), (2.0, 5.0)]
    for lo_v, hi_v in bins_risk:
        sub = df[(df["risk_pct"] >= lo_v) & (df["risk_pct"] < hi_v)]
        lbl = f"[{lo_v:.1f}% - {hi_v:.1f}%)"
        print(table_row(lbl, sub))

    # -- 4g. Per confluenza -----------------------------------------------------
    print(f"\n{'-'*75}")
    print("  4g. Per CONFLUENZA (N pattern nello stesso timestamp)")
    print(hdr(""), end="")
    for c in sorted(df["confluence"].dropna().unique()):
        sub = df[df["confluence"] == c]
        lbl = f"confluence = {int(c)}"
        print(table_row(lbl, sub))

    # -- 4h. Per strength ------------------------------------------------------
    print(f"\n{'-'*75}")
    print("  4h. Per PATTERN STRENGTH (fasce)")
    print(hdr(""), end="")
    bins_str = [(0.0, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 1.01)]
    for lo_v, hi_v in bins_str:
        sub = df[(df["pattern_strength"] >= lo_v) & (df["pattern_strength"] < hi_v)]
        lbl = f"strength [{lo_v:.2f} - {hi_v:.2f})"
        print(table_row(lbl, sub))

    # -- 4i. MFE / MAE distribuzione -------------------------------------------
    print(f"\n{'-'*75}")
    print("  4i. MFE / MAE distribuzione (trade con entry filled)")

    mfe = df["mfe_r"].dropna()
    mae = df["mae_r"].dropna()

    if len(mfe) > 0:
        print(f"\n  MFE (Maximum Favorable Excursion) — n={len(mfe):,}")
        for pct in [25, 50, 75, 90, 95]:
            print(f"    p{pct:2d}: {np.percentile(mfe, pct):+.3f}R")
        print(f"    mean: {mfe.mean():+.3f}R   std: {mfe.std():.3f}R")

    if len(mae) > 0:
        print(f"\n  MAE (Maximum Adverse Excursion) — n={len(mae):,}")
        for pct in [25, 50, 75, 90, 95]:
            print(f"    p{pct:2d}: {np.percentile(mae, pct):+.3f}R")
        print(f"    mean: {mae.mean():+.3f}R   std: {mae.std():.3f}R")

    # MFE per outcome
    print(f"\n  MFE per outcome:")
    for oc in ["tp2", "tp1", "stop", "timeout"]:
        sub = df[df["outcome"] == oc]["mfe_r"].dropna()
        if len(sub) > 0:
            print(f"    {oc:10s}: n={len(sub):4,}  mfe_mean={sub.mean():+.3f}R  "
                  f"mfe_p50={np.percentile(sub, 50):+.3f}R")

    # -- 4j. TP ottimale e trailing stop ---------------------------------------
    print(f"\n{'-'*75}")
    print("  4j. TP OTTIMALE e TRAILING STOP (analisi MFE)")

    for r_target in [1.0, 1.5, 2.0, 2.5, 3.0]:
        pct_reached = (df["mfe_r"].fillna(0) >= r_target).mean() * 100
        if len(mfe) > 0:
            print(f"    MFE >= {r_target:.1f}R: {pct_reached:.1f}% dei trade")

    print()
    # Trailing stop simulation: entra a +0.5R, esce al trailing
    for trail_trigger in [0.5, 1.0, 1.5]:
        trail_stop = 0.3  # trail 0.3R indietro dal peak MFE
        # Simula: se MFE raggiunge il trigger, exit a (mfe - trail_stop); altrimenti usa pnl_r_slip reale
        # Il pnl_r_slip reale include già lo slippage; il trail exit lo approssima senza ricalcolo
        mfe_arr      = df["mfe_r"].fillna(-999).values
        pnl_arr      = df["pnl_r_slip"].values
        triggered    = mfe_arr >= trail_trigger
        trail_exits  = np.clip(mfe_arr[triggered] - trail_stop, -1.0, None)
        pnl_sim      = np.where(triggered, np.clip(mfe_arr - trail_stop, -1.0, None), pnl_arr)
        avg_trail    = float(pnl_sim.mean()) if len(pnl_sim) > 0 else 0.0
        wr_trail     = float((pnl_sim > 0).mean() * 100) if len(pnl_sim) > 0 else 0.0
        pct_trig     = triggered.mean() * 100
        print(f"    Trail trigger @ {trail_trigger:.1f}R (stop={trail_stop:.1f}R back): "
              f"avg_r={avg_trail:+.4f}R  WR={wr_trail:.1f}%  triggered={pct_trig:.0f}%")

    print(f"\n{'='*75}")


if __name__ == "__main__":
    main()
