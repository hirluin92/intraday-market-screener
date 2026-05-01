"""
Ottimizzazione trailing stop — studio completo.
Dataset: val_5m_v2.csv | Config: TRIPLO 6-pattern
"""

import sys
import numpy as np
import pandas as pd

# ── Caricamento e filtri TRIPLO ───────────────────────────────────────────────
PATTERNS = [
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
]

df = pd.read_csv("data/val_5m_v2.csv")
df["pattern_timestamp"] = pd.to_datetime(df["pattern_timestamp"], utc=True)
df["year"] = df["pattern_timestamp"].dt.year

def ny_hour(ts):
    return (ts.hour - (4 if 3 <= ts.month <= 10 else 5)) % 24

df["ny_hour"] = df["pattern_timestamp"].apply(ny_hour)

mask = (
    df["pattern_name"].isin(PATTERNS)
    & (df["entry_filled"] == True)
    & (df["risk_pct"] >= 0.30)
    & ((df["ny_hour"] == 15) | ((df["ny_hour"] >= 11) & (df["ny_hour"] <= 13)))
)
df = df[mask].copy()

# Costo per trade in R (formula esatta)
df["cost_r"] = 0.0015 * df["entry_price"] / (df["entry_price"] - df["stop_price"]).abs()
df["cost_r"] = df["cost_r"].clip(0.01, 5.0)

# Maschere fascia oraria
alpha_mask  = df["ny_hour"] == 15
midday_mask = (df["ny_hour"] >= 11) & (df["ny_hour"] <= 13)

N = len(df)
BASE_AVG = df["pnl_r"].mean()
CAPITAL  = 100_000
RISK_PCT = 0.005
DAYS     = (df["pattern_timestamp"].max() - df["pattern_timestamp"].min()).days
N_YEAR   = int(N / DAYS * 252)
EUR_PER_R = N_YEAR * CAPITAL * RISK_PCT   # €/anno per 1R di miglioramento

print(f"Dataset TRIPLO 6-pat: {N} trade | {DAYS} giorni | {N_YEAR}/anno")
print(f"Base avg_r: {BASE_AVG:+.4f}R | €/anno per +1R: {EUR_PER_R:,.0f}€")
print()


# ── Funzione simulazione trail step-based ────────────────────────────────────
def sim_steps(df_in, steps, n_persi_pessimistic=True):
    """
    steps: [(trigger_r, dest_r), ...]
    Ottimistico per TP (no perdite premature nel calcolo avg_r).
    n_persi: conta TP con MFE>=trigger e MAE > max(0,-dest) — upper bound.
    """
    eff_stop = pd.Series(-1.0, index=df_in.index)
    for trigger, dest in sorted(steps):
        trig_mask = df_in["mfe_r"] >= trigger
        eff_stop[trig_mask] = np.maximum(eff_stop[trig_mask], dest)

    any_trail = eff_stop > -1.0

    pnl = df_in["pnl_r"].copy()
    # Stop trades salvati
    stop_saved = (df_in["outcome"] == "stop") & any_trail
    pnl[stop_saved] = eff_stop[stop_saved] - df_in["cost_r"][stop_saved] * 0.5

    n_salvati = stop_saved.sum()

    # n_persi_prem: TP trades dove MAE > soglia del nuovo stop (upper bound)
    # Per dest >= 0: soglia MAE = 0 (qualunque dip sotto entry)
    # Per dest <  0: soglia MAE = abs(dest)
    soglia_mae = eff_stop.apply(lambda d: max(0.0, -d) if d > -1.0 else 999)
    persi_mask = (
        df_in["outcome"].isin(["tp1", "tp2"])
        & any_trail
        & (df_in["mae_r"] > soglia_mae)
    )
    n_persi = persi_mask.sum()

    return pnl, n_salvati, n_persi


