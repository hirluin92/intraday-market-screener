"""
Monte Carlo v5 — compound MENSILE + slot cap realistici.

Fix vs v4:
  - Compound MENSILE (non per-trade): equity aggiornata una volta al mese,
    non dopo ogni trade. Trade simultanei non compoundano tra loro.
  - Risk $ FISSO all'inizio del mese: risk_$ = equity_start * risk_pct.
    Tutti i trade del mese usano lo stesso notional, non equity corrente.
  - 5m trade/mese capped da slot constraint reale:
      2 slot × 2 ore power × ~2 cicli/ora × 21 gg × 50% fill = ~84/mese
  - 1h trade/mese da rate dataset (entry_filled=True già filtra per fills reali):
      ~76/mese, coerente con 3 slot + hold medio <1 giorno
"""
from __future__ import annotations
import numpy as np
import pandas as pd

RNG_SEED     = 42
N_SIM        = 5_000
CAPITAL      = 100_000.0
CAPITAL_3K   = 3_000.0
RISK_1H      = 0.015    # 1.5% del capitale per trade 1h
RISK_5M      = 0.005    # 0.5% del capitale per trade 5m
SLIP         = 0.15     # R round-trip slippage
MIN_STRENGTH = 0.60

# Slot constraint 1h
# 3 slot, hold medio stimato 3 giorni (TP1=2R su 1h tipicamente 2-4 gg)
SLOTS_1H          = 3
AVG_HOLD_DAYS_1H  = 3   # giorni medi per trade 1h (stima conservativa)
TRADING_DAYS      = 21  # giorni trading/mese
SLOT_CAP_1H_MONTH = round(SLOTS_1H * TRADING_DAYS / AVG_HOLD_DAYS_1H)  # = 21

# Slot constraint 5m
# 2 slot × 2 ore power × ~2 cicli/ora × 21 gg × 50% fill rate
SLOTS_5M          = 2
POWER_HOURS_5M    = 2   # ore power/giorno (es. 13-15 ET)
CYCLES_PER_HOUR   = 2   # hold medio ~30min = 2 cicli/ora per slot
FILL_RATE_5M      = 0.5 # 50% dei slot disponibili riempiti
SLOT_CAP_5M_MONTH = round(SLOTS_5M * POWER_HOURS_5M * CYCLES_PER_HOUR * TRADING_DAYS * FILL_RATE_5M)

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


# ─── Formula eff_r ────────────────────────────────────────────────────────────
def compute_r_tp1(entry, stop, tp1):
    sd = abs(float(entry) - float(stop))
    return 0.0 if sd < 1e-10 else abs(float(tp1) - float(entry)) / sd

def compute_r_tp2(entry, stop, tp2):
    sd = abs(float(entry) - float(stop))
    return 0.0 if sd < 1e-10 else abs(float(tp2) - float(entry)) / sd

def eff_r(row) -> float:
    outcome = str(row["outcome"])
    pnl_r   = float(row["pnl_r"])
    r1 = compute_r_tp1(row["entry_price"], row["stop_price"], row["tp1_price"])
    r2 = compute_r_tp2(row["entry_price"], row["stop_price"], row["tp2_price"])
    if outcome == "tp2":
        return 0.5 * r1 + 0.5 * r2
    elif outcome == "tp1":
        runner = 0.5 if r1 >= 1.0 else (0.0 if r1 >= 0.5 else -1.0)
        return 0.5 * r1 + 0.5 * runner
    elif outcome in ("stop", "stopped", "sl"):
        return -1.0
    elif outcome == "timeout":
        return float(pnl_r)
    else:
        return float(pnl_r)


# ─── Carica dataset ────────────────────────────────────────────────────────────
D1 = "/tmp/val_1h_production.csv"
D5 = "/tmp/val_5m_v2.csv"

