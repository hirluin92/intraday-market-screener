"""OOS 70/30 + Monte Carlo finale con tutti i fix."""
from __future__ import annotations
import pandas as pd
import numpy as np
import pytz

SEP = "=" * 72
ET  = pytz.timezone("America/New_York")
RNG_SEED = 42
N_SIM    = 5_000
CAPITAL  = 2_500.0
RISK_PCT = 0.01
SLIP     = 0.15

PATTERNS_1H = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}
PATTERNS_5M = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
}
BLOCKED_5M = {"SPY", "AAPL", "MSFT", "GOOGL", "WMT"}

# ── Load ───────────────────────────────────────────────────────────────────────
df1r = pd.read_csv("data/val_1h_full.csv")
df1r["pattern_timestamp"] = pd.to_datetime(df1r["pattern_timestamp"], utc=True)
df1r["_hour_et"] = df1r["pattern_timestamp"].dt.tz_convert(ET).dt.hour

df5r = pd.read_csv("data/val_5m_expanded.csv")
df5r["pattern_timestamp"] = pd.to_datetime(df5r["pattern_timestamp"], utc=True)

# Base 1h pool (6 pattern, entry_filled, no hour filter yet)
df1_base = df1r[
    df1r["entry_filled"].astype(bool) &
    df1r["pattern_name"].isin(PATTERNS_1H)
].copy().sort_values("pattern_timestamp")

# ── Split 70/30 ────────────────────────────────────────────────────────────────
cut    = int(len(df1_base) * 0.70)
cut_ts = df1_base.iloc[cut]["pattern_timestamp"]
train  = df1_base.iloc[:cut].copy()
test   = df1_base.iloc[cut:].copy()

print(SEP)
print("  OOS 70/30 — FIX 10 / 11 / 12 su val_1h_full.csv")
print(SEP)
print(f"  TRAIN: n={len(train):,}  "
      f"{train['pattern_timestamp'].min().date()} -> {cut_ts.date()}  "
      f"avg_r={train['pnl_r'].mean():+.4f}R")
print(f"  TEST:  n={len(test):,}  "
      f"{cut_ts.date()} -> {test['pattern_timestamp'].max().date()}  "
      f"avg_r={test['pnl_r'].mean():+.4f}R")


def oos_check(name: str, mask_remove_fn, min_n: int = 50) -> None:
    print(f"\n  {name}")
    for lbl, df_ in [("TRAIN", train), ("TEST", test)]:
        mask  = mask_remove_fn(df_)
        kept  = df_[~mask]
        rem   = df_[mask]
        base  = df_["pnl_r"].mean()
        kr    = kept["pnl_r"].mean() if len(kept) >= min_n else float("nan")
        rr    = rem["pnl_r"].mean()  if len(rem) >= min_n  else float("nan")
        delta = kr - base
        v     = "TIENE" if delta > 0.01 else ("NEUTRO" if delta > -0.02 else "PEGGIORA")
        print(f"  [{lbl}]  rim: n={len(rem):>5}  avg_rim={rr:>+.4f}R  "
              f"| ten: n={len(kept):>5}  avg_ten={kr:>+.4f}R  "
              f"delta={delta:>+.4f}R  [{v}]")


# ── FIX 10 — Confluenza >= 1 (gia' implementata) ──────────────────────────────
# Ricostruisci conteggio pattern per (symbol, hour) nel dataset COMPLETO
df1r_filled = df1r[df1r["entry_filled"].astype(bool) & df1r["pattern_name"].isin(PATTERNS_1H)].copy()
df1r_filled["_ts_h"] = df1r_filled["pattern_timestamp"].dt.floor("h")
conf_map = (df1r_filled.groupby(["symbol", "_ts_h"])["pattern_name"]
            .count().rename("_nconf"))

for df_ in [train, test]:
    df_["_ts_h"] = df_["pattern_timestamp"].dt.floor("h")
    df_["_nconf"] = df_.set_index(["symbol", "_ts_h"]).index.map(conf_map).values
    df_["_nconf"] = df_["_nconf"].fillna(1).astype(int)