def sim_continuous(df_in, trail_dist=0.75):
    """Trailing continuo: stop = max(original_stop, mfe - trail_dist) in R."""
    mfe = df_in["mfe_r"]
    triggered = mfe >= trail_dist
    eff_stop = np.where(triggered, mfe - trail_dist, -1.0)

    pnl = df_in["pnl_r"].copy()
    stop_saved = (df_in["outcome"] == "stop") & triggered
    pnl[stop_saved] = pd.Series(eff_stop, index=df_in.index)[stop_saved] \
                      - df_in["cost_r"][stop_saved] * 0.5

    n_salvati = stop_saved.sum()
    # n_persi per trail continuo: MAE must exceed (eff_stop - entry in R)
    # eff_stop in R from entry = mfe_r - trail_dist (can be > 0)
    # Price falls to (entry + eff_stop*risk) from above: can't compute from MAE alone
    # → approssimazione: TP trade persi se MAE > 0 AND eff_stop <= 0
    eff_s = pd.Series(eff_stop, index=df_in.index)
    soglia = eff_s.apply(lambda d: max(0.0, -d) if d > -1.0 else 999)
    persi_mask = (
        df_in["outcome"].isin(["tp1", "tp2"])
        & triggered
        & (df_in["mae_r"] > soglia)
    )
    n_persi = persi_mask.sum()
    return pnl, n_salvati, n_persi


def delta_str(d, eur_per_r):
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.4f}R  ({sign}{d * eur_per_r:,.0f}€/y)"


SEP = "=" * 80


# ══════════════════════════════════════════════════════════════════════════════
print(SEP)
print("1. TRIGGER OTTIMALE — Trail to BE (dest=0R) vs trigger level")
print(SEP)
print("  NOTA: n_persi_prem = upper bound (assume dip post-trigger).")
print(f"  Base: {N} trade | avg_r = {BASE_AVG:+.4f}R")
print()
hdr = (
    f"  {'Trigger':>9}  {'n_salvati':>10}  {'n_persi':>8}"
    f"  {'avg_base':>10}  {'avg_trail':>10}  {'Δ':>7}  {'€/anno Δ':>10}"
)
print(hdr)
print("  " + "-" * 76)

best_trigger = None
best_delta = -999

for T in [0.25, 0.50, 0.60, 0.75, 0.85, 1.00, 1.25, 1.50]:
    steps = [(T, 0.0)]
    pnl_t, n_sal, n_per = sim_steps(df, steps)
    avg_t = pnl_t.mean()
    delta = avg_t - BASE_AVG
    eur = delta * EUR_PER_R
    flag = " ★" if delta > 0.25 else ""
    print(
        f"  +{T:.2f}R       {n_sal:>10,}  {n_per:>8,}"
        f"  {BASE_AVG:>+10.4f}R  {avg_t:>+10.4f}R  {delta:>+7.4f}R  {eur:>+10,.0f}€{flag}"
    )
    if delta > best_delta:
        best_delta = delta
        best_trigger = T

print()
print(f"  → Trigger ottimale (solo stop savings): +{best_trigger:.2f}R  (Δ = {best_delta:+.4f}R)")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("2. TRAILING MULTI-STEP")
print(SEP)

configs = {
    "A  Fisso (baseline)":               [],
    "B  BE dopo +0.75R":                 [(0.75, 0.0)],
    "C  BE@+0.50 → +0.5R@+1.0":         [(0.50, 0.0), (1.00, 0.50)],
    "D  BE@+0.75 → +0.5R@+1.25 → +1R@+1.75": [(0.75, 0.0), (1.25, 0.50), (1.75, 1.00)],
    "E  Continuo (stop = MFE - 0.75R)":  None,
}

hdr2 = (
    f"  {'Config':<42}  {'n_sal':>6}  {'n_per':>6}"
    f"  {'avg_r':>9}  {'Δ':>8}  {'€/anno Δ':>10}"
)
print(hdr2)
print("  " + "-" * 86)

pnl_best_multi = None
label_best_multi = ""
delta_best_multi = -999

for label, steps in configs.items():
    if steps is None:
        pnl_t, n_sal, n_per = sim_continuous(df, trail_dist=0.75)
    elif steps == []:
        pnl_t = df["pnl_r"].copy(); n_sal = 0; n_per = 0
    else:
        pnl_t, n_sal, n_per = sim_steps(df, steps)

    avg_t = pnl_t.mean()
    delta = avg_t - BASE_AVG
    eur = delta * EUR_PER_R
    flag = " ★" if delta > 0.25 else ""
    print(
        f"  {label:<42}  {n_sal:>6,}  {n_per:>6,}"
        f"  {avg_t:>+9.4f}R  {delta:>+8.4f}R  {eur:>+10,.0f}€{flag}"
    )
    if delta > delta_best_multi:
        delta_best_multi = delta
        label_best_multi = label
        pnl_best_multi = pnl_t

