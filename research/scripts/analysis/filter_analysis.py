"""
Analisi filtri post-fix — val_1h_large_post_fix.csv
Autonomo: pandas + numpy, nessun import dal progetto.
"""

import pandas as pd
import numpy as np

CSV = "data/val_1h_large_post_fix.csv"
BASELINE_AVG_R = 0.2186          # avg_r globale confermato dalle analisi precedenti
MIN_TRADES_VALID = 500           # soglia statistica minima per configurazione
STRADA_A_ENGULFING_MIN_SCORE = 84.0
PATTERNS_BEAR_REGIME_ONLY = {"engulfing_bullish", "macd_divergence_bull", "rsi_divergence_bull"}

# ─── load ────────────────────────────────────────────────────────────────────
df = pd.read_csv(CSV, parse_dates=["pattern_timestamp"])
df = df[df["entry_filled"] == True].copy()
df["pq"] = pd.to_numeric(df["pattern_quality_score"], errors="coerce")
N_BASE = len(df)

SEP = "=" * 80
SEP2 = "-" * 80

def stats(sub):
    if len(sub) == 0:
        return dict(n=0, avg_r=None, wr=None, pf=None)
    n = len(sub)
    avg_r = sub["pnl_r"].mean()
    wr = (sub["pnl_r"] > 0).mean() * 100
    wins = sub.loc[sub["pnl_r"] > 0, "pnl_r"].sum()
    losses = abs(sub.loc[sub["pnl_r"] < 0, "pnl_r"].sum())
    pf = wins / losses if losses > 0 else None
    return dict(n=n, avg_r=avg_r, wr=wr, pf=pf)

def fmt_r(v):
    return f"{v:+.4f}R" if v is not None else "  N/A  "

def fmt_pf(v):
    return f"{v:.2f}" if v is not None else " N/A"

def delta(new_avg, base=BASELINE_AVG_R):
    if new_avg is None:
        return ""
    return f"({new_avg - base:+.4f}R vs base)"


# =============================================================================
print(SEP)
print("  ANALISI 1 — FILTRI CHE ELIMINANO I TRADE PEGGIORI")
print(SEP)

# ─── 1a. Per pattern_name ─────────────────────────────────────────────────────
print("\n[1a] avg_r per pattern_name")
print(f"  {'Pattern':<40} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}")
print("  " + SEP2[:72])
pn_stats = []
for pn, grp in df.groupby("pattern_name"):
    s = stats(grp)
    pn_stats.append((pn, s))
    flag = " <<< NEGATIVO" if s["avg_r"] < 0 else ""
    print(f"  {pn:<40} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}{flag}")

negative_patterns = [pn for pn, s in pn_stats if s["avg_r"] < 0]
if negative_patterns:
    after_remove = df[~df["pattern_name"].isin(negative_patterns)]
    s_after = stats(after_remove)
    s_removed = stats(df[df["pattern_name"].isin(negative_patterns)])
    print(f"\n  >>> Rimozione pattern negativi: {negative_patterns}")
    print(f"      Rimossi:    n={s_removed['n']}, avg_r={fmt_r(s_removed['avg_r'])}")
    print(f"      Rimanenti:  n={s_after['n']}, avg_r={fmt_r(s_after['avg_r'])} {delta(s_after['avg_r'])}")
else:
    print("\n  >>> Nessun pattern con avg_r negativo sull'intero dataset.")

# ─── 1b. Per direction ────────────────────────────────────────────────────────
print("\n[1b] avg_r per direction")
print(f"  {'Direction':<15} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}")
print("  " + SEP2[:50])
for d, grp in df.groupby("direction"):
    s = stats(grp)
    print(f"  {d:<15} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}")

dir_stats = {d: stats(grp) for d, grp in df.groupby("direction")}
worst_dir = min(dir_stats, key=lambda d: dir_stats[d]["avg_r"])
best_dir  = max(dir_stats, key=lambda d: dir_stats[d]["avg_r"])
if dir_stats[worst_dir]["avg_r"] < 0:
    after_dir = df[df["direction"] != worst_dir]
    s_after = stats(after_dir)
    s_rm = stats(df[df["direction"] == worst_dir])
    print(f"\n  >>> Rimozione direzione '{worst_dir}':")
    print(f"      Rimossi:    n={s_rm['n']}, avg_r={fmt_r(s_rm['avg_r'])}")
    print(f"      Rimanenti:  n={s_after['n']}, avg_r={fmt_r(s_after['avg_r'])} {delta(s_after['avg_r'])}")