print()
print(SEP)
print("  FIX 10 — CONFLUENZA: 1-pattern vs 2+-pattern")
print(SEP)
for lbl, df_ in [("TRAIN", train), ("TEST", test)]:
    r1 = df_[df_["_nconf"] == 1]["pnl_r"].mean()
    r2 = df_[df_["_nconf"] >= 2]["pnl_r"].mean()
    n1 = (df_["_nconf"] == 1).sum()
    n2 = (df_["_nconf"] >= 2).sum()
    beat = "SI" if r1 > r2 else "NO"
    print(f"  [{lbl}]  1-pat: n={n1:>5}  avg={r1:>+.4f}R  |  "
          f"2+-pat: n={n2:>5}  avg={r2:>+.4f}R  |  1-pat MIGLIORE: {beat}")

# ── FIX 11 — Min strength 0.60 ────────────────────────────────────────────────
print()
print(SEP)
print("  FIX 11 — SOGLIA STRENGTH: 0.60-0.70 (aggiunta) vs 0.70+ (attuale)")
print(SEP)
for lbl, df_ in [("TRAIN", train), ("TEST", test)]:
    r60 = df_[(df_["pattern_strength"] >= 0.60) & (df_["pattern_strength"] < 0.70)]["pnl_r"].mean()
    r70 = df_[df_["pattern_strength"] >= 0.70]["pnl_r"].mean()
    n60 = ((df_["pattern_strength"] >= 0.60) & (df_["pattern_strength"] < 0.70)).sum()
    n70 = (df_["pattern_strength"] >= 0.70).sum()
    beat = "SI" if r60 > r70 else "NO"
    print(f"  [{lbl}]  0.60-0.70: n={n60:>5}  avg={r60:>+.4f}R  |  "
          f"0.70+: n={n70:>5}  avg={r70:>+.4f}R  |  0.60-0.70 MIGLIORE: {beat}")

# Dettaglio per fascia
print()
print("  Dettaglio fasce strength — TRAIN vs TEST:")
print(f"  {'Fascia':12s}  {'TR n':>7}  {'TR avg':>9}  {'TE n':>7}  {'TE avg':>9}  {'Coerente?':>10}")
print("  " + "-" * 60)
for lo, hi in [(0.50, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.80)]:
    tm = train[(train["pattern_strength"] >= lo) & (train["pattern_strength"] < hi)]
    te = test[(test["pattern_strength"] >= lo) & (test["pattern_strength"] < hi)]
    tr = tm["pnl_r"].mean() if len(tm) >= 20 else float("nan")
    te_r = te["pnl_r"].mean() if len(te) >= 20 else float("nan")
    coh = ""
    if not (np.isnan(tr) or np.isnan(te_r)):
        coh = "SI" if abs(tr - te_r) < 0.30 else "GAP"
    print(f"  {lo:.2f}-{hi:.2f}     {len(tm):>7,}  {tr:>+9.4f}  "
          f"{len(te):>7,}  {te_r:>+9.4f}  {coh:>10}")

# ── FIX 12 — risk_pct <= 1.5% ─────────────────────────────────────────────────
oos_check(
    SEP + "\n  FIX 12 — risk_pct > 1.5% (rimossi)",
    lambda df_: df_["risk_pct"] > 1.5,
)
print()
print("  Dettaglio per fascia risk_pct — TRAIN vs TEST:")
print(f"  {'Fascia%':10s}  {'TR n':>7}  {'TR avg':>9}  {'TE n':>7}  {'TE avg':>9}  {'Coerente?':>10}")
print("  " + "-" * 60)
for lo, hi in [(0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 100)]:
    tm = train[(train["risk_pct"] > lo) & (train["risk_pct"] <= hi)]
    te = test[(test["risk_pct"] > lo) & (test["risk_pct"] <= hi)]
    tr = tm["pnl_r"].mean() if len(tm) >= 20 else float("nan")
    te_r = te["pnl_r"].mean() if len(te) >= 20 else float("nan")
    coh = ""
    if not (np.isnan(tr) or np.isnan(te_r)):
        coh = "SI" if (tr > 0.4) == (te_r > 0.4) else "NO"
    print(f"  {lo:.1f}-{hi:.1f}%     {len(tm):>7,}  {tr:>+9.4f}  "
          f"{len(te):>7,}  {te_r:>+9.4f}  {coh:>10}")