print(f"\n  → Migliore multi-step: [{label_best_multi.strip()}]  Δ={delta_best_multi:+.4f}R")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("3. TRIGGER PER FASCIA ORARIA — ALPHA (15:xx) vs MIDDAY_F (11-13)")
print(SEP)

for T in [0.50, 0.75, 1.00]:
    steps = [(T, 0.0)]
    print(f"\n  Trigger +{T:.2f}R:")
    for label, mask in [("ALPHA", alpha_mask), ("MIDDAY_F", midday_mask)]:
        sub = df[mask]
        base_avg = sub["pnl_r"].mean()
        pnl_t, n_sal, n_per = sim_steps(sub, steps)
        avg_t = pnl_t.mean()
        delta = avg_t - base_avg
        print(
            f"    {label:<10}  n={len(sub):5,}  base={base_avg:+.4f}R  "
            f"trail={avg_t:+.4f}R  Δ={delta:+.4f}R  n_sal={n_sal:,}  n_per={n_per:,}"
        )

# Trigger ottimale per fascia
print()
print("  Trigger ottimale per fascia:")
for label, mask in [("ALPHA", alpha_mask), ("MIDDAY_F", midday_mask)]:
    sub = df[mask]
    base_a = sub["pnl_r"].mean()
    best_T_a, best_d_a = None, -999
    for T in [0.25, 0.50, 0.60, 0.75, 0.85, 1.00, 1.25, 1.50]:
        pnl_t, _, _ = sim_steps(sub, [(T, 0.0)])
        d = pnl_t.mean() - base_a
        if d > best_d_a:
            best_d_a = d; best_T_a = T
    print(f"    {label:<10}: ottimale = +{best_T_a:.2f}R  Δ={best_d_a:+.4f}R")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("4. TRIGGER PER PATTERN")
print(SEP)

hdr4 = f"  {'Pattern':<24}  {'Trigger ott.':>12}  {'avg_base':>9}  {'avg_trail':>9}  {'Δ':>8}  {'n':>5}"
print(hdr4)
print("  " + "-" * 72)

for pat in PATTERNS:
    sub = df[df["pattern_name"] == pat]
    base_a = sub["pnl_r"].mean()
    best_T, best_d = None, -999
    best_trail = base_a
    for T in [0.25, 0.50, 0.60, 0.75, 0.85, 1.00, 1.25, 1.50]:
        pnl_t, _, _ = sim_steps(sub, [(T, 0.0)])
        d = pnl_t.mean() - base_a
        if d > best_d:
            best_d = d; best_T = T; best_trail = pnl_t.mean()
    flag = " ★" if best_d > 0.25 else ""
    print(
        f"  {pat:<24}  +{best_T:.2f}R          "
        f"{base_a:>+9.4f}R  {best_trail:>+9.4f}R  {best_d:>+8.4f}R  {len(sub):>5,}{flag}"
    )


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("5. DESTINAZIONE DELLO STOP — Trigger fisso +0.75R, destinazione variabile")
print(SEP)
print("  NOTA: per dest > 0 (sopra entry), n_persi non calcolabile da MAE — si usa '?'")
print()

TRIGGER_FIXED = 0.75
hdr5 = (
    f"  {'Destinazione':>32}  {'n_sal':>6}  {'n_per':>6}"
    f"  {'avg_r':>9}  {'Δ':>8}  {'€/anno Δ':>10}"
)
print(hdr5)
print("  " + "-" * 77)

best_dest_delta = -999
best_dest_label = ""
best_dest_pnl = None

dests = [
    ("Stop a -0.25R (ancora in perdita)",  TRIGGER_FIXED, -0.25),
    ("Stop a  BE  (0R, breakeven)",        TRIGGER_FIXED,  0.00),
    ("Stop a +0.25R (lock piccolo prof.)", TRIGGER_FIXED,  0.25),
    ("Stop a +0.50R (lock mezzo prof.)",   TRIGGER_FIXED,  0.50),
]

for label, trig, dest in dests:
    steps = [(trig, dest)]
    pnl_t, n_sal, n_per = sim_steps(df, steps)
    avg_t = pnl_t.mean()
    delta = avg_t - BASE_AVG
    eur = delta * EUR_PER_R

    if dest >= 0:
        n_per_str = "?"   # MAE non misura dip sopra entry
    else:
        n_per_str = str(n_per)

    flag = " ★" if delta == max(
        [sim_steps(df, [(trig, d)], )[0].mean() - BASE_AVG for _, _, d in dests]
    ) else ""
    print(
        f"  {label:<32}  {n_sal:>6,}  {n_per_str:>6}"
        f"  {avg_t:>+9.4f}R  {delta:>+8.4f}R  {eur:>+10,.0f}€"
    )
    if delta > best_dest_delta:
        best_dest_delta = delta; best_dest_label = label; best_dest_pnl = pnl_t