else:
    print(f"\n  >>> Entrambe le direzioni positive. '{worst_dir}' e' la peggiore ma avg_r>0.")

# ─── 1c. Per signal_alignment ────────────────────────────────────────────────
print("\n[1c] avg_r per signal_alignment")
print(f"  {'Alignment':<15} {'n':>5}  {'avg_r':>9}  {'WR%':>6}")
print("  " + SEP2[:45])
for a, grp in df.groupby("signal_alignment"):
    s = stats(grp)
    print(f"  {a:<15} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%")
print("  >>> Tutti i trade nel CSV hanno signal_alignment='aligned' — variabile gia' filtrata a monte.")

# ─── 1d. Per fasce pattern_strength ──────────────────────────────────────────
print("\n[1d] avg_r per fascia pattern_strength")
print(f"  {'Fascia':<15} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}")
print("  " + SEP2[:55])
ps_bands = [(0.0, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.85), (0.85, 1.01)]
ps_results = {}
for lo, hi in ps_bands:
    sub = df[(df["pattern_strength"] >= lo) & (df["pattern_strength"] < hi)]
    s = stats(sub)
    label = f"[{lo:.2f}-{hi:.2f})"
    ps_results[(lo, hi)] = s
    flag = " <<< NEGATIVO" if s["avg_r"] is not None and s["avg_r"] < 0 else ""
    print(f"  {label:<15} {s['n']:>5}  {fmt_r(s['avg_r']) if s['n']>0 else '  N/A  ':>9}  "
          f"{s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}{flag}" if s['n'] > 0 else
          f"  {label:<15} {0:>5}  {'  N/A  ':>9}  {'  N/A':>6}  {'N/A':>5}")

# Trova il cutoff ottimale per pattern_strength
best_ps_delta = -999
best_ps_cut = None
for cut in [0.60, 0.65, 0.70, 0.75, 0.80]:
    above = df[df["pattern_strength"] >= cut]
    below = df[df["pattern_strength"] < cut]
    if len(above) < MIN_TRADES_VALID:
        continue
    s_above = stats(above)
    s_below = stats(below)
    delta_r = s_above["avg_r"] - BASELINE_AVG_R
    if delta_r > best_ps_delta:
        best_ps_delta = delta_r
        best_ps_cut = (cut, s_above, s_below)

if best_ps_cut:
    cut, s_above, s_below = best_ps_cut
    print(f"\n  >>> Cutoff ottimale pattern_strength >= {cut}:")
    print(f"      Rimossi:   n={s_below['n']}, avg_r={fmt_r(s_below['avg_r'])}")
    print(f"      Rimanenti: n={s_above['n']}, avg_r={fmt_r(s_above['avg_r'])} {delta(s_above['avg_r'])}")

# ─── 1e. Per fasce screener_score ────────────────────────────────────────────
print("\n[1e] avg_r per fascia screener_score")
print(f"  {'Fascia':<12} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}")
print("  " + SEP2[:52])
ss_vals = sorted(df["screener_score"].dropna().unique())
for v in ss_vals:
    sub = df[df["screener_score"] == v]
    s = stats(sub)
    flag = " <<< NEGATIVO" if s["avg_r"] < 0 else ""
    print(f"  score={v:<6} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}{flag}")

best_ss_delta = -999
best_ss_cut = None
for cut in [9, 10, 11]:
    above = df[df["screener_score"] >= cut]
    below = df[df["screener_score"] < cut]
    if len(above) < MIN_TRADES_VALID:
        continue
    s_above = stats(above)
    s_below = stats(below)
    delta_r = s_above["avg_r"] - BASELINE_AVG_R
    if delta_r > best_ss_delta:
        best_ss_delta = delta_r
        best_ss_cut = (cut, s_above, s_below)

if best_ss_cut:
    cut, s_above, s_below = best_ss_cut
    print(f"\n  >>> Cutoff ottimale screener_score >= {cut}:")
    print(f"      Rimossi:   n={s_below['n']}, avg_r={fmt_r(s_below['avg_r'])}")
    print(f"      Rimanenti: n={s_above['n']}, avg_r={fmt_r(s_above['avg_r'])} {delta(s_above['avg_r'])}")

