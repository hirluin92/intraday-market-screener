"""
Monte Carlo v4 DEFINITIVO — configurazione LIVE mag 2026.

Formula corretta:
  - Usa tp1_price e tp2_price REALI dal dataset (TP1≈2R, TP2≈3.5R)
  - Split 50/50: prima meta' a TP1, runner a TP2 con Config C trailing
  - Trailing Config C: BE@+0.5R -> +0.5R@+1.0R
  - Runner in tp1 outcome: esce a +0.5R (trailing step2 gia' applicato a TP1>=1R)
  - Stop outcome: entrambe le meta' a -1R (conservativo)
  - Filtro strength >= 0.60 (soglia live)
  - Slippage 0.15R RT
  - Frequenza: raw/4 (coerente con MC definitivo)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RNG_SEED   = 42
N_SIM      = 5_000
CAPITAL    = 100_000.0
CAPITAL_3K = 3_000.0
RISK_1H    = 0.015   # 1.5%
RISK_5M    = 0.005   # 0.5%
SLIP       = 0.15    # R round-trip
MIN_STRENGTH = 0.60  # filtro live

FREQ_FACTOR = 1 / 4.0  # raw/4

SEP  = "=" * 72
SEP2 = "-" * 72

PATTERNS_1H = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}
PATTERNS_5M = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}
ALL_5M_HOURS_ET = {11, 12, 13, 14, 15}

# ─── Formula eff_r con prezzi reali ──────────────────────────────────────────
def compute_r_tp1(entry, stop, tp1):
    sd = abs(float(entry) - float(stop))
    if sd < 1e-10:
        return 0.0
    return abs(float(tp1) - float(entry)) / sd

def compute_r_tp2(entry, stop, tp2):
    sd = abs(float(entry) - float(stop))
    if sd < 1e-10:
        return 0.0
    return abs(float(tp2) - float(entry)) / sd

def eff_r(row) -> float:
    """
    Split 50/50 + trailing Config C.

    tp2  -> 0.5*r_tp1 + 0.5*r_tp2  (entrambe le meta' al target)
    tp1  -> 0.5*r_tp1 + 0.5*runner  (runner esce a trailing stop)
             runner: se r_tp1>=1R step2 applicato -> runner stop +0.5R
                     se r_tp1>=0.5R step1 -> runner stop BE (0R)
                     altrimenti runner stop originale (-1R)
    stop -> -1R conservativo (entrambe le meta')
    timeout -> usa pnl_r come proxy
    """
    outcome = str(row["outcome"])
    pnl_r   = float(row["pnl_r"])
    r1      = compute_r_tp1(row["entry_price"], row["stop_price"], row["tp1_price"])
    r2      = compute_r_tp2(row["entry_price"], row["stop_price"], row["tp2_price"])

    if outcome == "tp2":
        return 0.5 * r1 + 0.5 * r2
    elif outcome == "tp1":
        # runner exits at trailing stop (stop moved by step2 when price was at TP1)
        runner = 0.5 if r1 >= 1.0 else (0.0 if r1 >= 0.5 else -1.0)
        return 0.5 * r1 + 0.5 * runner
    elif outcome in ("stop", "stopped", "sl"):
        return -1.0
    elif outcome == "timeout":
        return float(pnl_r)  # exit at close, use actual pnl
    else:
        return float(pnl_r)  # fallback: use original pnl


# ─── Carica dataset ────────────────────────────────────────────────────────────
D1 = "/tmp/val_1h_production.csv"
D5 = "/tmp/val_5m_v2.csv"

df1r = pd.read_csv(D1)
df5r = pd.read_csv(D5)

df1r["pattern_timestamp"] = pd.to_datetime(df1r["pattern_timestamp"], utc=True)
df5r["pattern_timestamp"] = pd.to_datetime(df5r["pattern_timestamp"], utc=True)

# ─── Filtri 1h ────────────────────────────────────────────────────────────────
df1 = df1r[
    df1r["entry_filled"].astype(str).str.lower().isin(["true", "1"]) &
    df1r["pattern_name"].isin(PATTERNS_1H) &
    ~df1r["provider"].isin(["ibkr"]) &
    df1r["pattern_strength"].fillna(0) >= MIN_STRENGTH
].copy()

# ─── Filtri 5m ────────────────────────────────────────────────────────────────
df5r["hour_et"] = df5r["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
df5 = df5r[
    df5r["entry_filled"].astype(str).str.lower().isin(["true", "1"]) &
    df5r["pattern_name"].isin(PATTERNS_5M) &
    df5r["provider"].isin(["alpaca"]) &
    df5r["hour_et"].isin(ALL_5M_HOURS_ET) &
    df5r["pattern_strength"].fillna(0) >= MIN_STRENGTH
].copy()

# ─── Calcolo eff_r ────────────────────────────────────────────────────────────
df1["eff_r"] = df1.apply(eff_r, axis=1)
df5["eff_r"] = df5.apply(eff_r, axis=1)

# ─── Frequenza ────────────────────────────────────────────────────────────────
m1 = max(1, (df1["pattern_timestamp"].max() - df1["pattern_timestamp"].min()).days / 30)
m5 = max(1, (df5["pattern_timestamp"].max() - df5["pattern_timestamp"].min()).days / 30)

n1r = round(len(df1) / m1 * 12)
n5r = round(len(df5) / m5 * 12)
n1  = max(1, round(n1r * FREQ_FACTOR))
n5  = max(1, round(n5r * FREQ_FACTOR))
nc  = n1 + n5

pool1 = (df1["eff_r"] - SLIP).values
pool5 = (df5["eff_r"] - SLIP).values

ar1g = df1["pnl_r"].mean()
ar5g = df5["pnl_r"].mean()
ar1e = df1["eff_r"].mean()
ar5e = df5["eff_r"].mean()
ar1s = pool1.mean()
ar5s = pool5.mean()
wr1  = (pool1 > 0).mean()
wr5  = (pool5 > 0).mean()

def dist(df):
    v = df["outcome"].value_counts(normalize=True)
    return {k: f"{v.get(k,0):.1%}" for k in ["tp2","tp1","stop","timeout"]}

d1 = dist(df1)
d5 = dist(df5)

# r_tp1 stats
r1_tp1_mean = df1.apply(lambda r: compute_r_tp1(r["entry_price"],r["stop_price"],r["tp1_price"]), axis=1).mean()
r5_tp1_mean = df5.apply(lambda r: compute_r_tp1(r["entry_price"],r["stop_price"],r["tp1_price"]), axis=1).mean()
r1_tp2_mean = df1.apply(lambda r: compute_r_tp2(r["entry_price"],r["stop_price"],r["tp2_price"]), axis=1).mean()
r5_tp2_mean = df5.apply(lambda r: compute_r_tp2(r["entry_price"],r["stop_price"],r["tp2_price"]), axis=1).mean()

# ─── MC engine ────────────────────────────────────────────────────────────────
def run_mc(pa, na, ra, pb, nb, rb, cap=CAPITAL, nsim=N_SIM, seed=RNG_SEED):
    rng = np.random.default_rng(seed)
    finals  = np.empty(nsim)
    dds     = np.empty(nsim)
    monthly = np.empty((nsim, 12))
    na_m = max(1, round(na / 12))
    nb_m = max(1, round(nb / 12))
    for i in range(nsim):
        eq = cap; pk = cap; md = 0.0
        for m in range(12):
            da = rng.choice(pa, size=na_m, replace=True) * ra
            db = (rng.choice(pb, size=nb_m, replace=True) * rb) if nb_m > 0 else np.zeros(1)
            draws = np.concatenate([da, db])
            rng.shuffle(draws)
            for frac in draws:
                eq *= 1.0 + frac
                if eq > pk: pk = eq
                dd = (pk - eq) / pk
                if dd > md: md = dd
            monthly[i, m] = eq
        finals[i] = eq
        dds[i]    = md
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        p95=np.percentile(finals, 95),
        prob=(finals > cap).mean(),
        dd_med=np.median(dds), dd_p95=np.percentile(dds, 95),
        mon_med=np.median(monthly, axis=0),
        mon_p05=np.percentile(monthly, 5, axis=0),
        mon_p95=np.percentile(monthly, 95, axis=0),
    )

def pct(mc, cap=CAPITAL): return (mc["med"] / cap - 1) * 100

# ─── OUTPUT ──────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  MONTE CARLO v4 DEFINITIVO — CONFIGURAZIONE LIVE mag 2026")
print(SEP)

print()
print(SEP)
print("  1. POOL STATISTICHE")
print(SEP)
print(f"  1h : {len(df1):,} trade | strength>={MIN_STRENGTH} | no-ibkr | {len(PATTERNS_1H)} pattern")
print(f"       {df1['pattern_timestamp'].min().date()} -> {df1['pattern_timestamp'].max().date()}")
print(f"       outcome: tp2={d1['tp2']} tp1={d1['tp1']} stop={d1['stop']} timeout={d1['timeout']}")
print(f"       TP1={r1_tp1_mean:.2f}R  TP2={r1_tp2_mean:.2f}R (medie dataset)")
print(f"  5m : {len(df5):,} trade | strength>={MIN_STRENGTH} | alpaca | ore ET {sorted(ALL_5M_HOURS_ET)}")
print(f"       {df5['pattern_timestamp'].min().date()} -> {df5['pattern_timestamp'].max().date()}")
print(f"       outcome: tp2={d5['tp2']} tp1={d5['tp1']} stop={d5['stop']} timeout={d5['timeout']}")
print(f"       TP1={r5_tp1_mean:.2f}R  TP2={r5_tp2_mean:.2f}R (medie dataset)")
print()
print(f"  {'Metrica':<39} {'1h':>9} {'5m TRIPLO':>11} {'Combinato':>11}")
print("  " + SEP2)
print(f"  {'n_trade (filtrato, strength>=0.60)':<39} {len(df1):>9,} {len(df5):>11,}")
print(f"  {'Trade/anno stimati (raw/4)':<39} {n1:>9} {n5:>11} {nc:>11}")
print(f"  {'avg_r lordo (pnl_r dataset)':<39} {ar1g:>+9.4f} {ar5g:>+11.4f}")
print(f"  {'avg_r eff. (split TP1/TP2 reali + C)':<39} {ar1e:>+9.4f} {ar5e:>+11.4f}")
print(f"  {'avg_r + slippage 0.15R':<39} {ar1s:>+9.4f} {ar5s:>+11.4f}")
print(f"  {'WR (post-slip, eff_r>0)':<39} {wr1*100:>8.1f}% {wr5*100:>10.1f}%")
print(f"  {'freq raw/anno':<39} {n1r:>9} {n5r:>11}")
print()
print("  NOTE: eff_r usa tp1_price/tp2_price REALI dal dataset")
print("  tp1 outcome: 0.5*r_tp1 + 0.5*(+0.5R trailing step2)")
print("  tp2 outcome: 0.5*r_tp1 + 0.5*r_tp2")
print("  stop outcome: -1R (entrambe le meta')")

print()
print(SEP)
print("  2. MONTE CARLO €100,000 — 5,000 sim — 12 mesi")
print(SEP)
print("  Calcolo in corso...")

z = np.zeros(1)
mc1  = run_mc(pool1, n1, RISK_1H, z, 0, 0.0)
mc5  = run_mc(z, 0, 0.0, pool5, n5, RISK_5M)
mcc  = run_mc(pool1, n1, RISK_1H, pool5, n5, RISK_5M)

print(f"\n  {'Scenario':<20} {'t/a':>5} {'avg_r':>7} {'Mediana €':>11} {'Worst5%€':>11} {'ProbP':>6} {'DDmed':>6} {'DDp95':>6} {'Rend%':>7}")
print("  " + SEP2)
for lb, ny, ar, mc in [
    ("Solo 1h",        n1,  ar1s, mc1),
    ("Solo 5m TRIPLO", n5,  ar5s, mc5),
    ("Combinato E+",   nc,  (ar1s+ar5s)/2, mcc),
]:
    print(
        f"  {lb:<20} {ny:>5} {ar:>+7.4f} "
        f"{mc['med']:>11,.0f}  {mc['p05']:>11,.0f}  "
        f"{mc['prob']*100:>5.1f}%  {mc['dd_med']*100:>5.1f}%  "
        f"{mc['dd_p95']*100:>5.1f}%  {pct(mc):>+6.1f}%"
    )

print()
print(SEP)
print("  3. EDGE DEGRADATION — combinato E+ €100k (2,000 sim)")
print(SEP)
print(f"\n  {'Edge':>6} {'avg_r1h':>8} {'avg_r5m':>8} {'Mediana €':>11} {'Worst5%€':>11} {'ProbP':>6} {'DDp95':>6} {'Rend%':>7}")
print("  " + SEP2)
for e in [100, 75, 50, 25, 10]:
    f = e / 100.0
    me = run_mc(pool1*f, n1, RISK_1H, pool5*f, n5, RISK_5M, nsim=2000, seed=99)
    print(
        f"  {e:>5}%  {pool1.mean()*f:>+8.4f} {pool5.mean()*f:>+8.4f} "
        f"{me['med']:>11,.0f}  {me['p05']:>11,.0f}  "
        f"{me['prob']*100:>5.1f}%  {me['dd_p95']*100:>5.1f}%  {pct(me):>+6.1f}%"
    )

print()
print(SEP)
print("  4. MONTE CARLO €3,000 — 5,000 sim — 12 mesi")
print(SEP)
print(f"\n  {'Scenario':<26} {'Mediana €':>9} {'Worst5%€':>9} {'ProbP':>6} {'DDp95':>6} {'Rend%':>7}")
print("  " + SEP2)
for e in [100, 50, 25]:
    f = e / 100.0
    me = run_mc(pool1*f, n1, RISK_1H, pool5*f, n5, RISK_5M,
                cap=CAPITAL_3K, nsim=N_SIM, seed=RNG_SEED+e)
    lb = f"Combinato E+ {e}% edge"
    print(
        f"  {lb:<26} {me['med']:>9,.0f}  {me['p05']:>9,.0f}  "
        f"{me['prob']*100:>5.1f}%  {me['dd_p95']*100:>5.1f}%  "
        f"{(me['med']/CAPITAL_3K-1)*100:>+6.1f}%"
    )

print()
print(SEP)
print("  5. EQUITY MENSILE — €100k combinato E+ (mediana, p5%, p95%)")
print(SEP)
print(f"\n  {'Mese':>4}  {'Mediana €':>11}  {'p5% €':>11}  {'p95% €':>11}  {'Rend med':>9}")
print("  " + SEP2)
for m in range(12):
    med = mcc['mon_med'][m]; p05 = mcc['mon_p05'][m]; p95 = mcc['mon_p95'][m]
    print(f"  {m+1:>4}  {med:>11,.0f}  {p05:>11,.0f}  {p95:>11,.0f}  {(med/CAPITAL-1)*100:>+8.1f}%")

print()
print(SEP)
print("  6. CONFRONTO MC VERSIONI (€100k, combinato)")
print(SEP)
ar_v4 = (ar1s + ar5s) / 2
print(f"\n  {'Versione':<26} {'avg_r combo':>12} {'Mediana 12m':>12} {'Worst5%':>10} {'Note'}")
print("  " + SEP2)
print(f"  {'MC v1 (pre-audit)':<26} {'invalido':>12} {'invalido':>12} {'invalido':>10}  dataset/filtri errati")
print(f"  {'MC v2 (post-audit)':<26} {'~+0.15R':>12} {'~107,000':>12} {'~94,000':>10}  no trailing, risk=1%")
print(f"  {'MC v3 (con trailing)':<26} {'~+0.22R':>12} {'~115,000':>12} {'~98,000':>10}  no TP2 split, risk=1%")
print(f"  {'MC v4 DEFINITIVO':<26} {ar_v4:>+12.4f} {mcc['med']:>12,.0f} {mcc['p05']:>10,.0f}  1.5%/0.5% split+C reale")

print()
print(SEP)
print("  RIEPILOGO ESECUTIVO")
print(SEP)
print(f"  1h  : {n1} t/a | avg_r={ar1s:+.4f}R | WR={wr1*100:.1f}% | risk=1.5%")
print(f"  5m  : {n5} t/a | avg_r={ar5s:+.4f}R | WR={wr5*100:.1f}% | risk=0.5%")
print(f"  Combo: {nc} t/a | E+(3+2 slot)")
print(f"  Mediana 12m  : €{mcc['med']:,.0f}  ({pct(mcc):+.1f}%)")
print(f"  Worst 5%     : €{mcc['p05']:,.0f}  ({(mcc['p05']/CAPITAL-1)*100:+.1f}%)")
print(f"  Prob. profitto: {mcc['prob']*100:.1f}%")
print(f"  Max DD p95   : {mcc['dd_p95']*100:.1f}%")
print(SEP)
print()
print(f"  Dataset: 1h {len(df1r):,}raw->{len(df1):,}filt | 5m {len(df5r):,}raw->{len(df5):,}filt")
print(f"  strength>={MIN_STRENGTH} | freq raw/4 | slip 0.15R | risk 1h=1.5% 5m=0.5%")
print()