print(f"\n  → Destinazione ottimale: [{best_dest_label.strip()}]  Δ={best_dest_delta:+.4f}R")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)

# Determina la config migliore complessiva (da sezione 2)
BEST_STEPS_LABEL = label_best_multi.strip()
# trova steps corrispondenti
best_steps_map = {
    "B  BE dopo +0.75R":    [(0.75, 0.0)],
    "C  BE@+0.50 → +0.5R@+1.0":  [(0.50, 0.0), (1.00, 0.50)],
    "D  BE@+0.75 → +0.5R@+1.25 → +1R@+1.75": [(0.75, 0.0), (1.25, 0.50), (1.75, 1.00)],
    "E  Continuo (stop = MFE - 0.75R)": None,
}
BEST_STEPS_KEY = None
for k in best_steps_map:
    if k in BEST_STEPS_LABEL:
        BEST_STEPS_KEY = k; break

if BEST_STEPS_KEY and best_steps_map[BEST_STEPS_KEY] is not None:
    BEST_STEPS = best_steps_map[BEST_STEPS_KEY]
    label_oos = BEST_STEPS_LABEL
else:
    # default a B (BE @0.75)
    BEST_STEPS = [(0.75, 0.0)]
    label_oos = "B  BE dopo +0.75R"

print(f"6. STABILITÀ OOS — Config ottimale: [{label_oos.strip()}]")
print(SEP)

hdr6 = f"  {'Anno':>5}  {'n':>5}  {'avg_r base':>11}  {'avg_r trail':>12}  {'Δ':>9}  {'Stabile?':>9}"
print(hdr6)
print("  " + "-" * 57)

for yr in sorted(df["year"].unique()):
    sub = df[df["year"] == yr]
    base_a = sub["pnl_r"].mean()
    pnl_t, _, _ = sim_steps(sub, BEST_STEPS)
    trail_a = pnl_t.mean()
    delta = trail_a - base_a
    stabile = "SI ✓" if delta > 0 else "NO ✗"
    print(f"  {yr:>5}  {len(sub):>5,}  {base_a:>+11.4f}R  {trail_a:>+12.4f}R  {delta:>+9.4f}R  {stabile:>9}")

print()
# Stabilità per fascia
for label, mask in [("ALPHA", alpha_mask), ("MIDDAY_F", midday_mask)]:
    sub = df[mask]
    base_a = sub["pnl_r"].mean()
    pnl_t, _, _ = sim_steps(sub, BEST_STEPS)
    print(f"  {label}: base={base_a:+.4f}R  trail={pnl_t.mean():+.4f}R  Δ={pnl_t.mean()-base_a:+.4f}R")


# ══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("7. MONTE CARLO FINALE — 1h + 5m TRIPLO con trailing ottimale")
print(SEP)

import pandas as _pd
import numpy as _np

_np.random.seed(42)

# 5m pool base e trail ottimale
pool5_base  = df["pnl_r"].values
pnl_opt, _, _ = sim_steps(df, BEST_STEPS)
pool5_trail = pnl_opt.values

# 1h pool
df1h = _pd.read_csv("data/val_1h_production.csv")
df1h_f = df1h[df1h["entry_filled"] == True]
pool1h = df1h_f["pnl_r"].values
days1h = (_pd.to_datetime(df1h_f["pattern_timestamp"], utc=True).max()
          - _pd.to_datetime(df1h_f["pattern_timestamp"], utc=True).min()).days
N1H_YEAR = int(len(df1h_f) / days1h * 252)
N5_YEAR  = N_YEAR

CAPITAL_MC = 100_000
RISK_5M    = 0.005
RISK_1H    = 0.015
N_SIM      = 5_000

RISK5_EUR  = CAPITAL_MC * RISK_5M
RISK1H_EUR = CAPITAL_MC * RISK_1H