# ─── 1f. Per fasce final_score ────────────────────────────────────────────────
print("\n[1f] avg_r per fascia final_score")
print(f"  {'Fascia':<12} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}")
print("  " + SEP2[:52])
fs_bands = [(49, 55), (55, 60), (60, 65), (65, 70), (70, 75), (75, 80), (80, 88)]
for lo, hi in fs_bands:
    sub = df[(df["final_score"] >= lo) & (df["final_score"] < hi)]
    s = stats(sub)
    flag = " <<< NEGATIVO" if s["n"] > 0 and s["avg_r"] < 0 else ""
    if s["n"] > 0:
        print(f"  [{lo}-{hi}):   {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}{flag}")

best_fs_delta = -999
best_fs_cut = None
for cut in [55, 60, 65, 70, 75]:
    above = df[df["final_score"] >= cut]
    below = df[df["final_score"] < cut]
    if len(above) < MIN_TRADES_VALID:
        continue
    s_above = stats(above)
    s_below = stats(below)
    delta_r = s_above["avg_r"] - BASELINE_AVG_R
    if delta_r > best_fs_delta:
        best_fs_delta = delta_r
        best_fs_cut = (cut, s_above, s_below)

if best_fs_cut:
    cut, s_above, s_below = best_fs_cut
    print(f"\n  >>> Cutoff ottimale final_score >= {cut}:")
    print(f"      Rimossi:   n={s_below['n']}, avg_r={fmt_r(s_below['avg_r'])}")
    print(f"      Rimanenti: n={s_above['n']}, avg_r={fmt_r(s_above['avg_r'])} {delta(s_above['avg_r'])}")

# ─── 1g. Per fasce pattern_quality_score ─────────────────────────────────────
print("\n[1g] avg_r per fascia pattern_quality_score (esclusi i NaN)")
df_pq = df[df["pq"].notna()].copy()
print(f"  Campione con PQ disponibile: {len(df_pq)} / {len(df)}")
print(f"  {'Fascia':<14} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}")
print("  " + SEP2[:54])
pq_bands = [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 100)]
for lo, hi in pq_bands:
    sub = df_pq[(df_pq["pq"] >= lo) & (df_pq["pq"] < hi)]
    s = stats(sub)
    if s["n"] > 0:
        flag = " <<< NEGATIVO" if s["avg_r"] < 0 else ""
        print(f"  pq=[{lo:2d}-{hi:2d}): {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}{flag}")

best_pq_delta = -999
best_pq_cut = None
for cut in [30, 40, 45, 50, 55, 60]:
    sub_pq = df_pq[df_pq["pq"] >= cut]
    sub_rm = df_pq[df_pq["pq"] < cut]
    sub_nan = df[df["pq"].isna()]  # NaN: includi o escludi?
    # scenario A: includi i NaN nei rimanenti
    combined = pd.concat([sub_pq, sub_nan])
    if len(combined) < MIN_TRADES_VALID:
        continue
    s_above = stats(combined)
    s_below = stats(sub_rm)
    delta_r = s_above["avg_r"] - BASELINE_AVG_R
    if delta_r > best_pq_delta:
        best_pq_delta = delta_r
        best_pq_cut = (cut, s_above, s_below, len(sub_nan))

if best_pq_cut:
    cut, s_above, s_below, n_nan = best_pq_cut
    print(f"\n  >>> Cutoff ottimale pq >= {cut} (NaN inclusi nel pool rimanenti = {n_nan}):")
    print(f"      Rimossi:   n={s_below['n']}, avg_r={fmt_r(s_below['avg_r'])}")
    print(f"      Rimanenti: n={s_above['n']}, avg_r={fmt_r(s_above['avg_r'])} {delta(s_above['avg_r'])}")

# ─── 1h. Per pattern × direction (crosstab) ───────────────────────────────────
print("\n[1h] avg_r per (pattern_name x direction) — sottogruppi con n >= 20")
print(f"  {'Pattern':<40} {'Dir':<10} {'n':>5}  {'avg_r':>9}  {'WR%':>6}")
print("  " + SEP2[:75])
neg_combos = []
for (pn, d), grp in df.groupby(["pattern_name", "direction"]):
    s = stats(grp)
    if s["n"] >= 20:
        flag = " <<< NEGATIVO" if s["avg_r"] < 0 else ""
        print(f"  {pn:<40} {d:<10} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%{flag}")
        if s["avg_r"] < 0:
            neg_combos.append((pn, d))

