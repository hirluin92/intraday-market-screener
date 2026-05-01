"""
Simulazione realistica con capitale €3,000 — commissioni IBKR reali, sizing effettivo.
Config: TRIPLO 6-pat + trailing C (BE@+0.50 → +0.5R@+1.0)
Nota: entry_price in USD, capitale in EUR → assume EUR≈USD (±8% error, trascurabile per l'analisi).
"""
import sys
import numpy as np
import pandas as pd

np.random.seed(42)

SEP = "=" * 80
SEP2 = "-" * 80

PATTERNS = [
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
]

# ── 1. CARICAMENTO E FILTRI ───────────────────────────────────────────────────
df5 = pd.read_csv("data/val_5m_v2.csv")
df5["pattern_timestamp"] = pd.to_datetime(df5["pattern_timestamp"], utc=True)
df5["ny_hour"] = df5["pattern_timestamp"].apply(
    lambda t: (t.hour - (4 if 3 <= t.month <= 10 else 5)) % 24
)
mask5 = (
    df5["pattern_name"].isin(PATTERNS)
    & (df5["entry_filled"] == True)
    & (df5["risk_pct"] >= 0.30)
    & ((df5["ny_hour"] == 15) | ((df5["ny_hour"] >= 11) & (df5["ny_hour"] <= 13)))
)
df5 = df5[mask5].copy()
df5["rps"] = (df5["entry_price"] - df5["stop_price"]).abs()
df5["orig_cost_r"] = 0.0015 * df5["entry_price"] / df5["rps"]
df5["gross_r"] = df5["pnl_r"] + df5["orig_cost_r"]

# Trailing Config C: BE@+0.50 → lock +0.5R@+1.0 (solo stop trades)
def trail_c_gross(row):
    if pd.isna(row["mfe_r"]) or row["outcome"] != "stop":
        return row["gross_r"]
    mfe = row["mfe_r"]
    eff = -1.0
    if mfe >= 0.50: eff = max(eff, 0.0)
    if mfe >= 1.00: eff = max(eff, 0.50)
    return eff if eff > -1.0 else row["gross_r"]

df5["trail_gross_r"] = df5.apply(trail_c_gross, axis=1)

# 1h pool (no trailing — no MFE disponibile)
df1h = pd.read_csv("data/val_1h_production.csv")
df1h = df1h[df1h["entry_filled"] == True].copy()
df1h["pattern_timestamp"] = pd.to_datetime(df1h["pattern_timestamp"], utc=True)
df1h["rps"] = (df1h["entry_price"] - df1h["stop_price"]).abs()
df1h["orig_cost_r"] = 0.0015 * df1h["entry_price"] / df1h["rps"]
df1h["gross_r"] = df1h["pnl_r"] + df1h["orig_cost_r"]
df1h["trail_gross_r"] = df1h["gross_r"]

# ── Annualizzazione ───────────────────────────────────────────────────────────
DAYS5  = (df5["pattern_timestamp"].max() - df5["pattern_timestamp"].min()).days
N5_YR  = int(len(df5) / DAYS5 * 252)
DAYS1H = (df1h["pattern_timestamp"].max() - df1h["pattern_timestamp"].min()).days
N1H_YR = int(len(df1h) / DAYS1H * 252)


# ── FUNZIONE CORE: sizing + commissioni per dato capitale ─────────────────────
def size_and_comm(df_in, capital, risk_pct, use_trail=True):
    """
    Restituisce (df_valid, n_skipped) dove df_valid ha colonne aggiuntive:
      shares, actual_risk, ibkr_comm, ibkr_comm_r, net_r, dollar_pnl
    IBKR Tiered: $0.0035/share, min $0.35/ordine, 2 ordini per trade (entry+exit).
    """
    ideal_risk = capital * risk_pct
    sh = np.floor(ideal_risk / df_in["rps"].values).astype(int)

    valid_mask = sh >= 1
    n_skip = int((~valid_mask).sum())

    df_v = df_in[valid_mask].copy()
    sh_v  = sh[valid_mask]

    # IBKR commission (round trip = entry fill + exit fill)
    comm_per_order = np.maximum(0.35, 0.0035 * sh_v)
    total_comm     = 2.0 * comm_per_order
    actual_risk    = sh_v * df_v["rps"].values
    ibkr_comm_r    = total_comm / actual_risk

    src_gross = df_v["trail_gross_r"].values if use_trail else df_v["gross_r"].values
    net_r     = src_gross - ibkr_comm_r
    dollar_pnl = net_r * actual_risk

    df_v = df_v.copy()
    df_v["shares"]      = sh_v
    df_v["actual_risk"] = actual_risk
    df_v["ibkr_comm"]   = total_comm
    df_v["ibkr_comm_r"] = ibkr_comm_r
    df_v["net_r"]       = net_r
    df_v["dollar_pnl"]  = dollar_pnl
    return df_v, n_skip