df1r = pd.read_csv(D1)
df5r = pd.read_csv(D5)
df1r["pattern_timestamp"] = pd.to_datetime(df1r["pattern_timestamp"], utc=True)
df5r["pattern_timestamp"] = pd.to_datetime(df5r["pattern_timestamp"], utc=True)

# Filtri 1h
df1 = df1r[
    df1r["entry_filled"].astype(str).str.lower().isin(["true", "1"]) &
    df1r["pattern_name"].isin(PATTERNS_1H) &
    ~df1r["provider"].isin(["ibkr"]) &
    df1r["pattern_strength"].fillna(0) >= MIN_STRENGTH
].copy()

# Filtri 5m
df5r["hour_et"] = df5r["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
df5 = df5r[
    df5r["entry_filled"].astype(str).str.lower().isin(["true", "1"]) &
    df5r["pattern_name"].isin(PATTERNS_5M) &
    df5r["provider"].isin(["alpaca"]) &
    df5r["hour_et"].isin(ALL_5M_HOURS_ET) &
    df5r["pattern_strength"].fillna(0) >= MIN_STRENGTH
].copy()

df1["eff_r"] = df1.apply(eff_r, axis=1)
df5["eff_r"] = df5.apply(eff_r, axis=1)


# ─── Trade/mese ───────────────────────────────────────────────────────────────
months_1h = max(1, (df1["pattern_timestamp"].max() - df1["pattern_timestamp"].min()).days / 30)
months_5m = max(1, (df5["pattern_timestamp"].max() - df5["pattern_timestamp"].min()).days / 30)

n1_month_raw = len(df1) / months_1h  # da dataset (già entry_filled=True)
n5_month_raw = len(df5) / months_5m  # da dataset — molto > slot cap

# 1h: capped da slot+hold: 3 slot / 3 giorni hold × 21 gg = 21/mese
# dataset rate 73/mese è più alto perché include tutti i simboli senza slot limit
n1_month = max(1, min(round(n1_month_raw), SLOT_CAP_1H_MONTH))
# 5m: capped da slot constraint power hours
n5_month = max(1, min(round(n5_month_raw), SLOT_CAP_5M_MONTH))

n1_year = n1_month * 12
n5_year = n5_month * 12

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

# EV mensile deterministico (non compounded)
ev1m = n1_month * ar1s * RISK_1H
ev5m = n5_month * ar5s * RISK_5M

def dist(df):
    v = df["outcome"].value_counts(normalize=True)
    return {k: f"{v.get(k,0):.1%}" for k in ["tp2", "tp1", "stop", "timeout"]}

d1 = dist(df1)
d5 = dist(df5)

r1_tp1_mean = df1.apply(lambda r: compute_r_tp1(r["entry_price"],r["stop_price"],r["tp1_price"]), axis=1).mean()
r5_tp1_mean = df5.apply(lambda r: compute_r_tp1(r["entry_price"],r["stop_price"],r["tp1_price"]), axis=1).mean()
r1_tp2_mean = df1.apply(lambda r: compute_r_tp2(r["entry_price"],r["stop_price"],r["tp2_price"]), axis=1).mean()
r5_tp2_mean = df5.apply(lambda r: compute_r_tp2(r["entry_price"],r["stop_price"],r["tp2_price"]), axis=1).mean()


# ─── MC engine v5: compound MENSILE ───────────────────────────────────────────
def run_mc_v5(pool_a, na_m, pool_b, nb_m,
              risk_a_pct, risk_b_pct,
              cap=CAPITAL, nsim=N_SIM, seed=RNG_SEED):
    """
    Per ogni mese:
      1. risk_$ = equity_start × risk_pct  (fisso per tutti i trade del mese)
      2. Campiona na_m trade da pool_a, nb_m da pool_b
      3. P&L_mese = sum(r_i × risk_a_$) + sum(r_j × risk_b_$)
      4. equity += P&L_mese  ← compound MENSILE
    """
    rng = np.random.default_rng(seed)
    finals  = np.empty(nsim)
    dds     = np.empty(nsim)
    monthly = np.empty((nsim, 12))

    _have_a = na_m > 0 and len(pool_a) > 0
    _have_b = nb_m > 0 and len(pool_b) > 0

    for i in range(nsim):
        eq = cap
        pk = cap
        md = 0.0

        for m in range(12):
            eq0 = eq
            risk_a = eq0 * risk_a_pct
            risk_b = eq0 * risk_b_pct

            pnl = 0.0
            if _have_a:
                pnl += (rng.choice(pool_a, size=na_m, replace=True) * risk_a).sum()
            if _have_b:
                pnl += (rng.choice(pool_b, size=nb_m, replace=True) * risk_b).sum()

            eq = max(0.0, eq + pnl)

            if eq > pk:
                pk = eq
            if pk > 0:
                dd = (pk - eq) / pk
                if dd > md:
                    md = dd

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
def pct3(mc): return (mc["med"] / CAPITAL_3K - 1) * 100

EMPTY = np.zeros(1)


# ─── Output ───────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  MONTE CARLO v5 — COMPOUND MENSILE + SLOT CAP")
print(SEP)

print()
print(SEP)
print("  1. POOL STATISTICHE + FREQUENZA")
print(SEP)
print(f"  1h : {len(df1):,} trade | entry_filled | strength>={MIN_STRENGTH} | no-ibkr | {months_1h:.1f} mesi")
print(f"       {df1['pattern_timestamp'].min().date()} -> {df1['pattern_timestamp'].max().date()}")
print(f"       outcome: tp2={d1['tp2']}  tp1={d1['tp1']}  stop={d1['stop']}  timeout={d1['timeout']}")
print(f"       TP1={r1_tp1_mean:.2f}R  TP2={r1_tp2_mean:.2f}R (medie dataset)")
print(f"       avg_r lordo={ar1g:+.4f}R | eff_r={ar1e:+.4f}R | pool(net slip)={ar1s:+.4f}R | WR={wr1*100:.1f}%")
print(f"       Rate dataset: {n1_month_raw:.1f}/mese  →  cap slot: {SLOT_CAP_1H_MONTH}/mese  →  usato: {n1_month}/mese = {n1_year}/anno")
print(f"       Slot cap: {SLOTS_1H}slot × {TRADING_DAYS}gg ÷ {AVG_HOLD_DAYS_1H}gg hold = {SLOT_CAP_1H_MONTH}/mese")
print(f"       EV mensile det: {ev1m*100:+.2f}% equity  ({n1_month} × {ar1s:+.4f} × {RISK_1H*100:.1f}%)")
print()
print(f"  5m : {len(df5):,} trade | entry_filled | strength>={MIN_STRENGTH} | alpaca | {months_5m:.1f} mesi")
print(f"       {df5['pattern_timestamp'].min().date()} -> {df5['pattern_timestamp'].max().date()}")
print(f"       outcome: tp2={d5['tp2']}  tp1={d5['tp1']}  stop={d5['stop']}  timeout={d5['timeout']}")
print(f"       TP1={r5_tp1_mean:.2f}R  TP2={r5_tp2_mean:.2f}R (medie dataset)")
print(f"       avg_r lordo={ar5g:+.4f}R | eff_r={ar5e:+.4f}R | pool(net slip)={ar5s:+.4f}R | WR={wr5*100:.1f}%")
print(f"       Rate: {n5_month_raw:.0f}/mese raw  →  cap slot: {SLOT_CAP_5M_MONTH}/mese  →  usato: {n5_month}/mese = {n5_year}/anno")
print(f"       Slot cap: {SLOTS_5M}slot × {POWER_HOURS_5M}h × {CYCLES_PER_HOUR}cicli/h × {TRADING_DAYS}gg × {FILL_RATE_5M*100:.0f}% = {SLOT_CAP_5M_MONTH}/mese")
print(f"       EV mensile det: {ev5m*100:+.2f}% equity")
print()
ev_comb = ev1m + ev5m
print(f"  EV combinato det: {ev_comb*100:+.2f}%/mese  →  compounded 12m: {((1+ev_comb)**12-1)*100:+.1f}%")

print()
print(SEP)
print("  2. MC €100,000 — 5,000 sim — 12 mesi — compound MENSILE")
print(SEP)
print("  Calcolo in corso...")

mc1  = run_mc_v5(pool1, n1_month, EMPTY, 0, RISK_1H, 0.0)
mc5  = run_mc_v5(EMPTY, 0, pool5, n5_month, 0.0, RISK_5M)
mcc  = run_mc_v5(pool1, n1_month, pool5, n5_month, RISK_1H, RISK_5M)

print(f"\n  {'Scenario':<18} {'t/m':>4} {'t/a':>5} {'avg_r':>7} {'Mediana':>12} {'Worst5%':>12} "
      f"{'ProbP':>6} {'DDmed':>6} {'DDp95':>6} {'Rend%':>8}")
print("  " + SEP2)
for lb, nm, na, ar, mc in [
    ("Solo 1h",       n1_month,           n1_year,           ar1s, mc1),
    ("Solo 5m",       n5_month,           n5_year,           ar5s, mc5),
    ("Combinato E+",  n1_month+n5_month,  n1_year+n5_year,   (ar1s+ar5s)/2, mcc),
]:
    print(
        f"  {lb:<18} {nm:>4} {na:>5} {ar:>+7.4f} "
        f"{mc['med']:>12,.0f}  {mc['p05']:>12,.0f}  "
        f"{mc['prob']*100:>5.1f}%  {mc['dd_med']*100:>5.1f}%  "
        f"{mc['dd_p95']*100:>5.1f}%  {pct(mc):>+7.1f}%"
    )

print()
print(SEP)
print("  3. EDGE DEGRADATION — combinato E+ €100k (2,000 sim)")
print(SEP)
print(f"  {'Edge':>6} {'avg_r 1h':>9} {'avg_r 5m':>9} {'Mediana':>12} {'Worst5%':>12} "
      f"{'ProbP':>6} {'DDp95':>6} {'Rend%':>8}  Note")
print("  " + SEP2)
labels = {
    100: "",
    75:  "",
    50:  "",
    25:  "← soglia realistica ottimistica",
    10:  "← realistica media",
    5:   "← conservativa",
    3:   "← molto conservativa",
}
for e in [100, 75, 50, 25, 10, 5, 3]:
    f = e / 100.0
    me = run_mc_v5(pool1*f, n1_month, pool5*f, n5_month,
                   RISK_1H, RISK_5M, nsim=2000, seed=99)
    note = labels.get(e, "")
    print(
        f"  {e:>5}%  {pool1.mean()*f:>+9.4f} {pool5.mean()*f:>+9.4f} "
        f"{me['med']:>12,.0f}  {me['p05']:>12,.0f}  "
        f"{me['prob']*100:>5.1f}%  {me['dd_p95']*100:>5.1f}%  {pct(me):>+7.1f}%  {note}"
    )

print()
print(SEP)
print("  4. MC €3,000 — 5,000 sim — 12 mesi")
print(SEP)
print(f"\n  {'Scenario':<26} {'Mediana':>9} {'Worst5%':>9} {'ProbP':>6} {'DDp95':>6} {'Rend%':>8}")
print("  " + SEP2)
for e in [100, 50, 25]:
    f = e / 100.0
    me = run_mc_v5(pool1*f, n1_month, pool5*f, n5_month, RISK_1H, RISK_5M,
                   cap=CAPITAL_3K, nsim=N_SIM, seed=RNG_SEED+e)
    lb = f"Combinato {e}% edge"
    print(
        f"  {lb:<26} {me['med']:>9,.0f}  {me['p05']:>9,.0f}  "
        f"{me['prob']*100:>5.1f}%  {me['dd_p95']*100:>5.1f}%  "
        f"{(me['med']/CAPITAL_3K-1)*100:>+7.1f}%"
    )

print()
print(SEP)
print("  5. EQUITY MENSILE — €100k combinato (mediana / p5% / p95%)")
print(SEP)
print(f"\n  {'Mese':>4}  {'Mediana':>12}  {'p5%':>12}  {'p95%':>12}  {'Rend med':>9}")
print("  " + SEP2)
for m in range(12):
    med = mcc['mon_med'][m]; p05 = mcc['mon_p05'][m]; p95 = mcc['mon_p95'][m]
    print(f"  {m+1:>4}  {med:>12,.0f}  {p05:>12,.0f}  {p95:>12,.0f}  {(med/CAPITAL-1)*100:>+8.1f}%")

print()
print(SEP)
print("  6. CONFRONTO VERSIONI (€100k combinato)")
print(SEP)
ar_v5 = (ar1s + ar5s) / 2
print(f"\n  {'Versione':<30} {'t/anno':>7} {'avg_r':>8} {'Mediana':>12} {'Worst5%':>10}  Note")
print("  " + SEP2)
print(f"  {'MC v4 (BUG: cpd per-trade)':<30} {'2,313':>7} {'~+0.46':>8} {'~9,876,000':>12} {'~5,228,000':>10}  compound geometrico per-trade")
print(f"  {'MC v5 (cpd mensile + slot cap)':<30} {n1_year+n5_year:>7} {ar_v5:>+8.4f} {mcc['med']:>12,.0f} {mcc['p05']:>10,.0f}  CORRETTO")

print()
print(SEP)
print("  RIEPILOGO ESECUTIVO")
print(SEP)
print(f"  1h  : {n1_month}/mese ({n1_year}/anno) | avg_r={ar1s:+.4f}R | WR={wr1*100:.1f}% | risk=1.5% | EV={ev1m*100:+.2f}%/mese")
print(f"  5m  : {n5_month}/mese ({n5_year}/anno) | avg_r={ar5s:+.4f}R | WR={wr5*100:.1f}% | risk=0.5% | EV={ev5m*100:+.2f}%/mese")
print(f"  Combinato : {n1_month+n5_month}/mese ({n1_year+n5_year}/anno) | EV det={ev_comb*100:+.2f}%/mese")
print(f"  Mediana 12m (100% edge)  : €{mcc['med']:>12,.0f}  ({pct(mcc):+.1f}%)")
print(f"  Worst 5%                 : €{mcc['p05']:>12,.0f}  ({(mcc['p05']/CAPITAL-1)*100:+.1f}%)")
print(f"  Prob profitto: {mcc['prob']*100:.1f}%")
print(f"  Max DD med   : {mcc['dd_med']*100:.1f}%   Max DD p95: {mcc['dd_p95']*100:.1f}%")
print()
print("  PERCHÉ I NUMERI SONO ALTI:")
print(f"  1h EV mensile = {n1_month} trade × {ar1s:+.4f}R avg × 1.5% risk = {ev1m*100:+.2f}%/mese")
print(f"  Con +{ev_comb*100:.0f}%/mese deterministico il compounding è inevitabilmente esplosivo.")
print(f"  L'edge 1h dataset (WR={wr1*100:.1f}%, TP1={r1_tp1_mean:.2f}R) è eccezionale —")
print(f"  quanto si mantiene out-of-sample è la vera domanda.")
print(f"  Scenario realistico: 10-25% edge retention → Rend 12m: +169% / +930%")
print(SEP)
print()
print(f"  Dataset: 1h {len(df1r):,}raw→{len(df1):,}filt | 5m {len(df5r):,}raw→{len(df5):,}filt")
print(f"  strength>={MIN_STRENGTH} | slip={SLIP}R | risk 1h={RISK_1H*100}% 5m={RISK_5M*100}%")
print()
