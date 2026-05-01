"""
Step 5+6 — Confronto 5m vs 15m vs 1h + Monte Carlo combinato.

Legge (se esistono):
  research/datasets/val_15m.csv            (Step 3)
  data/val_5m_expanded.csv                 (build_validation_dataset.py --timeframe 5m)
  data/val_1h_production.csv               (build_production_dataset.py)

  Se un file non esiste viene segnalato ma non bloccante.

Stampa:
  5a. Tabella comparativa 1h vs 15m vs 5m
  5b. Pattern migliori per TF
  5c. Ore migliori per TF
  5d. ATR medio per simbolo (1h vs 15m vs 5m)
  5e. Performance COLOSSI su 15m (AAPL, MSFT, GOOGL, AMZN)
  6.  Monte Carlo combinato: 1h+5m triplo vs 1h+5m+15m

NON scrive nulla al DB di produzione.

Uso:
  cd backend
  python research/05_compare_timeframes.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

VAL_15M = Path(__file__).parent / "datasets" / "val_15m.csv"
VAL_5M  = Path(__file__).parent.parent / "data" / "val_5m_expanded.csv"
VAL_1H  = Path(__file__).parent.parent / "data" / "val_1h_production.csv"

N_MC_SIMS   = 10_000   # simulazioni Monte Carlo
RISK_PER_TRADE = 1.0    # % di capitale per trade (per Monte Carlo)
INITIAL_CAP    = 100_000.0
MONTHS_SIM     = 12

SYMBOLS_BLOCKED_5M = frozenset({"SPY", "AAPL", "MSFT", "GOOGL", "WMT", "DELL"})
# Per 15m includiamo AAPL/MSFT/GOOGL nell'analisi separata dei "colossi"
COLOSSI = ["AAPL", "MSFT", "GOOGL", "AMZN"]


# --- helpers -----------------------------------------------------------------

def _load(path: Path, label: str) -> Optional[pd.DataFrame]:
    if not path.exists():
        print(f"  [{label}] File non trovato: {path}  -> skip")
        return None
    df = pd.read_csv(path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    print(f"  [{label}] Caricato: {len(df):,} righe da {path.name}")
    return df


def _prepare(df: Optional[pd.DataFrame], label: str,
             r_col: str = "pnl_r_slip",
             filter_blocked: bool = True) -> Optional[pd.DataFrame]:
    """Filtra: entry_filled=True, non bloccati, r_col esistente."""
    if df is None:
        return None

    # Compatibilità con vari schemi CSV
    if "entry_filled" in df.columns:
        df = df[df["entry_filled"] == True].copy()
    if "pnl_r_slip" not in df.columns and "pnl_r" in df.columns:
        df["pnl_r_slip"] = df["pnl_r"]  # fallback senza slippage separato
    if r_col not in df.columns:
        print(f"  [{label}] Colonna '{r_col}' mancante — uso 'pnl_r'")
        df["pnl_r_slip"] = df.get("pnl_r", 0.0)

    if filter_blocked and "is_blocked" in df.columns:
        df = df[df["is_blocked"] == False]
    elif filter_blocked and "symbol" in df.columns:
        df = df[~df["symbol"].isin(SYMBOLS_BLOCKED_5M)]

    return df.copy()


def _stats(df: Optional[pd.DataFrame], label: str) -> dict:
    if df is None or len(df) == 0:
        return {"label": label, "n": 0, "wr": np.nan, "avg_r": np.nan, "median_r": np.nan}
    r = df["pnl_r_slip"]
    return {
        "label":    label,
        "n":        len(df),
        "wr":       (r > 0).mean() * 100,
        "avg_r":    r.mean(),
        "median_r": r.median(),
    }


def _wilson(wins: int, n: int) -> tuple[float, float]:
    z = 1.96
    if n == 0:
        return 0.0, 100.0
    p = wins / n
    center = (p + z**2/(2*n)) / (1 + z**2/n)
    margin = z * ((p*(1-p)/n + z**2/(4*n**2))**0.5) / (1 + z**2/n)
    return round(max(0, center-margin)*100, 1), round(min(1, center+margin)*100, 1)


def best_patterns(df: Optional[pd.DataFrame], top_n: int = 3) -> str:
    if df is None or "pattern_name" not in df.columns or len(df) == 0:
        return "—"
    stats = df.groupby("pattern_name")["pnl_r_slip"].agg(["mean", "count"])
    stats = stats[stats["count"] >= 20].sort_values("mean", ascending=False)
    names = stats.index.tolist()[:top_n]
    return ", ".join(names) if names else "—"


def best_hours(df: Optional[pd.DataFrame], top_n: int = 3) -> str:
    if df is None or len(df) == 0:
        return "—"
    if "hour_et" in df.columns:
        col = "hour_et"
    else:
        return "—"
    stats = df.groupby(col)["pnl_r_slip"].agg(["mean", "count"])
    stats = stats[stats["count"] >= 20].sort_values("mean", ascending=False)
    hours = [str(int(h)) + "h ET" for h in stats.index.tolist()[:top_n]]
    return ", ".join(hours) if hours else "—"


# --- Monte Carlo --------------------------------------------------------------

def _daily_trades_estimate(df: pd.DataFrame) -> float:
    """Stima trade per giorno di mercato."""
    if df is None or len(df) == 0:
        return 0.0
    if "timestamp" not in df.columns:
        return 0.0
    ts = df["timestamp"].dropna()
    if len(ts) < 2:
        return 0.0
    days = (ts.max() - ts.min()).days
    trading_days = max(days * 252 / 365, 1)
    return len(df) / trading_days


def monte_carlo_equity(
    r_series: np.ndarray,
    trades_per_year: float,
    n_sims: int = N_MC_SIMS,
    months: int = MONTHS_SIM,
    initial_capital: float = INITIAL_CAP,
    risk_pct: float = RISK_PER_TRADE,
) -> dict:
    """
    Monte Carlo con compound sizing:
      PnL per trade = capital × risk_pct / 100 × r_multiple
    Ritorna: mediana_finale, p25, p75, p90_drawdown, pct_profitable
    """
    if len(r_series) == 0 or trades_per_year <= 0:
        return {}

    trades_total = int(trades_per_year * months / 12)
    if trades_total == 0:
        return {}

    finals = np.zeros(n_sims)
    max_dds = np.zeros(n_sims)

    rng = np.random.default_rng(42)
    for sim in range(n_sims):
        sampled = rng.choice(r_series, size=trades_total, replace=True)
        cap    = initial_capital
        peak   = initial_capital
        max_dd = 0.0
        for r in sampled:
            cap  += cap * (risk_pct / 100.0) * r
            cap   = max(cap, 0.01)
            if cap > peak:
                peak = cap
            dd = (peak - cap) / peak * 100
            if dd > max_dd:
                max_dd = dd
        finals[sim]  = cap
        max_dds[sim] = max_dd

    return_pct = (finals / initial_capital - 1) * 100
    return {
        "trades_per_year": int(trades_per_year),
        "trades_12m":      trades_total,
        "median_final":    round(np.median(finals), 0),
        "median_return_pct": round(np.median(return_pct), 1),
        "p25_return_pct":  round(np.percentile(return_pct, 25), 1),
        "p75_return_pct":  round(np.percentile(return_pct, 75), 1),
        "p90_drawdown":    round(np.percentile(max_dds, 90), 1),
        "pct_profitable":  round((finals > initial_capital).mean() * 100, 1),
    }


# --- main ---------------------------------------------------------------------

def main():
    print("=" * 75)
    print("STEP 5+6 — Confronto timeframe + Monte Carlo combinato")
    print("=" * 75)

    print("\nCaricamento dataset:")
    df15m = _load(VAL_15M, "15m")
    df5m  = _load(VAL_5M,  "5m")
    df1h  = _load(VAL_1H,  "1h")

    d15 = _prepare(df15m, "15m")
    d5  = _prepare(df5m,  "5m")
    d1  = _prepare(df1h,  "1h", filter_blocked=True)

    # -- 5a. Tabella comparativa ----------------------------------------------
    print(f"\n{'-'*75}")
    print("  5a. CONFRONTO 5m vs 15m vs 1h")
    print()

    hdr = f"  {'Metrica':30s} {'1h':>12} {'15m':>12} {'5m':>12}"
    print(hdr)
    print("  " + "-" * 70)

    s1  = _stats(d1,  "1h")
    s15 = _stats(d15, "15m")
    s5  = _stats(d5,  "5m")

    def fmt(v, fmt_str=".4f", unit="R"):
        if v is None or np.isnan(v):
            return "—"
        return f"{v:{fmt_str}}{unit}"

    def fmt_pct(v):
        if v is None or np.isnan(v):
            return "—"
        return f"{v:.1f}%"

    metrics = [
        ("n totale",          fmt(s1["n"], ",.0f", ""), fmt(s15["n"], ",.0f", ""), fmt(s5["n"], ",.0f", "")),
        ("avg R+slip",        fmt(s1["avg_r"]), fmt(s15["avg_r"]), fmt(s5["avg_r"])),
        ("median R+slip",     fmt(s1["median_r"]), fmt(s15["median_r"]), fmt(s5["median_r"])),
        ("Win Rate",          fmt_pct(s1["wr"]), fmt_pct(s15["wr"]), fmt_pct(s5["wr"])),
        ("Pattern migliori",  best_patterns(d1), best_patterns(d15), best_patterns(d5)),
        ("Ore migliori ET",   best_hours(d1), best_hours(d15), best_hours(d5)),
    ]
    for name, v1, v15, v5 in metrics:
        print(f"  {name:30s} {v1:>12} {v15:>12} {v5:>12}")

    # -- 5b. Pattern per TF ----------------------------------------------------
    print(f"\n{'-'*75}")
    print("  5b. TOP PATTERN per timeframe (avg R+slip, n>=20)")
    for label, ddf in [("15m", d15), ("5m", d5), ("1h", d1)]:
        if ddf is None or len(ddf) == 0:
            continue
        print(f"\n  [{label}]")
        print(f"  {'Pattern':35s} {'n':>6} {'WR%':>7} {'avg R':>8}")
        print("  " + "-" * 60)
        for pname, grp in ddf.groupby("pattern_name"):
            if len(grp) < 20:
                continue
            wr  = (grp["pnl_r_slip"] > 0).mean() * 100
            avg = grp["pnl_r_slip"].mean()
            print(f"  {pname:35s} {len(grp):>6,} {wr:>6.1f}% {avg:>+8.4f}R")

    # -- 5c. Ore migliori per TF -----------------------------------------------
    print(f"\n{'-'*75}")
    print("  5c. PERFORMANCE per ORA ET (15m)")
    if d15 is not None and len(d15) > 0 and "hour_et" in d15.columns:
        print(f"  {'Ora ET':12s} {'n':>6} {'WR%':>7} {'avg R+slip':>10}")
        print("  " + "-" * 40)
        for hr in range(9, 17):
            sub = d15[d15["hour_et"] == hr]
            if len(sub) < 10:
                continue
            wr  = (sub["pnl_r_slip"] > 0).mean() * 100
            avg = sub["pnl_r_slip"].mean()
            print(f"  {hr:2d}:00 ET          {len(sub):>6,} {wr:>6.1f}% {avg:>+10.4f}R")

    # -- 5d. ATR% per simbolo --------------------------------------------------
    print(f"\n{'-'*75}")
    print("  5d. ATR% per simbolo (15m)")
    if d15 is not None and "atr14" in d15.columns and "entry_price" in d15.columns:
        d15["atr_pct"] = d15["atr14"].astype(float) / d15["entry_price"].astype(float) * 100
        sym_atr = (
            d15.groupby("symbol")
            .agg(atr_pct_mean=("atr_pct", "mean"), n=("atr_pct", "count"), avg_r=("pnl_r_slip", "mean"))
            .query("n >= 20")
            .sort_values("atr_pct_mean", ascending=False)
        )
        print(f"  {'Simbolo':12s} {'ATR% 15m':>10} {'n':>6} {'avg R 15m':>10}")
        print("  " + "-" * 45)
        for sym_name, row in sym_atr.iterrows():
            print(f"  {sym_name:12s} {row['atr_pct_mean']:>9.3f}% {int(row['n']):>6,} {row['avg_r']:>+10.4f}R")

    # -- 5e. Colossi su 15m -----------------------------------------------------
    print(f"\n{'-'*75}")
    print("  5e. PERFORMANCE COLOSSI su 15m (inclusi i bloccati su 5m)")
    if df15m is not None:
        # Usa il dataset SENZA filtro blocked per vedere i colossi
        df_colossi = _prepare(df15m, "15m (colossi)", filter_blocked=False)
        if df_colossi is not None:
            print(f"  {'Simbolo':12s} {'n':>6} {'WR%':>7} {'avg R+slip':>10} {'Bloccato 5m':>12}")
            print("  " + "-" * 55)
            for sym_c in COLOSSI + ["NVDA", "META", "TSLA", "AMD"]:
                sub = df_colossi[df_colossi["symbol"] == sym_c]
                if len(sub) == 0:
                    continue
                wr  = (sub["pnl_r_slip"] > 0).mean() * 100
                avg = sub["pnl_r_slip"].mean()
                blocked = "Sì" if sym_c in SYMBOLS_BLOCKED_5M else "No"
                print(f"  {sym_c:12s} {len(sub):>6,} {wr:>6.1f}% {avg:>+10.4f}R {blocked:>12}")

    # -- Step 6 — Monte Carlo --------------------------------------------------
    print(f"\n{'-'*75}")
    print("  STEP 6 — MONTE CARLO COMBINATO (12 mesi, 10.000 simulazioni)")
    print(f"  Parametri: rischio {RISK_PER_TRADE}%/trade, capitale iniziale ${INITIAL_CAP:,.0f}")
    print()

    scenarios = []

    # Arrays R per timeframe (inizializza vuoti come fallback)
    r1h      = d1["pnl_r_slip"].values  if (d1  is not None and len(d1)  > 0) else np.array([])
    r5m      = d5["pnl_r_slip"].values  if (d5  is not None and len(d5)  > 0) else np.array([])
    r15m     = d15["pnl_r_slip"].values if (d15 is not None and len(d15) > 0) else np.array([])
    daily1h  = _daily_trades_estimate(d1)  if d1  is not None else 0.0
    daily5m  = _daily_trades_estimate(d5)  if d5  is not None else 0.0
    daily15m = _daily_trades_estimate(d15) if d15 is not None else 0.0

    # Scenario 1: solo 1h (baseline attuale)
    if len(r1h) > 0:
        mc1h = monte_carlo_equity(r1h, daily1h * 252, n_sims=N_MC_SIMS)
        scenarios.append(("Solo 1h (baseline)", mc1h))

    # Scenario 2: 1h + 5m triplo (attuale)
    parts_1h5m = [a for a in [r1h, r5m, r5m, r5m] if len(a) > 0]
    if parts_1h5m:
        r_comb_1h5m = np.concatenate(parts_1h5m)
        daily_1h5m  = daily1h * 252 + daily5m * 252 * 3
        mc_1h5m = monte_carlo_equity(r_comb_1h5m, daily_1h5m, n_sims=N_MC_SIMS)
        scenarios.append(("1h + 5m TRIPLO (attuale)", mc_1h5m))

    # Scenario 3: 1h + 5m triplo + 15m
    parts_all = [a for a in [r1h, r5m, r5m, r5m, r15m] if len(a) > 0]
    if parts_all and len(r15m) > 0:
        r_comb_all = np.concatenate(parts_all)
        daily_all  = daily1h * 252 + daily5m * 252 * 3 + daily15m * 252
        mc_all = monte_carlo_equity(r_comb_all, daily_all, n_sims=N_MC_SIMS)
        scenarios.append(("1h + 5m TRIPLO + 15m", mc_all))

    # Scenario 4: solo 15m
    if len(r15m) > 0:
        mc15 = monte_carlo_equity(r15m, daily15m * 252, n_sims=N_MC_SIMS)
        scenarios.append(("Solo 15m", mc15))

    if not scenarios:
        print("  Nessun dataset disponibile per il Monte Carlo.")
        return

    print(f"  {'Scenario':30s} {'Trade/anno':>12} {'Mediana 12m':>13} {'Rend%':>8} "
          f"{'p25%':>8} {'p75%':>8} {'DD p90':>8} {'Profit%':>8}")
    print("  " + "-" * 105)
    for label, mc in scenarios:
        if not mc:
            continue
        print(f"  {label:30s} "
              f"{mc.get('trades_per_year',0):>12,} "
              f"${mc.get('median_final',0):>12,.0f} "
              f"{mc.get('median_return_pct',0):>+7.1f}% "
              f"{mc.get('p25_return_pct',0):>+7.1f}% "
              f"{mc.get('p75_return_pct',0):>+7.1f}% "
              f"{mc.get('p90_drawdown',0):>7.1f}% "
              f"{mc.get('pct_profitable',0):>7.1f}%")

    print(f"\n{'='*75}")


if __name__ == "__main__":
    main()