# ── MONTE CARLO con sizing reale ──────────────────────────────────────────────
def mc_real(df5_valid, df1h_valid, n5_eff, n1h_eff, n_sim=5000):
    pnl5  = df5_valid["dollar_pnl"].values
    pnl1h = df1h_valid["dollar_pnl"].values
    n5m   = max(1, n5_eff // 12)
    n1hm  = max(1, n1h_eff // 12)
    out = np.zeros(n_sim)
    for i in range(n_sim):
        yr = 0.0
        for _ in range(12):
            yr += np.random.choice(pnl5,  size=n5m,  replace=True).sum()
            yr += np.random.choice(pnl1h, size=n1hm, replace=True).sum()
        out[i] = yr
    return out


def run_for_capital(capital, risk5=0.005, risk1h=0.015, n_sim=5000):
    v5,  skip5  = size_and_comm(df5,  capital, risk5,  use_trail=True)
    v1h, skip1h = size_and_comm(df1h, capital, risk1h, use_trail=False)
    sr5  = skip5  / len(df5)
    sr1h = skip1h / len(df1h)
    eff5  = int(N5_YR  * (1 - sr5))
    eff1h = int(N1H_YR * (1 - sr1h))
    res = mc_real(v5, v1h, eff5, eff1h, n_sim=n_sim)
    avg_net5  = v5["net_r"].mean()
    avg_net1h = v1h["net_r"].mean()
    avg_comm5  = v5["ibkr_comm_r"].mean()
    avg_comm1h = v1h["ibkr_comm_r"].mean()
    avg_sh5    = v5["shares"].mean()
    return {
        "capital": capital,
        "skip5_pct": sr5 * 100,
        "skip1h_pct": sr1h * 100,
        "eff5": eff5, "eff1h": eff1h,
        "avg_net5": avg_net5, "avg_net1h": avg_net1h,
        "avg_comm5": avg_comm5, "avg_comm1h": avg_comm1h,
        "avg_sh5": avg_sh5,
        "median": np.median(res),
        "worst5": np.percentile(res, 5),
        "probP": (res > 0).mean() * 100,
        "res": res,
    }


print(SEP)
print("SIMULAZIONE CON CAPITALE REALE — IBKR Tiered commissioni")
print(SEP)
print(f"5m pool: {len(df5):,} trade | {N5_YR:,}/anno")
print(f"1h pool: {len(df1h):,} trade  | {N1H_YR:,}/anno")
print(f"Trailing: Config C (BE@+0.50 → +0.5R@+1.0) — solo 5m")
print(f"IBKR Tiered: max($0.35, $0.0035×shares) per ordine × 2 (RT)")
print()


# ══════════════════════════════════════════════════════════════════════════════
print(SEP)
print("1. SIZING REALE — €3,000")
print(SEP)

C3K = 3_000
v5_3k, skip5_3k   = size_and_comm(df5,  C3K, 0.005)
v1h_3k, skip1h_3k = size_and_comm(df1h, C3K, 0.015)

print(f"\n  5m (risk 0.5% = €{C3K*0.005:.0f}/trade):")
print(f"    Trade validi:  {len(v5_3k):,}/{len(df5):,} ({100*len(v5_3k)/len(df5):.1f}%)")
print(f"    Trade skippati: {skip5_3k:,} ({100*skip5_3k/len(df5):.1f}%) — size < 1 azione")
print(f"    Shares media:   {v5_3k['shares'].mean():.1f}  |  mediana: {v5_3k['shares'].median():.0f}")
print(f"    Notional medio: ${(v5_3k['shares']*v5_3k['entry_price']).mean():,.0f}")
print(f"    IBKR comm medio: ${v5_3k['ibkr_comm'].mean():.2f}/trade  ({v5_3k['ibkr_comm_r'].mean():.4f}R)")
print(f"    avg gross_r: {v5_3k['trail_gross_r'].mean():+.4f}R")
print(f"    avg net_r:   {v5_3k['net_r'].mean():+.4f}R")
print(f"    avg dollar:  ${v5_3k['dollar_pnl'].mean():+.2f}/trade")
print()
print(f"  1h (risk 1.5% = €{C3K*0.015:.0f}/trade):")
print(f"    Trade validi:  {len(v1h_3k):,}/{len(df1h):,} ({100*len(v1h_3k)/len(df1h):.1f}%)")
print(f"    Trade skippati: {skip1h_3k:,} ({100*skip1h_3k/len(df1h):.1f}%)")
print(f"    Shares media:   {v1h_3k['shares'].mean():.1f}  |  mediana: {v1h_3k['shares'].median():.0f}")
print(f"    IBKR comm medio: ${v1h_3k['ibkr_comm'].mean():.2f}/trade  ({v1h_3k['ibkr_comm_r'].mean():.4f}R)")
print(f"    avg gross_r: {v1h_3k['trail_gross_r'].mean():+.4f}R")
print(f"    avg net_r:   {v1h_3k['net_r'].mean():+.4f}R")
print(f"    avg dollar:  ${v1h_3k['dollar_pnl'].mean():+.2f}/trade")


# ── Distribuzione shares ──────────────────────────────────────────────────────
print()
print("  Distribuzione size 5m (€3k):")
for label, lo, hi in [
    ("1 azione",   1, 2), ("2-4 azioni",  2, 5), ("5-9 azioni",  5, 10),
    ("10-19",     10, 20), ("20-49",      20, 50), ("50+",        50, 9999),
]:
    sub = v5_3k[(v5_3k["shares"] >= lo) & (v5_3k["shares"] < hi)]
    pct = 100 * len(sub) / max(1, len(v5_3k))
    avg_r = sub["net_r"].mean() if len(sub) > 0 else float("nan")
    print(f"    {label:<10}  {len(sub):>5,}  ({pct:5.1f}%)  avg_net_r={avg_r:+.4f}R")


# ── % skip per fascia di prezzo ───────────────────────────────────────────────
print()
print("  % trade SKIPPATI per fascia prezzo — 5m @€3k (size<1 azione):")
print(f"  {'Fascia':>15}  {'n totale':>9}  {'n skip':>7}  {'% skip':>7}  {'entry_price medio':>18}")
for lo, hi, lbl in [
    (0,   50,  "< $50"),
    (50,  100, "$50-100"),
    (100, 200, "$100-200"),
    (200, 500, "$200-500"),
    (500, 9999,"$500+"),
]:
    sub_all = df5[(df5["entry_price"] >= lo) & (df5["entry_price"] < hi)]
    ideal_risk = C3K * 0.005
    sh = np.floor(ideal_risk / sub_all["rps"].values).astype(int)
    n_skip = int((sh < 1).sum())
    avg_price = sub_all["entry_price"].mean()
    print(f"  {lbl:>15}  {len(sub_all):>9,}  {n_skip:>7,}  {100*n_skip/max(1,len(sub_all)):>6.1f}%  {avg_price:>18.2f}$")


# ── Impatto TP1/TP2 split ─────────────────────────────────────────────────────
print()
print("  TP1/TP2 split — distribuzione problemi:")
for sh_thr in [1, 2, 3, 4]:
    n = (v5_3k["shares"] == sh_thr).sum()
    if n > 0:
        label = "SKIP TP2 (solo TP1)" if sh_thr == 1 else f"split: {sh_thr//2}+{sh_thr - sh_thr//2}"
        print(f"    {sh_thr} azione/i → {label}  ({n:,} trade, {100*n/len(v5_3k):.1f}%)")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("2. COMMISSIONI IBKR REALI — confronto assunzione vs realtà")
print(SEP)

print(f"\n  {'Capitale':>10}  {'risk5%€':>8}  {'avg_sh':>7}  {'comm_ass(R)':>12}  {'comm_ibkr(R)':>13}  {'overhead':>9}")
print("  " + SEP2[:70])
for cap in [3_000, 5_000, 10_000, 25_000, 50_000, 100_000]:
    v5_c, _ = size_and_comm(df5, cap, 0.005)
    if len(v5_c) == 0:
        continue
    orig_c = v5_c["orig_cost_r"].mean()
    ibkr_c = v5_c["ibkr_comm_r"].mean()
    overhead = (ibkr_c - orig_c) / max(1e-6, v5_c["trail_gross_r"].mean())
    avg_sh = v5_c["shares"].mean()
    print(
        f"  {cap:>10,}€  {cap*0.005:>8.0f}€  {avg_sh:>7.1f}  "
        f"{orig_c:>+12.4f}R  {ibkr_c:>+13.4f}R  {overhead:>+8.1%}"
    )


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("3. MONTE CARLO €3,000 — 5000 sim × 12 mesi")
print(SEP)

# Senza trailing (per confronto)
v5_3k_notr, _ = size_and_comm(df5, C3K, 0.005, use_trail=False)

eff5_3k  = int(N5_YR  * (1 - skip5_3k/len(df5)))
eff1h_3k = int(N1H_YR * (1 - skip1h_3k/len(df1h)))

print(f"\n  Trade/anno effettivi: 5m={eff5_3k:,}  1h={eff1h_3k:,} (dopo skip)")
print(f"  avg net_r 5m: {v5_3k['net_r'].mean():+.4f}R | avg net_r 1h: {v1h_3k['net_r'].mean():+.4f}R")
print()

res_notr = mc_real(v5_3k_notr, v1h_3k, eff5_3k, eff1h_3k, n_sim=5000)
res_tr   = mc_real(v5_3k, v1h_3k, eff5_3k, eff1h_3k, n_sim=5000)

hdr = f"  {'Scenario':<35}  {'Trade/y':>7}  {'avg_net_r':>10}  {'Mediana 12m':>12}  {'Worst 5%':>10}  {'ProbP':>6}"
print(hdr)
print("  " + SEP2[:80])

for label, v5, res in [
    ("Senza trailing (IBKR comm)",     v5_3k_notr, res_notr),
    ("Con trailing C (IBKR comm)",     v5_3k,      res_tr),
]:
    tot_t = eff5_3k + eff1h_3k
    avg5 = v5["net_r"].mean()
    print(
        f"  {label:<35}  {tot_t:>7,}  {avg5:>+10.4f}R  "
        f"  {np.median(res):>+11,.0f}€  {np.percentile(res,5):>+10,.0f}€  {(res>0).mean()*100:>5.1f}%"
    )

print(f"\n  Uplift trailing:  {np.median(res_tr)-np.median(res_notr):>+,.0f}€/anno (mediano)")
print(f"  Risultato mensile atteso: {np.median(res_tr)/12:>+,.0f}€/mese")
print()

# Edge degradation
print("  EDGE DEGRADATION — Con trailing, €3,000:")
v5_vals  = v5_3k["dollar_pnl"].values
v1h_vals = v1h_3k["dollar_pnl"].values
n5m  = max(1, eff5_3k  // 12)
n1hm = max(1, eff1h_3k // 12)
print(f"  {'Edge':>5}  {'Mediana':>12}  {'Worst5%':>10}  {'ProbP':>6}")
print("  " + "-" * 35)
for ef, lbl in [(1.0,"100%"), (0.5,"50%"), (0.25,"25%")]:
    out = np.zeros(5000)
    for i in range(5000):
        yr = 0.0
        for _ in range(12):
            yr += (np.random.choice(v5_vals,  size=n5m,  replace=True) * ef).sum()
            yr += (np.random.choice(v1h_vals, size=n1hm, replace=True) * ef).sum()
        out[i] = yr
    print(f"  {lbl:>5}  {np.median(out):>+12,.0f}€  {np.percentile(out,5):>+10,.0f}€  {(out>0).mean()*100:>5.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("4. SCALA MINIMA — sweep capitale completo")
print(SEP)
print()
hdr4 = (
    f"  {'Capitale':>10}  {'skip5%':>7}  {'skip1h%':>8}  {'avg_sh5':>8}  "
    f"{'comm5(R)':>9}  {'net5(R)':>9}  {'Mediana/y':>11}  {'Worst5%':>10}  {'ProbP':>6}"
)
print(hdr4)
print("  " + SEP2)

CAPITALS = [1_000, 2_000, 3_000, 5_000, 10_000, 25_000, 50_000, 100_000]

rows_scale = []
for cap in CAPITALS:
    r = run_for_capital(cap, n_sim=3000)
    rows_scale.append(r)
    flag = ""
    if r["probP"] >= 99: flag = " ★"
    if r["median"] < 0:  flag = " ✗"
    print(
        f"  {cap:>10,}€  {r['skip5_pct']:>6.1f}%  {r['skip1h_pct']:>7.1f}%  "
        f"{r['avg_sh5']:>8.1f}  {r['avg_comm5']:>+9.4f}R  {r['avg_net5']:>+9.4f}R  "
        f"  {r['median']:>+10,.0f}€  {r['worst5']:>+10,.0f}€  {r['probP']:>5.1f}%{flag}"
    )

# ── Analisi breakeven commissioni ─────────────────────────────────────────────
print()
print("  IMPATTO COMMISSIONI IBKR — % dell'edge 5m mangiata dalle commissioni aggiuntive:")
print(f"  {'Capitale':>10}  {'gross5(R)':>10}  {'net5(R)':>9}  {'comm5(R)':>10}  {'edge_loss%':>11}  {'min_size':>10}")
print("  " + "-" * 68)
for cap in CAPITALS:
    v5_c, _ = size_and_comm(df5, cap, 0.005)
    if len(v5_c) == 0:
        print(f"  {cap:>10,}€  — tutti i trade skippati —"); continue
    gros = v5_c["trail_gross_r"].mean()
    net  = v5_c["net_r"].mean()
    comm = v5_c["ibkr_comm_r"].mean()
    loss = 100 * comm / max(1e-9, gros)
    p1   = 100 * (v5_c["shares"] == 1).sum() / len(v5_c)
    p5   = 100 * (v5_c["shares"] < 5).sum() / len(v5_c)
    print(
        f"  {cap:>10,}€  {gros:>+10.4f}R  {net:>+9.4f}R  {comm:>+10.4f}R  "
        f"{loss:>10.1f}%  {p1:.0f}% 1-sh, {p5:.0f}%<5sh"
    )

# ── Analisi per fascia di prezzo e capitale ───────────────────────────────────
print()
print("  % SKIP per prezzo × capitale (5m, 0.5% risk):")
print(f"  {'Prezzo':>12}", end="")
for cap in [3_000, 5_000, 10_000, 25_000]:
    print(f"  €{cap//1000:>2}k skip%", end="")
print()
print("  " + "-" * 60)
for lo, hi, lbl in [(0,50,"<$50"),(50,100,"$50-100"),(100,200,"$100-200"),(200,500,"$200-500"),(500,9999,"$500+")]:
    sub_all = df5[(df5["entry_price"] >= lo) & (df5["entry_price"] < hi)]
    if len(sub_all) == 0:
        continue
    print(f"  {lbl:>12}", end="")
    for cap in [3_000, 5_000, 10_000, 25_000]:
        ideal = cap * 0.005
        sh = np.floor(ideal / sub_all["rps"].values).astype(int)
        pct = 100 * (sh < 1).sum() / len(sub_all)
        print(f"  {pct:>12.1f}%", end="")
    print()

# ── Soglia minima raccomandata ────────────────────────────────────────────────
print()
print(SEP)
print("CONCLUSIONI")
print(SEP)

# Trova capitale dove edge_loss < 10% e skip < 5%
for r in rows_scale:
    cap = r["capital"]
    v5_c, sk = size_and_comm(df5, cap, 0.005)
    if len(v5_c) == 0: continue
    gros = v5_c["trail_gross_r"].mean()
    comm = v5_c["ibkr_comm_r"].mean()
    loss = 100 * comm / max(1e-9, gros)
    skip = 100 * sk / len(df5)
    p90  = 100 * (v5_c["shares"] >= 5).sum() / len(v5_c)
    if loss <= 10 or cap == CAPITALS[-1]:
        print(f"  Soglia 'comm <= 10% edge': >= €{cap:,} (loss={loss:.1f}%, skip={skip:.1f}%, ≥5sh={p90:.0f}%)")
        break

print()
print("  TABELLA RIEPILOGATIVA:")
print(f"  {'Capitale':>10}  {'Trade/anno':>10}  {'avg_net_r':>10}  {'Mediana/anno':>13}  {'ProbP':>6}  {'Viabile?':>9}")
print("  " + "-" * 70)
for r in rows_scale:
    tot = r["eff5"] + r["eff1h"]
    viable = "SI ✓" if r["probP"] >= 95 and r["median"] > 0 else ("LIMIT" if r["median"] > 0 else "NO ✗")
    print(
        f"  {r['capital']:>10,}€  {tot:>10,}  {r['avg_net5']:>+10.4f}R  "
        f"  {r['median']:>+12,.0f}€  {r['probP']:>5.1f}%  {viable:>9}"
    )

print()
print("  PROBLEMI €3,000:")
v5_c3, sk3 = size_and_comm(df5, 3000, 0.005)
gros3 = v5_c3["trail_gross_r"].mean()
comm3 = v5_c3["ibkr_comm_r"].mean()
print(f"  a) Skip rate 5m: {100*sk3/len(df5):.1f}% dei trade non eseguibili (size<1)")
print(f"  b) Commissioni: {comm3:.4f}R/trade ({100*comm3/gros3:.1f}% dell'edge lordo)")
print(f"  c) TP1/TP2 split: {100*(v5_c3['shares']==1).sum()/len(v5_c3):.1f}% trade con 1 azione → TP2 skip")
print(f"  d) Spread slippage: non quantificato (rischio aggiuntivo ~0.02-0.05R per <5 azioni)")
