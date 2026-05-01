"""
Monte Carlo finale — post FIX3 + FIX4.
Dataset: val_1h_fix3.csv + val_5m_fix3_fix4.csv
Capitale: EUR 2,500 | risk 1% per trade | 5,000 simulazioni | 12 mesi
Slippage: 0.15R per trade (su avg_r pre-slippage)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RNG_SEED = 42
N_SIM    = 5_000
CAPITAL  = 2_500.0
RISK_PCT = 0.01
SLIP     = 0.15   # R per trade

VALIDATED_1H = {
    "double_bottom", "double_top", "engulfing_bullish",
    "macd_divergence_bull", "rsi_divergence_bull",
    "rsi_divergence_bear", "macd_divergence_bear",
}
VALIDATED_5M_ALPACA = {
    "double_bottom", "double_top",
    "macd_divergence_bear", "macd_divergence_bull",
}

SEP = "=" * 72

# ─── Carica pool ──────────────────────────────────────────────────────────────

df1_raw = pd.read_csv("data/val_1h_fix3.csv")
df1_raw["pattern_timestamp"] = pd.to_datetime(df1_raw["pattern_timestamp"], utc=True)
df1 = df1_raw[
    df1_raw["entry_filled"].astype(bool) &
    df1_raw["pattern_name"].isin(VALIDATED_1H)
].copy()

df5_raw = pd.read_csv("data/val_5m_fix3_fix4.csv")
df5_raw["pattern_timestamp"] = pd.to_datetime(df5_raw["pattern_timestamp"], utc=True)
df5 = df5_raw[
    df5_raw["entry_filled"].astype(bool) &
    df5_raw["provider"].eq("alpaca") &
    df5_raw["pattern_name"].isin(VALIDATED_5M_ALPACA)
].copy()

# ─── Statistiche pool ─────────────────────────────────────────────────────────

months_1h = max(1, (df1["pattern_timestamp"].max() - df1["pattern_timestamp"].min()).days / 30)
months_5m = max(1, (df5["pattern_timestamp"].max() - df5["pattern_timestamp"].min()).days / 30)

n_month_1h = len(df1) / months_1h
n_month_5m = len(df5) / months_5m
n_year_1h  = round(n_month_1h * 12)
n_year_5m  = round(n_month_5m * 12)

avg_r_1h    = df1["pnl_r"].mean()
avg_r_5m    = df5["pnl_r"].mean()
pool_1h     = (df1["pnl_r"] - SLIP).values
pool_5m     = (df5["pnl_r"] - SLIP).values

print(SEP)
print("  POOL STATISTICHE")
print(SEP)
print(f"  1h : n={len(df1):,}  avg_r pre-slip={avg_r_1h:+.4f}  avg_r post-slip={pool_1h.mean():+.4f}  {n_year_1h} t/a")
print(f"  5m : n={len(df5):,}  avg_r pre-slip={avg_r_5m:+.4f}  avg_r post-slip={pool_5m.mean():+.4f}  {n_year_5m} t/a")
print()


# ─── Monte Carlo ──────────────────────────────────────────────────────────────

def run_mc(
    pool: np.ndarray,
    n_trades_year: int,
    n_sim: int = N_SIM,
    seed: int = RNG_SEED,
) -> dict:
    """Bootstrap MC compound equity."""
    if len(pool) == 0 or n_trades_year == 0:
        return dict(med=CAPITAL, p05=CAPITAL, prob_profit=0.0, dd_med=0.0, dd_p95=0.0)
    rng = np.random.default_rng(seed)
    finals   = np.empty(n_sim)
    max_dds  = np.empty(n_sim)
    for i in range(n_sim):
        draws = rng.choice(pool, size=n_trades_year, replace=True)
        eq  = CAPITAL
        peak = CAPITAL
        max_dd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        finals[i]  = eq
        max_dds[i] = max_dd
    return dict(
        med       = np.median(finals),
        p05       = np.percentile(finals, 5),
        prob_profit = (finals > CAPITAL).mean(),
        dd_med    = np.median(max_dds),
        dd_p95    = np.percentile(max_dds, 95),
    )


def run_mc_combined(
    pool_1h: np.ndarray, n_1h: int,
    pool_5m: np.ndarray, n_5m: int,
    n_sim: int = N_SIM,
    seed: int = RNG_SEED,
) -> dict:
    """MC combinato: disegna proporzionalmente da 1h e 5m, poi mescola."""
    total = n_1h + n_5m
    if total == 0:
        return dict(med=CAPITAL, p05=CAPITAL, prob_profit=0.0, dd_med=0.0, dd_p95=0.0)
    rng = np.random.default_rng(seed)
    finals  = np.empty(n_sim)
    max_dds = np.empty(n_sim)
    for i in range(n_sim):
        d1 = rng.choice(pool_1h, size=n_1h, replace=True)
        d5 = rng.choice(pool_5m, size=n_5m, replace=True)
        draws = np.concatenate([d1, d5])
        rng.shuffle(draws)
        eq  = CAPITAL
        peak = CAPITAL
        max_dd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        finals[i]  = eq
        max_dds[i] = max_dd
    return dict(
        med       = np.median(finals),
        p05       = np.percentile(finals, 5),
        prob_profit = (finals > CAPITAL).mean(),
        dd_med    = np.median(max_dds),
        dd_p95    = np.percentile(max_dds, 95),
    )


print(SEP)
print("  MONTE CARLO (5,000 sim, 12 mesi, slip=0.15R, capitale EUR 2,500)")
print(SEP)

print("\n  Calcolo Solo 1h post-FIX3…")
mc1h = run_mc(pool_1h, n_year_1h)

print("  Calcolo Solo 5m post-FIX3+FIX4…")
mc5m = run_mc(pool_5m, n_year_5m)

print("  Calcolo Combinato…")
mc_comb = run_mc_combined(pool_1h, n_year_1h, pool_5m, n_year_5m)

# ─── Tabella risultati ────────────────────────────────────────────────────────

print()
header = f"  {'Scenario':<30} {'t/a':>5} {'Mediana':>9} {'Worst5%':>9} {'ProbP':>7} {'DD med':>7} {'DD p95':>7}"
print(header)
print(f"  {'-'*len(header.strip())}")

rows = [
    ("Solo 1h post-FIX3",       n_year_1h,         mc1h),
    ("Solo 5m post-FIX3+FIX4",  n_year_5m,         mc5m),
    ("Combinato 1h+5m",          n_year_1h+n_year_5m, mc_comb),
]
for label, n_yr, mc in rows:
    print(
        f"  {label:<30} {n_yr:>5} "
        f"{mc['med']:>8,.0f}  "
        f"{mc['p05']:>8,.0f}  "
        f"{mc['prob_profit']*100:>6.1f}%  "
        f"{mc['dd_med']*100:>6.1f}%  "
        f"{mc['dd_p95']*100:>6.1f}%"
    )

# ─── Confronto con baseline pre-fix ───────────────────────────────────────────

print()
print(SEP)
print("  CONFRONTO CON BASELINE PRE-FIX (da sessione precedente)")
print(SEP)
print()
print("  Scenario pre-fix (MC sessione precedente, stessi parametri):")
print("    Solo 1h baseline  : mediana EUR 6,636  |  DD med 12.4%  |  Worst5% 4,138")
print("    Solo 5m baseline  : mediana EUR 4,568  |  DD med 14.3%  |  Worst5% 3,003")
print("    Combinato baseline: mediana EUR 12,063 |  DD med 15.8%  |  Worst5% 6,538")
print()
print("  Scenario post-FIX3+FIX4 (questo run):")
print(f"    Solo 1h post-fix  : mediana EUR {mc1h['med']:,.0f}  |  DD med {mc1h['dd_med']*100:.1f}%  |  Worst5% {mc1h['p05']:,.0f}")
print(f"    Solo 5m post-fix  : mediana EUR {mc5m['med']:,.0f}  |  DD med {mc5m['dd_med']*100:.1f}%  |  Worst5% {mc5m['p05']:,.0f}")
print(f"    Combinato post-fix: mediana EUR {mc_comb['med']:,.0f} |  DD med {mc_comb['dd_med']*100:.1f}%  |  Worst5% {mc_comb['p05']:,.0f}")

# ─── Analisi pool e interpretazione ───────────────────────────────────────────

print()
print(SEP)
print("  ANALISI POOL DETTAGLIATA")
print(SEP)
print()
print(f"  1h pool post-slip: avg={pool_1h.mean():+.4f}R  std={pool_1h.std():.3f}  "
      f"WR={(pool_1h>0).mean()*100:.1f}%  n={len(pool_1h)}")
print(f"  5m pool post-slip: avg={pool_5m.mean():+.4f}R  std={pool_5m.std():.3f}  "
      f"WR={(pool_5m>0).mean()*100:.1f}%  n={len(pool_5m)}")

print()
print("  Sensibilita' slippage (solo combinato, 500 sim):")
print(f"  {'Slip':>6} {'1h avg_r':>9} {'5m avg_r':>9} {'Mediana':>9} {'Worst5%':>9} {'ProbP':>7}")
print(f"  {'-'*55}")
for slip in [0.00, 0.05, 0.10, 0.15, 0.20, 0.25]:
    p1h_s = (df1["pnl_r"] - slip).values
    p5m_s = (df5["pnl_r"] - slip).values
    mc_s = run_mc_combined(p1h_s, n_year_1h, p5m_s, n_year_5m, n_sim=500, seed=99+int(slip*100))
    print(
        f"  {slip:>6.2f} {p1h_s.mean():>+9.4f} {p5m_s.mean():>+9.4f} "
        f"{mc_s['med']:>8,.0f}  {mc_s['p05']:>8,.0f}  {mc_s['prob_profit']*100:>6.1f}%"
    )

print()
print(SEP)
print("  BREAK-EVEN SLIPPAGE")
print(SEP)
print(f"  1h post-fix: break-even slippage = {avg_r_1h:+.4f}R")
print(f"  5m post-fix: break-even slippage = {avg_r_5m:+.4f}R")
print(f"  Il sistema combinato resta profittevole fino a ~{min(avg_r_1h, avg_r_5m):.2f}R di slippage per trade.")
print()
