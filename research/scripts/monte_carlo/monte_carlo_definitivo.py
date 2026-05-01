"""
Monte Carlo DEFINITIVO — apr 2026.

Dataset:
  1h : data/val_1h_full.csv      (41,081 rows, timestamp.asc, 2023-04 -> 2025-10, deterministico)
  5m : data/val_5m_expanded.csv  (112,567 rows, timestamp.asc, limite 200k pattern, include SPY/FAANG)

Pool:
  1h : double_bottom/top + macd/rsi_divergence_bear/bull (NO engulfing_bullish)
       engulfing escluso perche' avg_r=-0.035R senza filtro regime (25,855 trade, full dataset)
  5m : double_bottom/top + macd_divergence_bear/bull (NO engulfing_bullish)
       engulfing escluso: avg_r=-0.486R su 5m Alpaca (12,402 trade, full dataset)

Parametri MC:
  Capitale: EUR 2,500 | Risk: 1% per trade | Slippage: 0.15R | 5,000 sim
  Frequenza live = raw / 4 (filtri reali: confluenza -70%, strength, regime)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RNG_SEED = 42
N_SIM    = 5_000
CAPITAL  = 2_500.0
RISK_PCT = 0.01
SLIP     = 0.15

SEP = "=" * 72

# ---------------------------------------------------------------------------
# Pool 1h
# ---------------------------------------------------------------------------
VALIDATED_1H_MC: set[str] = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "rsi_divergence_bull",
    "rsi_divergence_bear", "macd_divergence_bear",
}

df1_raw = pd.read_csv("data/val_1h_full.csv")
df1_raw["pattern_timestamp"] = pd.to_datetime(df1_raw["pattern_timestamp"], utc=True)
df1 = df1_raw[
    df1_raw["entry_filled"].astype(bool) &
    df1_raw["pattern_name"].isin(VALIDATED_1H_MC)
].copy()

# ---------------------------------------------------------------------------
# Pool 5m (expanded, include SPY/FAANG ripristinati, WMT escluso)
# ---------------------------------------------------------------------------
VALIDATED_5M_MC: set[str] = {
    "double_bottom", "double_top",
    "macd_divergence_bear", "macd_divergence_bull",
}

df5_raw = pd.read_csv("data/val_5m_expanded.csv")
df5_raw["pattern_timestamp"] = pd.to_datetime(df5_raw["pattern_timestamp"], utc=True)
# Simboli negativi confermati sul dataset espanso (30 mesi) — esclusi dal pool MC
_BLOCKED_5M = {"SPY", "AAPL", "MSFT", "GOOGL", "WMT"}

df5 = df5_raw[
    df5_raw["entry_filled"].astype(bool) &
    df5_raw["provider"].eq("alpaca") &
    df5_raw["pattern_name"].isin(VALIDATED_5M_MC) &
    ~df5_raw["symbol"].isin(_BLOCKED_5M)
].copy()

# ---------------------------------------------------------------------------
# Statistiche pool
# ---------------------------------------------------------------------------
months_1h = max(1, (df1["pattern_timestamp"].max() - df1["pattern_timestamp"].min()).days / 30)
months_5m = max(1, (df5["pattern_timestamp"].max() - df5["pattern_timestamp"].min()).days / 30)

n_month_1h = len(df1) / months_1h
n_month_5m = len(df5) / months_5m
n_year_1h_raw  = round(n_month_1h * 12)
n_year_5m_raw  = round(n_month_5m * 12)

# Frequenza live stimata (raw / 4): confluenza min 2 patterns ~-70%, strength, regime
n_year_1h = max(1, round(n_year_1h_raw / 4))
n_year_5m = max(1, round(n_year_5m_raw / 4))

avg_r_1h = df1["pnl_r"].mean()
avg_r_5m = df5["pnl_r"].mean()
pool_1h  = (df1["pnl_r"] - SLIP).values
pool_5m  = (df5["pnl_r"] - SLIP).values

print(SEP)
print("  POOL STATISTICHE")
print(SEP)
print(f"  1h : n={len(df1):,}  range {df1['pattern_timestamp'].min().date()} -> {df1['pattern_timestamp'].max().date()}")
print(f"       avg_r={avg_r_1h:+.4f}R  post-slip={pool_1h.mean():+.4f}R  WR={(pool_1h>0).mean()*100:.1f}%")
print(f"       freq raw={n_year_1h_raw} t/a  freq live~{n_year_1h} t/a (raw/4)")
print()
print(f"  5m : n={len(df5):,}  range {df5['pattern_timestamp'].min().date()} -> {df5['pattern_timestamp'].max().date()}")
print(f"       avg_r={avg_r_5m:+.4f}R  post-slip={pool_5m.mean():+.4f}R  WR={(pool_5m>0).mean()*100:.1f}%")
print(f"       freq raw={n_year_5m_raw} t/a  freq live~{n_year_5m} t/a (raw/4)")

# ---------------------------------------------------------------------------
# Statistiche 5m per simbolo (4 pattern validati)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  5m SIMBOLI — 4 pattern validati (double/top/bottom + divergenze MACD)")
print(SEP)
sym5 = (
    df5.groupby("symbol")["pnl_r"]
    .agg(n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100)
    .sort_values("avg_r", ascending=False)
)
for sym, row in sym5.iterrows():
    print(f"  {sym:10s}: n={int(row['n']):>5}  avg={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%")

# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------
def run_mc(pool: np.ndarray, n_trades_year: int, n_sim: int = N_SIM, seed: int = RNG_SEED) -> dict:
    if len(pool) == 0 or n_trades_year == 0:
        return dict(med=CAPITAL, p05=CAPITAL, prob_profit=0.0, dd_med=0.0, dd_p95=0.0)
    rng = np.random.default_rng(seed)
    finals  = np.empty(n_sim)
    max_dds = np.empty(n_sim)
    for i in range(n_sim):
        draws = rng.choice(pool, size=n_trades_year, replace=True)
        eq = CAPITAL; peak = CAPITAL; max_dd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak: peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd: max_dd = dd
        finals[i]  = eq
        max_dds[i] = max_dd
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob_profit=(finals > CAPITAL).mean(),
        dd_med=np.median(max_dds), dd_p95=np.percentile(max_dds, 95),
    )


def run_mc_combined(
    pool_1h: np.ndarray, n_1h: int,
    pool_5m: np.ndarray, n_5m: int,
    n_sim: int = N_SIM, seed: int = RNG_SEED,
) -> dict:
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
        eq = CAPITAL; peak = CAPITAL; max_dd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak: peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd: max_dd = dd
        finals[i]  = eq
        max_dds[i] = max_dd
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob_profit=(finals > CAPITAL).mean(),
        dd_med=np.median(max_dds), dd_p95=np.percentile(max_dds, 95),
    )


print()
print("  Calcolo MC (5,000 simulazioni)...")
mc1h   = run_mc(pool_1h, n_year_1h)
mc5m   = run_mc(pool_5m, n_year_5m)
mc_comb = run_mc_combined(pool_1h, n_year_1h, pool_5m, n_year_5m)

print()
print(SEP)
print("  MONTE CARLO DEFINITIVO")
print("  EUR 2,500 | 1% risk | slip=0.15R | 5,000 sim | 12 mesi | freq=raw/4")
print("  Pool: double/top/bottom + macd/rsi_divergence (no engulfing)")
print(SEP)
header = f"  {'Scenario':<32} {'t/a':>5} {'Mediana':>9} {'Worst5%':>9} {'ProbP':>7} {'DD med':>7} {'DD p95':>7}"
print(header)
print("  " + "-" * 72)

for label, n_yr, mc in [
    ("Solo 1h",           n_year_1h,            mc1h),
    ("Solo 5m Alpaca",    n_year_5m,            mc5m),
    ("Combinato 1h+5m",   n_year_1h+n_year_5m,  mc_comb),
]:
    print(
        f"  {label:<32} {n_yr:>5} "
        f"{mc['med']:>8,.0f}  "
        f"{mc['p05']:>8,.0f}  "
        f"{mc['prob_profit']*100:>6.1f}%  "
        f"{mc['dd_med']*100:>6.1f}%  "
        f"{mc['dd_p95']*100:>6.1f}%"
    )

# ---------------------------------------------------------------------------
# Sensibilita' frequenza (solo combinato, 500 sim)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  SENSIBILITA' FREQUENZA (combinato, 500 sim per rapidita')")
print(SEP)
print(f"  {'freq/anno':>10} {'Mediana':>9} {'Worst5%':>9} {'ProbP':>7} {'DD med':>7}")
print("  " + "-" * 50)
for divisor in [2, 3, 4, 6, 8, 12]:
    n1 = max(1, round(n_year_1h_raw / divisor))
    n5 = max(1, round(n_year_5m_raw / divisor))
    mc_s = run_mc_combined(pool_1h, n1, pool_5m, n5, n_sim=500, seed=99)
    print(
        f"  raw/{divisor:<3} ({n1+n5:>5} t/a): "
        f"{mc_s['med']:>8,.0f}  "
        f"{mc_s['p05']:>8,.0f}  "
        f"{mc_s['prob_profit']*100:>6.1f}%  "
        f"{mc_s['dd_med']*100:>6.1f}%"
    )

# ---------------------------------------------------------------------------
# Sensibilita' slippage (combinato, 500 sim)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  SENSIBILITA' SLIPPAGE (combinato, freq=raw/4, 500 sim)")
print(SEP)
print(f"  {'Slip':>6} {'1h avg_r':>9} {'5m avg_r':>9} {'Mediana':>9} {'Worst5%':>9} {'ProbP':>7}")
print("  " + "-" * 57)
for slip in [0.00, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    p1 = (df1["pnl_r"] - slip).values
    p5 = (df5["pnl_r"] - slip).values
    mc_s = run_mc_combined(p1, n_year_1h, p5, n_year_5m, n_sim=500, seed=99+int(slip*100))
    print(
        f"  {slip:>6.2f} {p1.mean():>+9.4f} {p5.mean():>+9.4f} "
        f"{mc_s['med']:>8,.0f}  {mc_s['p05']:>8,.0f}  {mc_s['prob_profit']*100:>6.1f}%"
    )

print()
print(SEP)
print("  BREAK-EVEN SLIPPAGE")
print(SEP)
print(f"  1h: break-even = {avg_r_1h:+.4f}R  (sistema profittevole fino a {avg_r_1h:.3f}R slip/trade)")
print(f"  5m: break-even = {avg_r_5m:+.4f}R  (sistema profittevole fino a {avg_r_5m:.3f}R slip/trade)")
print()
print("  Dataset usati:")
print(f"  - val_1h_full.csv     : {len(df1_raw):,} rows, 1h, deterministico (timestamp.asc)")
print(f"  - val_5m_expanded.csv : {len(df5_raw):,} rows, 5m, deterministico (timestamp.asc, limit=200k)")
print(f"  - SPY/META/AAPL/MSFT/NVDA/GOOGL: RIPRISTINATI (negativita' era da engulfing, non dai 4 pattern)")
print(f"  - WMT: RIMOSSO (avg_r=-0.166R su n=268 pattern validati)")
print()