# ── Pool finale 1h post-tutti-i-fix ───────────────────────────────────────────
print()
print(SEP)
print("  POOL 1h FINALE (tutti i fix: FIX7+8+11+12+strength>=0.60+no 03/09 ET)")
print(SEP)
df1_fix = df1r[
    df1r["entry_filled"].astype(bool) &
    df1r["pattern_name"].isin(PATTERNS_1H) &
    ~df1r["_hour_et"].isin([3, 9]) &
    (df1r["pattern_strength"] >= 0.60) &
    (df1r["risk_pct"] <= 1.5)
].copy()

# 5m pool
df5 = df5r[
    df5r["entry_filled"].astype(bool) &
    df5r["provider"].eq("alpaca") &
    df5r["pattern_name"].isin(PATTERNS_5M) &
    ~df5r["symbol"].isin(BLOCKED_5M)
].copy()

months_1h = max(1, (df1_fix["pattern_timestamp"].max() -
                    df1_fix["pattern_timestamp"].min()).days / 30)
months_5m = max(1, (df5["pattern_timestamp"].max() -
                    df5["pattern_timestamp"].min()).days / 30)
n_yr_1h_raw = round(len(df1_fix) / months_1h * 12)
n_yr_5m_raw = round(len(df5) / months_5m * 12)
n_yr_1h = max(1, round(n_yr_1h_raw / 4))
n_yr_5m = max(1, round(n_yr_5m_raw / 4))

pool_1h = (df1_fix["pnl_r"] - SLIP).values
pool_5m = (df5["pnl_r"] - SLIP).values

print(f"  1h: n={len(df1_fix):,}  avg_r={df1_fix['pnl_r'].mean():+.4f}R  "
      f"WR={(df1_fix['pnl_r']>0).mean()*100:.1f}%  post-slip={pool_1h.mean():+.4f}R")
print(f"      freq raw={n_yr_1h_raw}/a  live~{n_yr_1h}/a (raw/4)")
print(f"  5m: n={len(df5):,}  avg_r={df5['pnl_r'].mean():+.4f}R  "
      f"WR={(df5['pnl_r']>0).mean()*100:.1f}%  post-slip={pool_5m.mean():+.4f}R")
print(f"      freq raw={n_yr_5m_raw}/a  live~{n_yr_5m}/a (raw/4)")

# Breakdown by fix applied
print()
print("  Impatto incrementale dei fix sul pool 1h:")
configs = [
    ("Base (6 pattern, entry_filled)",
     df1r[df1r["entry_filled"].astype(bool) & df1r["pattern_name"].isin(PATTERNS_1H)]),
    ("+ escludi 03+09 ET (FIX7+8)",
     df1r[df1r["entry_filled"].astype(bool) & df1r["pattern_name"].isin(PATTERNS_1H)
          & ~df1r["_hour_et"].isin([3, 9])]),
    ("+ strength >= 0.60 (FIX11)",
     df1r[df1r["entry_filled"].astype(bool) & df1r["pattern_name"].isin(PATTERNS_1H)
          & ~df1r["_hour_et"].isin([3, 9]) & (df1r["pattern_strength"] >= 0.60)]),
    ("+ risk_pct <= 1.5% (FIX12)",
     df1_fix),
]
for name, sub in configs:
    print(f"  {name:<42}: n={len(sub):>6,}  avg_r={sub['pnl_r'].mean():>+.4f}R  "
          f"WR={(sub['pnl_r']>0).mean()*100:>5.1f}%")


# ── Monte Carlo ────────────────────────────────────────────────────────────────
def run_mc(pool: np.ndarray, n_trades: int, n_sim: int = N_SIM,
           seed: int = RNG_SEED) -> dict:
    rng    = np.random.default_rng(seed)
    finals = np.empty(n_sim)
    dds    = np.empty(n_sim)
    for i in range(n_sim):
        draws = rng.choice(pool, size=n_trades, replace=True)
        eq = CAPITAL; peak = CAPITAL; mdd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > mdd:
                mdd = dd
        finals[i] = eq
        dds[i]    = mdd
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob=(finals > CAPITAL).mean(),
        dd_med=np.median(dds), dd_p95=np.percentile(dds, 95),
    )


