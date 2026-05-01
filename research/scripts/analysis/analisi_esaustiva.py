"""
Analisi esaustiva 12 dimensioni — dataset deterministici completi.
1h: val_1h_full.csv  | 5m: val_5m_expanded.csv
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
import pytz

SEP = "=" * 72

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
ET = pytz.timezone("America/New_York")
DAY = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
MESI = {1:"Gen",2:"Feb",3:"Mar",4:"Apr",5:"Mag",6:"Giu",
        7:"Lug",8:"Ago",9:"Set",10:"Ott",11:"Nov",12:"Dic"}

# ── Load ───────────────────────────────────────────────────────────────────────
df1r = pd.read_csv("data/val_1h_full.csv")
df1r["pattern_timestamp"] = pd.to_datetime(df1r["pattern_timestamp"], utc=True)
df1 = df1r[
    df1r["entry_filled"].astype(bool) &
    df1r["pattern_name"].isin(PATTERNS_1H)
].copy()

df5r = pd.read_csv("data/val_5m_expanded.csv")
df5r["pattern_timestamp"] = pd.to_datetime(df5r["pattern_timestamp"], utc=True)
df5 = df5r[
    df5r["entry_filled"].astype(bool) &
    df5r["provider"].eq("alpaca") &
    df5r["pattern_name"].isin(PATTERNS_5M) &
    ~df5r["symbol"].isin(BLOCKED_5M)
].copy()

print(SEP)
print(f"  POOL 1h: n={len(df1):,}  avg_r={df1['pnl_r'].mean():+.4f}R  "
      f"WR={(df1['pnl_r']>0).mean()*100:.1f}%")
print(f"  POOL 5m: n={len(df5):,}  avg_r={df5['pnl_r'].mean():+.4f}R  "
      f"WR={(df5['pnl_r']>0).mean()*100:.1f}%")
print(SEP)

def tbl(df, groupcol, n_min=30, sort_by_key=True):
    g = df.groupby(groupcol, observed=True)["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    if not sort_by_key:
        g = g.sort_values("avg_r", ascending=False)
    for k, row in g.iterrows():
        if row["n"] >= n_min:
            flag = " <<" if row["avg_r"] < 0 else ""
            print(f"  {str(k):24s}: n={int(row['n']):>5}  "
                  f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")


# ─────────────────────────────────────────────────────────────────────────────
# A1 — GIORNO SETTIMANA
# ─────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  A1 — GIORNO DELLA SETTIMANA")
print(SEP)
for label, df in [("1h", df1), ("5m", df5)]:
    df["_dow"] = df["pattern_timestamp"].dt.dayofweek
    print(f"  -- {label} --")
    g = df.groupby("_dow")["pnl_r"].agg(n="count", avg_r="mean",
                                          wr=lambda x: (x > 0).mean() * 100)
    for d, row in g.iterrows():
        flag = " <<" if row["avg_r"] < 0 else ""
        print(f"  {DAY[d]:5s}: n={int(row['n']):>5}  "
              f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A2 — MESE
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A2 — MESE DELL'ANNO (1h)")
print(SEP)
df1["_month"] = df1["pattern_timestamp"].dt.month
g = df1.groupby("_month")["pnl_r"].agg(n="count", avg_r="mean",
                                         wr=lambda x: (x > 0).mean() * 100)
for m, row in g.iterrows():
    flag = " <<" if row["avg_r"] < 0 else ""
    print(f"  {MESI[m]:5s}: n={int(row['n']):>5}  "
          f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")

# ─────────────────────────────────────────────────────────────────────────────
# A3 — SCREENER SCORE / VOLATILITA'
# ─────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  A3 — SCREENER SCORE (momentum bias, 1h)")
print(SEP)
ss_bins = [-200, -20, -10, -5, 0, 5, 10, 20, 200]
ss_labels = ["<-20", "-20:-10", "-10:-5", "-5:0", "0:5", "5:10", "10:20", ">20"]
df1["_ss_bin"] = pd.cut(df1["screener_score"], bins=ss_bins, labels=ss_labels)
tbl(df1, "_ss_bin", n_min=20)
print()
print("  A3b — SCREENER SCORE vs DIREZIONE (bullish vs bearish, 1h):")
df1["_dir_ss"] = df1["direction"] + "|ss" + pd.cut(
    df1["screener_score"], bins=[-200, 0, 200], labels=["neg", "pos"]
).astype(str)
tbl(df1, "_dir_ss", n_min=50, sort_by_key=False)
print()
print("  A3c — SCREENER SCORE (5m):")
df5["_ss_bin"] = pd.cut(df5["screener_score"], bins=ss_bins, labels=ss_labels)
tbl(df5, "_ss_bin", n_min=20)

# ─────────────────────────────────────────────────────────────────────────────
# A4 — DIREZIONE
# ─────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  A4 — DIREZIONE")
print(SEP)
for label, df in [("1h", df1), ("5m", df5)]:
    print(f"  -- {label} --")
    tbl(df, "direction", n_min=50)
    print()
print("  A4b — Direzione per pattern (1h):")
df1["_pat_dir"] = df1["pattern_name"] + "|" + df1["direction"]
tbl(df1, "_pat_dir", n_min=50, sort_by_key=False)

# ─────────────────────────────────────────────────────────────────────────────
# A5 — PATTERN STRENGTH
# ─────────────────────────────────────────────────────────────────────────────
print()
print(SEP)
print("  A5 — PATTERN STRENGTH (decili)")
print(SEP)
ps_bins = [i / 10 for i in range(11)]
ps_labels = [f"{i/10:.1f}-{(i+1)/10:.1f}" for i in range(10)]
for label, df in [("1h", df1), ("5m", df5)]:
    df["_ps_bin"] = pd.cut(df["pattern_strength"].clip(0, 1),
                            bins=ps_bins, labels=ps_labels, include_lowest=True)
    print(f"  -- {label} --")
    tbl(df, "_ps_bin", n_min=20)
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A6 — DISTRIBUZIONE PNL NEGATIVI
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A6 — DISTRIBUZIONE PNL_R NEGATIVI")
print(SEP)
loss_bins = [(-10, -3), (-3, -2), (-2, -1.5), (-1.5, -1.0), (-1.0, -0.5), (-0.5, 0)]
for label, df in [("1h", df1), ("5m", df5)]:
    neg = df[df["pnl_r"] < 0]
    print(f"  -- {label} -- (n negativi={len(neg):,} / {len(df):,} = "
          f"{len(neg)/len(df)*100:.1f}%)")
    for lo, hi in loss_bins:
        n = ((df["pnl_r"] >= lo) & (df["pnl_r"] < hi)).sum()
        pct = n / len(df) * 100
        flag = " <<< gap/no-stop" if lo <= -2 else ""
        print(f"  [{lo:>5.1f},{hi:>5.1f}): n={n:>5}  {pct:>5.2f}%{flag}")
    beyond = (df["pnl_r"] < -1.0).sum()
    print(f"  Oltre -1.0R:  n={beyond:>5} ({beyond/len(df)*100:.2f}%)")
    print(f"  Min pnl_r:    {df['pnl_r'].min():+.3f}R")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A7 — AUTOCORRELAZIONE SERIALE PER SIMBOLO
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A7 — AUTOCORRELAZIONE SERIALE LAG-1 PER SIMBOLO")
print("  (segnalati: |autocorr| > 0.10, n >= 30)")
print(SEP)
for label, df in [("1h", df1), ("5m", df5)]:
    found = False
    print(f"  -- {label} --")
    for sym, g in df.sort_values("pattern_timestamp").groupby("symbol"):
        if len(g) < 30:
            continue
        r = g["pnl_r"].values
        ac = np.corrcoef(r[:-1], r[1:])[0, 1]
        _, pval = scipy_stats.pearsonr(r[:-1], r[1:])
        if abs(ac) > 0.10:
            flag = " ***" if pval < 0.05 else ""
            print(f"  {sym:8s}: n={len(r):>4}  autocorr={ac:+.3f}  p={pval:.3f}{flag}")
            found = True
    if not found:
        print("  Nessun simbolo con |autocorr| > 0.10")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A8 — BEST / WORST SIMBOLI
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A8 — SIMBOLI BEST / WORST (n >= 50)")
print(SEP)
for label, df in [("1h", df1), ("5m", df5)]:
    g = df.groupby("symbol")["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    g = g[g["n"] >= 50].sort_values("avg_r", ascending=False)
    print(f"  -- {label} TOP 10 --")
    for sym, row in g.head(10).iterrows():
        print(f"  {sym:8s}: n={int(row['n']):>5}  avg_r={row['avg_r']:+.4f}R  "
              f"WR={row['wr']:>5.1f}%")
    print(f"  -- {label} BOTTOM 10 --")
    for sym, row in g.tail(10).sort_values("avg_r").iterrows():
        print(f"  {sym:8s}: n={int(row['n']):>5}  avg_r={row['avg_r']:+.4f}R  "
              f"WR={row['wr']:>5.1f}%")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A9 — ORA DEL GIORNO
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A9 — ORA DEL GIORNO (ET)")
print(SEP)
for label, df in [("1h", df1), ("5m", df5)]:
    df["_hour_et"] = df["pattern_timestamp"].dt.tz_convert(ET).dt.hour
    print(f"  -- {label} --")
    g = df.groupby("_hour_et")["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    for h, row in g.iterrows():
        if row["n"] >= 20:
            flag = " <<" if row["avg_r"] < 0 else ""
            print(f"  {h:02d}:xx ET: n={int(row['n']):>5}  "
                  f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A10 — HOLDING PERIOD
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A10 — HOLDING PERIOD (bars_to_exit)")
print(SEP)
bte_edges = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 999]
bte_labels = ["1", "2", "3", "4", "5", "6-7", "8-10", "11-15", "16-20", "21-30", "31+"]
for label, df in [("1h", df1), ("5m", df5)]:
    df["_bte"] = pd.cut(df["bars_to_exit"], bins=bte_edges, labels=bte_labels)
    print(f"  -- {label} --")
    g = df.groupby("_bte", observed=True)["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    for k, row in g.iterrows():
        if row["n"] >= 20:
            flag = " <<" if row["avg_r"] < 0 else ""
            print(f"  exit<=bar {k:>5}: n={int(row['n']):>5}  "
                  f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A11 — ENTRY BAR
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A11 — BARS_TO_ENTRY (ritardo riempimento)")
print(SEP)
ent_edges = [0, 1, 2, 3, 4, 5, 10, 20, 500]
ent_labels = ["1", "2", "3", "4", "5", "6-10", "11-20", "21+"]
for label, df in [("1h", df1), ("5m", df5)]:
    df["_bte2"] = pd.cut(df["bars_to_entry"], bins=ent_edges, labels=ent_labels)
    print(f"  -- {label} --")
    g = df.groupby("_bte2", observed=True)["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    for k, row in g.iterrows():
        if row["n"] >= 10:
            flag = " <<" if row["avg_r"] < 0 else ""
            print(f"  entry bar {k:>5}: n={int(row['n']):>5}  "
                  f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# A12 — OUTCOME
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  A12 — OUTCOME DISTRIBUTION")
print(SEP)
for label, df in [("1h", df1), ("5m", df5)]:
    print(f"  -- {label} (n={len(df):,}) --")
    g = df.groupby("outcome")["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    g["pct"] = g["n"] / len(df) * 100
    for oc, row in g.sort_values("n", ascending=False).iterrows():
        print(f"  {str(oc):12s}: n={int(row['n']):>5} ({row['pct']:>5.1f}%)  "
              f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# TABELLA FINALE FILTRI
# ─────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  TABELLA FINALE — FILTRI CANDIDATI (1h)")
print(SEP)
baseline_r = df1["pnl_r"].mean()
baseline_n = len(df1)
print(f"  Baseline: n={baseline_n:,}  avg_r={baseline_r:+.4f}R")
print()

rows = []

# Entry bar > 5
mask = df1["bars_to_entry"] > 5
r_kept = df1[~mask]["pnl_r"].mean()
rows.append(("Escludi bars_to_entry > 5", mask.sum(),
             df1[mask]["pnl_r"].mean(), r_kept, r_kept - baseline_r))

# Entry bar > 3
mask = df1["bars_to_entry"] > 3
r_kept = df1[~mask]["pnl_r"].mean()
rows.append(("Escludi bars_to_entry > 3", mask.sum(),
             df1[mask]["pnl_r"].mean(), r_kept, r_kept - baseline_r))

# Giorni negativi (solo lun-ven, escludiamo weekend)
for d, dname in enumerate(DAY[:5]):
    mask = df1["_dow"] == d
    if mask.sum() >= 50 and df1[mask]["pnl_r"].mean() < 0:
        r_kept = df1[~mask]["pnl_r"].mean()
        rows.append((f"Escludi {dname}", mask.sum(),
                     df1[mask]["pnl_r"].mean(), r_kept, r_kept - baseline_r))

# Mesi negativi
neg_months = [m for m, v in df1.groupby("_month")["pnl_r"].mean().items() if v < 0]
if neg_months:
    mask = df1["_month"].isin(neg_months)
    r_kept = df1[~mask]["pnl_r"].mean()
    rows.append((f"Escludi mesi neg {[MESI[m] for m in neg_months]}", mask.sum(),
                 df1[mask]["pnl_r"].mean(), r_kept, r_kept - baseline_r))

# Ore negative
neg_h = [h for h, row in df1.groupby("_hour_et")["pnl_r"].agg(
    n="count", avg_r="mean").iterrows()
    if row["avg_r"] < 0 and row["n"] >= 50]
if neg_h:
    mask = df1["_hour_et"].isin(neg_h)
    r_kept = df1[~mask]["pnl_r"].mean()
    rows.append((f"Escludi ore ET {neg_h}", mask.sum(),
                 df1[mask]["pnl_r"].mean(), r_kept, r_kept - baseline_r))

# Pattern strength soglia
for thr in [0.4, 0.5, 0.6]:
    mask = df1["pattern_strength"] < thr
    if mask.sum() >= 50:
        r_kept = df1[~mask]["pnl_r"].mean()
        rows.append((f"Escludi strength < {thr}", mask.sum(),
                     df1[mask]["pnl_r"].mean(), r_kept, r_kept - baseline_r))

rows.sort(key=lambda x: -x[4])
print(f"  {'Filtro':<42} {'n_rim':>7} {'avg_rim':>9} {'avg_dopo':>10} {'delta':>8}")
print("  " + "-" * 80)
for name, n_rem, avg_rem, avg_after, delta in rows:
    flag = " (***)" if delta > 0.05 else (" (**)" if delta > 0.02 else "")
    print(f"  {name:<42} {n_rem:>7,} {avg_rem:>+9.4f} {avg_after:>+10.4f} {delta:>+8.4f}{flag}")