if neg_combos:
    mask_neg = df.apply(lambda r: (r["pattern_name"], r["direction"]) in neg_combos, axis=1)
    s_rm = stats(df[mask_neg])
    s_after = stats(df[~mask_neg])
    print(f"\n  >>> Rimozione combo negative: {neg_combos}")
    print(f"      Rimossi:   n={s_rm['n']}, avg_r={fmt_r(s_rm['avg_r'])}")
    print(f"      Rimanenti: n={s_after['n']}, avg_r={fmt_r(s_after['avg_r'])} {delta(s_after['avg_r'])}")


# =============================================================================
print("\n" + SEP)
print("  ANALISI 2 — COMBINAZIONI DI FILTRI (TOP 3)")
print(SEP)

# Costruisce filtri candidati sistematicamente
filter_candidates = []

# F1: rimuovi combo (pattern, direction) negative (n>=20)
if neg_combos:
    mask = ~df.apply(lambda r: (r["pattern_name"], r["direction"]) in neg_combos, axis=1)
    filter_candidates.append(("F1: rm_neg_combos", mask))

# F2: pattern_strength >= 0.70 (soglia operativa attuale)
mask_ps70 = df["pattern_strength"] >= 0.70
filter_candidates.append(("F2: strength>=0.70", mask_ps70))

# F3: pattern_strength >= 0.75
mask_ps75 = df["pattern_strength"] >= 0.75
filter_candidates.append(("F3: strength>=0.75", mask_ps75))

# F4: final_score >= 60
mask_fs60 = df["final_score"] >= 60
filter_candidates.append(("F4: final_score>=60", mask_fs60))

# F5: final_score >= 65
mask_fs65 = df["final_score"] >= 65
filter_candidates.append(("F5: final_score>=65", mask_fs65))

# F6: screener_score >= 10
mask_ss10 = df["screener_score"] >= 10
filter_candidates.append(("F6: screener>=10", mask_ss10))

# F7: screener_score >= 11
mask_ss11 = df["screener_score"] >= 11
filter_candidates.append(("F7: screener>=11", mask_ss11))

# F8: pq >= 40 (includi NaN)
mask_pq40 = (df["pq"] >= 40) | df["pq"].isna()
filter_candidates.append(("F8: pq>=40_or_nan", mask_pq40))

# F9: pq >= 50 (includi NaN)
mask_pq50 = (df["pq"] >= 50) | df["pq"].isna()
filter_candidates.append(("F9: pq>=50_or_nan", mask_pq50))

# Valuta ogni filtro singolo
print("\n[2a] Singoli filtri candidati (ordinati per avg_r, n >= 500):")
print(f"  {'Filtro':<30} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}  {'delta':>10}")
print("  " + SEP2[:75])
single_results = []
for name, mask in filter_candidates:
    sub = df[mask]
    s = stats(sub)
    if s["n"] < MIN_TRADES_VALID:
        continue
    single_results.append((name, mask, s))

single_results.sort(key=lambda x: x[2]["avg_r"], reverse=True)
for name, mask, s in single_results:
    print(f"  {name:<30} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}  {delta(s['avg_r']):>10}")

# Combinazioni a 2 filtri
print("\n[2b] Combinazioni a 2 filtri (top 8, n >= 500):")
print(f"  {'Combinazione':<45} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}  {'delta':>10}")
print("  " + SEP2[:80])
combo_results = []
top_filters = single_results[:7]  # prendi i top 7 filtri per le combo
for i in range(len(top_filters)):
    for j in range(i + 1, len(top_filters)):
        n1, m1, _ = top_filters[i]
        n2, m2, _ = top_filters[j]
        combined_mask = m1 & m2
        sub = df[combined_mask]
        s = stats(sub)
        if s["n"] < MIN_TRADES_VALID:
            continue
        combo_results.append((f"{n1} + {n2}", combined_mask, s))

combo_results.sort(key=lambda x: x[2]["avg_r"], reverse=True)
for name, mask, s in combo_results[:8]:
    print(f"  {name:<45} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}  {delta(s['avg_r']):>10}")

# Top 3 combinazioni da usare nell'analisi 3
top3_combos = combo_results[:3] if len(combo_results) >= 3 else combo_results


# =============================================================================
print("\n" + SEP)
print("  ANALISI 3 — CONFRONTO CON STRADA A ATTUALE")
print(SEP)

# Baseline
s_base = stats(df)