def run_mc_comb(p1: np.ndarray, n1: int, p5: np.ndarray, n5: int,
                n_sim: int = N_SIM, seed: int = RNG_SEED) -> dict:
    rng    = np.random.default_rng(seed)
    finals = np.empty(n_sim)
    dds    = np.empty(n_sim)
    for i in range(n_sim):
        d1    = rng.choice(p1, size=n1, replace=True)
        d5    = rng.choice(p5, size=n5, replace=True)
        draws = np.concatenate([d1, d5])
        rng.shuffle(draws)
        eq = CAPITAL; peak = CAPITAL; mdd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > mdd:
                mdd = dd
        finals[i] = eq
        dds[i]    = mdd
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob=(finals > CAPITAL).mean(),
        dd_med=np.median(dds), dd_p95=np.percentile(dds, 95),
    )


print()
print(SEP)
print("  MONTE CARLO FINALE — TUTTI I FIX ATTIVI")
print("  EUR 2,500 | 1% risk | slip=0.15R | 5,000 sim | 12 mesi | raw/4")
print("  1h: 6 patt | no 03+09 ET | str>=0.60 | risk_pct<=1.5%")
print("  5m: 4 patt | 11-16 ET | no SPY/AAPL/MSFT/GOOGL/WMT")
print(SEP)
print("  Calcolo MC...")

mc1h  = run_mc(pool_1h, n_yr_1h)
mc5m  = run_mc(pool_5m, n_yr_5m)
mc_c  = run_mc_comb(pool_1h, n_yr_1h, pool_5m, n_yr_5m)

hdr = (f"  {'Scenario':<35} {'t/a':>5} {'Mediana':>9} "
       f"{'Worst5%':>9} {'ProbP':>7} {'DD med':>7} {'DD p95':>7}")
print(hdr)
print("  " + "-" * 75)
for lbl, n_yr, mc in [
    ("Solo 1h (post-fix)",         n_yr_1h,            mc1h),
    ("Solo 5m Alpaca",             n_yr_5m,            mc5m),
    ("Combinato 1h+5m",            n_yr_1h + n_yr_5m,  mc_c),
]:
    print(f"  {lbl:<35} {n_yr:>5} "
          f"{mc['med']:>8,.0f}  {mc['p05']:>8,.0f}  "
          f"{mc['prob']*100:>6.1f}%  {mc['dd_med']*100:>6.1f}%  "
          f"{mc['dd_p95']*100:>6.1f}%")

# Sensibilita' frequenza (500 sim rapide)
print()
print(SEP)
print("  SENSIBILITA' FREQUENZA (combinato, 500 sim)")
print(SEP)
print(f"  {'freq':>8}  {'t/a':>5}  {'Mediana':>9}  {'Worst5%':>9}  {'ProbP':>7}  {'DDmed':>7}")
print("  " + "-" * 58)
for div in [2, 3, 4, 6, 8, 12, 26]:
    n1 = max(1, round(n_yr_1h_raw / div))
    n5 = max(1, round(n_yr_5m_raw / div))
    mc_s = run_mc_comb(pool_1h, n1, pool_5m, n5, n_sim=500, seed=99)
    marker = " <-- realistico" if div == 8 else (" <-- raw/4" if div == 4 else "")
    print(f"  raw/{div:<3}  {n1+n5:>5}  "
          f"{mc_s['med']:>8,.0f}  {mc_s['p05']:>8,.0f}  "
          f"{mc_s['prob']*100:>6.1f}%  {mc_s['dd_med']*100:>6.1f}%{marker}")

# Break-even slippage
print()
print(SEP)
print("  BREAK-EVEN SLIPPAGE")
print(SEP)
avg1 = df1_fix["pnl_r"].mean()
avg5 = df5["pnl_r"].mean()
print(f"  1h post-fix: avg_r={avg1:+.4f}R — break-even slip={avg1:.3f}R/trade")
print(f"  5m:          avg_r={avg5:+.4f}R — break-even slip={avg5:.3f}R/trade")
print(f"  Slip attuale 0.15R: margine 1h={avg1-0.15:.3f}R  5m={avg5-0.15:.3f}R")