def mc(pool5, pool1h_arr, n5, n1h, edge=1.0, n_sim=N_SIM):
    r5  = RISK5_EUR  * edge
    r1h = RISK1H_EUR * edge
    totals = _np.zeros(n_sim)
    for i in range(n_sim):
        d5 = _np.random.choice(pool5,      size=n5,  replace=True)
        d1 = _np.random.choice(pool1h_arr, size=n1h, replace=True)
        totals[i] = d5.sum() * r5 + d1.sum() * r1h
    return totals

print(f"\n  Pool 5m: {len(pool5_base)} trade | ~{N5_YEAR}/anno")
print(f"  Pool 1h: {len(pool1h)} trade  | ~{N1H_YEAR}/anno")
print(f"  Capital: €{CAPITAL_MC:,} | risk 5m=0.5% (€{RISK5_EUR:,}/trade) | risk 1h=1.5% (€{RISK1H_EUR:,}/trade)")
print()

hdr_mc = (
    f"  {'Scenario':<40}  {'Trade/y':>7}  {'avg_r':>8}"
    f"  {'Mediana 12m':>12}  {'Worst 5%':>10}  {'ProbP':>6}"
)
print(hdr_mc)
print("  " + "-" * 88)

scenarios_mc = [
    ("Senza trailing",        pool5_base),
    (f"Trail ottimale [{label_oos.strip()[:12]}]", pool5_trail),
]

res_list = []
for label, pool5 in scenarios_mc:
    avg5 = pool5.mean(); avg1h = pool1h.mean()
    tot_t = N5_YEAR + N1H_YEAR
    avg_combo = (avg5 * N5_YEAR * RISK5_EUR + avg1h * N1H_YEAR * RISK1H_EUR)
    res = mc(pool5, pool1h, N5_YEAR, N1H_YEAR)
    med = _np.median(res); w5 = _np.percentile(res, 5); pp = (res > 0).mean() * 100
    res_list.append(res)
    print(
        f"  {label:<40}  {tot_t:>7,}  {avg5:>+8.4f}R"
        f"  {med:>+12,.0f}€  {w5:>+10,.0f}€  {pp:>5.1f}%"
    )

print(f"\n  Uplift mediano:  {_np.median(res_list[1]) - _np.median(res_list[0]):>+,.0f}€/anno")
print(f"  Uplift worst5%: {_np.percentile(res_list[1],5) - _np.percentile(res_list[0],5):>+,.0f}€/anno")
print()

print("  EDGE DEGRADATION — trailing ottimale:")
hdr_ed = f"  {'Edge':>5}  {'Mediana 12m':>12}  {'Worst 5%':>10}  {'ProbP':>5}"
print(hdr_ed)
print("  " + "-" * 36)
for ef, lbl in [(1.0, "100%"), (0.50, "50%"), (0.25, "25%")]:
    res = mc(pool5_trail, pool1h, N5_YEAR, N1H_YEAR, edge=ef)
    print(
        f"  {lbl:>5}  {_np.median(res):>+12,.0f}€  "
        f"{_np.percentile(res,5):>+10,.0f}€  {(res>0).mean()*100:>5.1f}%"
    )

print()
print(SEP)
print("RIEPILOGO")
print(SEP)
pnl_best_b, _, _ = sim_steps(df, [(0.75, 0.0)])
pnl_cont,  _, _ = sim_continuous(df, 0.75)
print(f"  Baseline (nessun trail):         avg_r = {BASE_AVG:+.4f}R")
print(f"  B  BE dopo +0.75R:               avg_r = {pnl_best_b.mean():+.4f}R  Δ={pnl_best_b.mean()-BASE_AVG:+.4f}R")
pnl_c, _, _ = sim_steps(df, [(0.50, 0.0), (1.00, 0.50)])
pnl_d, _, _ = sim_steps(df, [(0.75, 0.0), (1.25, 0.50), (1.75, 1.00)])
print(f"  C  BE@+0.50 → +0.5R@+1.0:       avg_r = {pnl_c.mean():+.4f}R  Δ={pnl_c.mean()-BASE_AVG:+.4f}R")
print(f"  D  BE@+0.75 → +0.5R@+1.25 → …:  avg_r = {pnl_d.mean():+.4f}R  Δ={pnl_d.mean()-BASE_AVG:+.4f}R")
print(f"  E  Continuo (MFE-0.75R):         avg_r = {pnl_cont.mean():+.4f}R  Δ={pnl_cont.mean()-BASE_AVG:+.4f}R")
print()
print(f"  Config raccomandata: [{label_oos.strip()}]")
print(f"  Trigger ottimale globale: +{best_trigger:.2f}R → BE")