# Strada A: rimuovi engulfing_bullish con final_score < 84
mask_strada_a = ~(
    (df["pattern_name"] == "engulfing_bullish") &
    (df["final_score"] < STRADA_A_ENGULFING_MIN_SCORE)
)
df_sa = df[mask_strada_a]
s_sa = stats(df_sa)
n_removed_sa = N_BASE - len(df_sa)
s_removed_sa = stats(df[~mask_strada_a])

print(f"\n  Strada A logica: esegui tutti i trade TRANNE")
print(f"  engulfing_bullish con final_score < {STRADA_A_ENGULFING_MIN_SCORE}")
print(f"  Trade rimossi da Strada A: {n_removed_sa}  avg_r rimossi: {fmt_r(s_removed_sa['avg_r'])}")

# Strada A + top 3 combinazioni
configs = [
    ("Baseline (nessun filtro)",       df,   mask_strada_a | True),  # tutti
    ("Strada A (engulf score>=84)",    df_sa, None),
]
if top3_combos:
    c1_name, c1_mask, _ = top3_combos[0]
    configs.append((
        f"Strada A + {c1_name[:35]}",
        df[mask_strada_a & c1_mask],
        None,
    ))
if len(top3_combos) >= 2:
    c2_name, c2_mask, _ = top3_combos[1]
    configs.append((
        f"Strada A + {c2_name[:35]}",
        df[mask_strada_a & c2_mask],
        None,
    ))
if len(top3_combos) >= 3:
    c3_name, c3_mask, _ = top3_combos[2]
    configs.append((
        f"Strada A + {c3_name[:35]}",
        df[mask_strada_a & c3_mask],
        None,
    ))

# Aggiunge anche solo i filtri singoli migliori senza Strada A
if single_results:
    top_s = single_results[0]
    configs.append((
        f"Solo {top_s[0][:40]}",
        df[top_s[1]],
        None,
    ))

print("\n" + SEP2)
print(f"  {'Configurazione':<48} {'n':>5}  {'avg_r':>9}  {'WR%':>6}  {'PF':>5}  vs_baseline")
print("  " + SEP2[:80])

for label, sub, _ in configs:
    s = stats(sub)
    vs = f"{s['avg_r'] - BASELINE_AVG_R:+.4f}R" if s["n"] > 0 else "N/A"
    print(f"  {label:<48} {s['n']:>5}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {fmt_pf(s['pf']):>5}  {vs}")

print("\n" + SEP2)

# =============================================================================
print("\n" + SEP)
print("  TABELLA FINALE RIEPILOGATIVA")
print(SEP)
print(f"\n  {'Configurazione':<48} {'n_trade':>7}  {'avg_r':>9}  {'WR%':>6}  {'vs_base':>9}")
print("  " + SEP2[:80])

final_rows = [
    ("Baseline (tutti i trade post-fix)",     df),
    ("Strada A (engulf score>=84)",           df_sa),
]
if top3_combos:
    c1_name, c1_mask, _ = top3_combos[0]
    final_rows.append((f"Strada A + {c1_name[:36]}", df[mask_strada_a & c1_mask]))
if len(top3_combos) >= 2:
    c2_name, c2_mask, _ = top3_combos[1]
    final_rows.append((f"Strada A + {c2_name[:36]}", df[mask_strada_a & c2_mask]))
if len(top3_combos) >= 3:
    c3_name, c3_mask, _ = top3_combos[2]
    final_rows.append((f"Strada A + {c3_name[:36]}", df[mask_strada_a & c3_mask]))
if single_results:
    top_s = single_results[0]
    final_rows.append((f"Best filtro singolo: {top_s[0]}", df[top_s[1]]))

for label, sub in final_rows:
    s = stats(sub)
    vs = f"{s['avg_r'] - BASELINE_AVG_R:+.4f}R"
    too_small = " (< 500!)" if s["n"] < MIN_TRADES_VALID else ""
    print(f"  {label:<48} {s['n']:>7}  {fmt_r(s['avg_r']):>9}  {s['wr']:>5.1f}%  {vs:>9}{too_small}")

print(SEP)
print()
print("  AVVERTENZA BIAS: tutti i filtri sopra sono calcolati IN-SAMPLE sullo stesso")
print("  dataset usato per identificarli. Prima di implementarli in produzione,")
print("  fare OOS split (es. pre/post cutoff o train/test) per validare che l'edge")
print("  non sia data-snooping. I filtri piu' semplici (strength, screener_score)")
print("  sono meno a rischio di overfitting dei filtri composti.")
print(SEP)
