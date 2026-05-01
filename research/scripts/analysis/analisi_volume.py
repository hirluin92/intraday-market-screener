"""
Analisi volume: funnel completo + test rilassamento filtri + Monte Carlo 5000 sim.
Obiettivo: aumentare trade/anno da 100 a 300-500 mantenendo avg_r > +0.50R.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

try:
    from zoneinfo import ZoneInfo
    TZ_ET = ZoneInfo("America/New_York")
except Exception:
    TZ_ET = None

PRODUCTION_PATTERNS_6 = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
})
LONG_PATS = frozenset({"double_bottom", "macd_divergence_bull", "rsi_divergence_bull"})
SHORT_PATS = frozenset({"double_top", "macd_divergence_bear", "rsi_divergence_bear"})

VALIDATED_48 = frozenset({
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
    "MU","LUNR","CAT","GS",
    "HON","ICE","CVX","DIA","VRTX",
})

VALIDATED_5M = frozenset({
    "META","NVDA","TSLA","AMD","NFLX","COIN","MSTR","HOOD","SHOP","SOFI",
    "ZS","NET","CELH","RBLX","PLTR","MDB","SMCI","DELL","NVO","LLY","MRNA",
    "NKE","TGT","SCHW","AMZN","MU","LUNR","CAT","GS",
})
PATTERNS_5M_4 = frozenset({
    "double_top","double_bottom","macd_divergence_bear","macd_divergence_bull",
})

SEP = "=" * 80
MONTHS = 30

def hour_et(ts):
    if TZ_ET is not None:
        return ts.astimezone(TZ_ET).hour
    return (ts.hour - 4) % 24

def mc(returns, freq_yr, n_sim=5000, capital=2500.0, risk=0.01, slip=0.15, label=""):
    net = np.array(returns) - slip
    net = net[net > -3]
    if len(net) == 0 or freq_yr < 1:
        return float("nan"), float("nan"), float("nan")
    caps = []
    for _ in range(n_sim):
        cap = capital
        s = np.random.choice(net, size=int(freq_yr), replace=True)
        for r in s:
            cap += cap * risk * r
            if cap <= 0:
                cap = 0
                break
        caps.append(cap)
    med = np.median(caps)
    w5 = np.percentile(caps, 5)
    prob = sum(1 for x in caps if x > capital) / n_sim * 100
    return med, w5, prob

np.random.seed(42)

# ══════════════════════════════════════════════════════════════════════════════
# CARICA DATASET GREZZO 1H
# ══════════════════════════════════════════════════════════════════════════════
raw = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
raw["hour_et"] = raw["pattern_timestamp"].apply(hour_et)
raw_sym = raw[raw["symbol"].isin(VALIDATED_48)].copy()

# ══════════════════════════════════════════════════════════════════════════════
# 1. FUNNEL COMPLETO
# ══════════════════════════════════════════════════════════════════════════════
print(SEP)
print("  1. FUNNEL COMPLETO (48 simboli validati)")
print(SEP)

steps = []
def step(label, df, filtro=""):
    n = len(df)
    n0 = steps[0][1] if steps else n
    avg = df["pnl_r"].mean() if n > 0 else float("nan")
    wr = (df["pnl_r"] > 0).mean() * 100 if n > 0 else float("nan")
    steps.append((label, n, n/n0*100 if n0>0 else 0, avg, wr, filtro))
    return df

f0 = step("Pattern raw (tutti)", raw_sym, "")
f1 = step("Solo 6 validati (no engulf)", raw_sym[raw_sym["pattern_name"].isin(PRODUCTION_PATTERNS_6)], "pattern filter")
f1e = f1.copy()
f2 = step("+ no 03:xx ET", f1e[~f1e["hour_et"].isin([3])], "FIX 8 (UK open)")
f3 = step("+ no 09:xx ET", f2[~f2["hour_et"].isin([9])], "FIX 7 (US open)")
f4 = step("+ strength [0.60, 0.80)", f3[(f3["pattern_strength"]>=0.60)&(f3["pattern_strength"]<0.80)], "FIX 6+11")
long_ok = (f4["pattern_name"].isin(LONG_PATS)) & (f4["risk_pct"] <= 3.0)
short_ok = (f4["pattern_name"].isin(SHORT_PATS)) & (f4["risk_pct"] <= 1.5)
f5 = step("+ risk_pct (L<=3%/S<=1.5%)", f4[long_ok | short_ok], "FIX 12 diff.")
if "bars_to_entry" in f5.columns:
    f6 = step("+ bars_to_entry <= 4", f5[f5["bars_to_entry"]<=4], "FIX 5")
else:
    f6 = step("+ bars_to_entry <= 4", f5, "FIX 5 (col mancante)")
f7 = step("+ entry_filled == True", f6[f6["entry_filled"]==True], "fill rate")

n0 = steps[0][1]
print(f"\n{'Step':<34} {'n':>7} {'%tot':>6} {'avg_r':>8} {'WR':>6}  Filtro")
print("-"*80)
for label, n, pct, avg, wr, filt in steps:
    avg_s = f"{avg:>+8.3f}R" if not pd.isna(avg) else "     n/a"
    wr_s = f"{wr:>5.1f}%" if not pd.isna(wr) else "   n/a"
    print(f"{label:<34} {n:>7,} {pct:>5.1f}% {avg_s} {wr_s}  {filt}")

freq_live = len(f7) / (MONTHS/12) / 4
print(f"\n  Dataset: {MONTHS} mesi. Freq live (raw/4): {freq_live:.0f} trade/anno")

# ══════════════════════════════════════════════════════════════════════════════
# 2. RILASSAMENTO SINGOLI FILTRI (base = f3 dopo pattern+ore)
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  2. RILASSAMENTO SINGOLI FILTRI (base: 6 pattern, 48 sym, no 03+09 ET)")
print(SEP)

# Base comune senza strength/risk/bars/fill
base = f3[f3["entry_filled"]==True].copy()  # solo fills per confronto omogeneo

def show_relaxation(label, sub, base_ref):
    n = len(sub)
    avg = sub["pnl_r"].mean() if n > 0 else float("nan")
    wr = (sub["pnl_r"] > 0).mean() * 100 if n > 0 else float("nan")
    extra = n - len(base_ref)
    avg_extra = sub[~sub.index.isin(base_ref.index)]["pnl_r"].mean() if extra > 0 else float("nan")
    avg_s = f"{avg:>+.3f}R" if not pd.isna(avg) else "  n/a"
    wr_s = f"{wr:.1f}%" if not pd.isna(wr) else " n/a"
    ex_s = f"{avg_extra:>+.3f}R" if not pd.isna(avg_extra) else "  n/a"
    print(f"  {label:<45} n={n:>5,}  avg_r={avg_s}  WR={wr_s}  extra_avg={ex_s}  +{extra:,}")

# BASE TIGHT (attuale)
base_tight_nofill = f4.copy()
long_ok2 = (base_tight_nofill["pattern_name"].isin(LONG_PATS)) & (base_tight_nofill["risk_pct"] <= 3.0)
short_ok2 = (base_tight_nofill["pattern_name"].isin(SHORT_PATS)) & (base_tight_nofill["risk_pct"] <= 1.5)
base_tight_nofill = base_tight_nofill[long_ok2 | short_ok2]
if "bars_to_entry" in base_tight_nofill.columns:
    base_tight_nofill = base_tight_nofill[base_tight_nofill["bars_to_entry"]<=4]
base_tight = base_tight_nofill[base_tight_nofill["entry_filled"]==True]

print(f"\n  BASE ATTUALE (TIGHT): n={len(base_tight):,}  avg_r={base_tight['pnl_r'].mean():>+.3f}R  "
      f"WR={(base_tight['pnl_r']>0).mean()*100:.1f}%\n")

# Helper: applica filtri configurabili su f1 (solo 6 pattern, 48 sym)
def apply_filters(df, hours_excl, str_lo, str_hi, risk_long, risk_short, bars_max, fill_only=True):
    d = df.copy()
    d = d[~d["hour_et"].isin(hours_excl)]
    d = d[(d["pattern_strength"] >= str_lo) & (d["pattern_strength"] < str_hi)]
    lo = d["pattern_name"].isin(LONG_PATS) & (d["risk_pct"] <= risk_long)
    sh = d["pattern_name"].isin(SHORT_PATS) & (d["risk_pct"] <= risk_short)
    d = d[lo | sh]
    if "bars_to_entry" in d.columns:
        d = d[d["bars_to_entry"] <= bars_max]
    if fill_only:
        d = d[d["entry_filled"] == True]
    return d

base_f = f1[f1["entry_filled"]==True]  # senza nessun altro filtro, per misurare singoli

print("  a) INCLUDI 09:xx ET (prima ora US):")
with09 = apply_filters(f1, [3], 0.60, 0.80, 3.0, 1.5, 4)
only09 = apply_filters(f1[f1["hour_et"]==9], [], 0.60, 0.80, 3.0, 1.5, 4)
print(f"     Con 09 inclusa: n={len(with09):,}  avg_r={with09['pnl_r'].mean():>+.3f}R")
print(f"     Solo trade 09:xx: n={len(only09):,}  avg_r={only09['pnl_r'].mean():>+.3f}R  "
      f"WR={(only09['pnl_r']>0).mean()*100:.1f}%")
if len(only09) > 0:
    print(f"     Per pattern (09:xx):")
    for pn, g in only09.groupby("pattern_name"):
        if len(g) >= 3:
            print(f"       {pn:<36} n={len(g):>4}  avg_r={g['pnl_r'].mean():>+.3f}R  WR={(g['pnl_r']>0).mean()*100:.1f}%")

print(f"\n  b) INCLUDI 03:xx ET (UK open):")
with03 = apply_filters(f1, [9], 0.60, 0.80, 3.0, 1.5, 4)
only03 = apply_filters(f1[f1["hour_et"]==3], [], 0.60, 0.80, 3.0, 1.5, 4)
print(f"     Con 03 inclusa: n={len(with03):,}  avg_r={with03['pnl_r'].mean():>+.3f}R")
print(f"     Solo trade 03:xx: n={len(only03):,}  avg_r={only03['pnl_r'].mean():>+.3f}R  "
      f"WR={(only03['pnl_r']>0).mean()*100:.1f}%")
if len(only03) > 0:
    for pn, g in only03.groupby("pattern_name"):
        if len(g) >= 3:
            print(f"       {pn:<36} n={len(g):>4}  avg_r={g['pnl_r'].mean():>+.3f}R  WR={(g['pnl_r']>0).mean()*100:.1f}%")

print(f"\n  c) ESTENDI strength a [0.50, 0.80):")
str50 = apply_filters(f1, [3,9], 0.50, 0.80, 3.0, 1.5, 4)
only_050_060 = apply_filters(f1[(f1["pattern_strength"]>=0.50)&(f1["pattern_strength"]<0.60)], [3,9], 0.50, 0.80, 3.0, 1.5, 4)
print(f"     Con [0.50,0.80): n={len(str50):,}  avg_r={str50['pnl_r'].mean():>+.3f}R")
print(f"     Solo fascia [0.50,0.60): n={len(only_050_060):,}  avg_r={only_050_060['pnl_r'].mean():>+.3f}R  "
      f"WR={(only_050_060['pnl_r']>0).mean()*100:.1f}%")

print(f"\n  d) ESTENDI cap strength a [0.60, 0.85):")
str85 = apply_filters(f1, [3,9], 0.60, 0.85, 3.0, 1.5, 4)
only_080_085 = apply_filters(f1[(f1["pattern_strength"]>=0.80)&(f1["pattern_strength"]<0.85)], [3,9], 0.60, 0.85, 3.0, 1.5, 4)
print(f"     Con [0.60,0.85): n={len(str85):,}  avg_r={str85['pnl_r'].mean():>+.3f}R")
print(f"     Solo fascia [0.80,0.85): n={len(only_080_085):,}  avg_r={only_080_085['pnl_r'].mean():>+.3f}R  "
      f"WR={(only_080_085['pnl_r']>0).mean()*100:.1f}%")
if len(only_080_085) > 0:
    for pn, g in only_080_085.groupby("pattern_name"):
        if len(g) >= 3:
            print(f"       {pn:<36} n={len(g):>4}  avg_r={g['pnl_r'].mean():>+.3f}R  WR={(g['pnl_r']>0).mean()*100:.1f}%")

print(f"\n  e) ALZA SHORT risk a 2.0%:")
risk20 = apply_filters(f1, [3,9], 0.60, 0.80, 3.0, 2.0, 4)
only_short_15_20 = f1.copy()
only_short_15_20 = only_short_15_20[~only_short_15_20["hour_et"].isin([3,9])]
only_short_15_20 = only_short_15_20[(only_short_15_20["pattern_strength"]>=0.60)&(only_short_15_20["pattern_strength"]<0.80)]
only_short_15_20 = only_short_15_20[only_short_15_20["pattern_name"].isin(SHORT_PATS)]
only_short_15_20 = only_short_15_20[(only_short_15_20["risk_pct"]>1.5)&(only_short_15_20["risk_pct"]<=2.0)]
if "bars_to_entry" in only_short_15_20.columns:
    only_short_15_20 = only_short_15_20[only_short_15_20["bars_to_entry"]<=4]
only_short_15_20 = only_short_15_20[only_short_15_20["entry_filled"]==True]
print(f"     Con SHORT<=2.0%: n={len(risk20):,}  avg_r={risk20['pnl_r'].mean():>+.3f}R")
print(f"     Solo short fascia 1.5-2.0%: n={len(only_short_15_20):,}  "
      f"avg_r={only_short_15_20['pnl_r'].mean():>+.3f}R  "
      f"WR={(only_short_15_20['pnl_r']>0).mean()*100:.1f}%" if len(only_short_15_20)>0 else "     Solo short fascia 1.5-2.0%: n=0")

print(f"\n  f) ALZA bars_to_entry a 6:")
bars6 = apply_filters(f1, [3,9], 0.60, 0.80, 3.0, 1.5, 6)
if "bars_to_entry" in f1.columns:
    only_bars_5_6 = apply_filters(f1[f1["bars_to_entry"].isin([5,6])], [3,9], 0.60, 0.80, 3.0, 1.5, 6)
    print(f"     Con bars<=6: n={len(bars6):,}  avg_r={bars6['pnl_r'].mean():>+.3f}R")
    print(f"     Solo barre 5-6: n={len(only_bars_5_6):,}  avg_r={only_bars_5_6['pnl_r'].mean():>+.3f}R  "
          f"WR={(only_bars_5_6['pnl_r']>0).mean()*100:.1f}%" if len(only_bars_5_6)>0 else "     Solo barre 5-6: n=0")
    if len(only_bars_5_6) > 0:
        for pn, g in only_bars_5_6.groupby("pattern_name"):
            if len(g) >= 3:
                print(f"       {pn:<36} n={len(g):>4}  avg_r={g['pnl_r'].mean():>+.3f}R")
else:
    print("     (bars_to_entry non disponibile)")

# ══════════════════════════════════════════════════════════════════════════════
# 3. CONFIGURAZIONI
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  3. CONFRONTO CONFIGURAZIONI")
print(SEP)

configs = {
    "TIGHT (attuale)":   dict(hours=[3,9], sl=0.60, sh=0.80, rl=3.0, rs=1.5, bars=4),
    "MEDIUM":            dict(hours=[3],   sl=0.60, sh=0.85, rl=3.0, rs=2.0, bars=6),
    "WIDE":              dict(hours=[],    sl=0.50, sh=0.85, rl=3.0, rs=2.5, bars=6),
}

print(f"\n{'Config':<22} {'n_ds':>6} {'avg_r':>8} {'WR':>6} {'t/anno':>7} {'med 12m':>9} {'w5%':>8} {'ProbP':>7}")
print("-"*80)

mc_results = {}
for name, cfg in configs.items():
    d = apply_filters(f1, cfg["hours"], cfg["sl"], cfg["sh"], cfg["rl"], cfg["rs"], cfg["bars"])
    n = len(d)
    avg = d["pnl_r"].mean()
    wr = (d["pnl_r"] > 0).mean() * 100
    freq = n / (MONTHS/12) / 4
    med, w5, prob = mc(d["pnl_r"].values, freq)
    mc_results[name] = (d, freq, med, w5, prob)
    med_s = f"EUR {med:>7,.0f}" if not pd.isna(med) else "     n/a"
    w5_s  = f"EUR {w5:>7,.0f}" if not pd.isna(w5) else "     n/a"
    print(f"  {name:<20} {n:>6,} {avg:>+8.3f}R {wr:>5.1f}% {freq:>7.0f} {med_s} {w5_s} {prob:>6.1f}%")

# ══════════════════════════════════════════════════════════════════════════════
# 4. DATASET 5M
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  4. DATASET 5M — filtri produzione")
print(SEP)

try:
    m = pd.read_csv("data/val_5m_expanded.csv", parse_dates=["pattern_timestamp"])
    m["hour_et"] = m["pattern_timestamp"].apply(hour_et)
    m_sym = m[m["symbol"].isin(VALIDATED_5M)].copy()

    print(f"\n  Dataset 5m raw: {len(m):,}  simboli={m['symbol'].nunique()}")

    mf = m_sym.copy()
    mf = mf[mf["pattern_name"].isin(PATTERNS_5M_4)]
    mf = mf[(mf["hour_et"] >= 11) & (mf["hour_et"] < 16)]
    mf = mf[(mf["pattern_strength"] >= 0.60) & (mf["pattern_strength"] < 0.80)]
    mf = mf[mf["risk_pct"] <= 1.5]
    if "bars_to_entry" in mf.columns:
        mf = mf[mf["bars_to_entry"] <= 3]
    mf = mf[mf["entry_filled"] == True]

    months_5m = 30
    freq_5m = len(mf) / (months_5m/12) / 4

    print(f"\n  5m filtrato (4 pat, 11-16ET, str[0.60,0.80), risk<=1.5%, bars<=3, filled):")
    print(f"    n={len(mf):,}  avg_r={mf['pnl_r'].mean():>+.4f}R  WR={(mf['pnl_r']>0).mean()*100:.1f}%")
    print(f"    Freq live (raw/4): {freq_5m:.0f} trade/anno")

    print(f"\n  5m per pattern:")
    for pn, g in mf.groupby("pattern_name"):
        print(f"    {pn:<36} n={len(g):>5,}  avg_r={g['pnl_r'].mean():>+.4f}R  WR={(g['pnl_r']>0).mean()*100:.1f}%")

    # 5m MEDIUM
    mf_med = m_sym.copy()
    mf_med = mf_med[mf_med["pattern_name"].isin(PATTERNS_5M_4)]
    mf_med = mf_med[(mf_med["hour_et"] >= 11) & (mf_med["hour_et"] < 16)]
    mf_med = mf_med[(mf_med["pattern_strength"] >= 0.60) & (mf_med["pattern_strength"] < 0.85)]
    mf_med = mf_med[mf_med["risk_pct"] <= 2.0]
    if "bars_to_entry" in mf_med.columns:
        mf_med = mf_med[mf_med["bars_to_entry"] <= 4]
    mf_med = mf_med[mf_med["entry_filled"] == True]
    freq_5m_med = len(mf_med) / (months_5m/12) / 4
    print(f"\n  5m MEDIUM (str<0.85, risk<=2%, bars<=4):")
    print(f"    n={len(mf_med):,}  avg_r={mf_med['pnl_r'].mean():>+.4f}R  freq={freq_5m_med:.0f}/anno")

    have_5m = True
except FileNotFoundError:
    print("  val_5m_expanded.csv non trovato — skip 5m")
    mf = pd.DataFrame(columns=["pnl_r"])
    mf_med = pd.DataFrame(columns=["pnl_r"])
    freq_5m = 0
    freq_5m_med = 0
    have_5m = False

# ══════════════════════════════════════════════════════════════════════════════
# 5. MONTE CARLO FINALE
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  5. MONTE CARLO FINALE — EUR 2,500 | 1% risk | 0.15R slip | 5,000 sim")
print(SEP)

scenarios = []

# 3 config 1h
for name, (d, freq, med, w5, prob) in mc_results.items():
    scenarios.append((f"1h {name}", d["pnl_r"].values, freq, med, w5, prob))

# 5m solo
if have_5m and len(mf) > 0:
    med5, w5_5, prob5 = mc(mf["pnl_r"].values, freq_5m)
    scenarios.append((f"5m TIGHT", mf["pnl_r"].values, freq_5m, med5, w5_5, prob5))

# Combinati 1h MEDIUM + 5m
if have_5m and len(mf_med) > 0:
    d_med = mc_results["MEDIUM"][0]
    freq_med = mc_results["MEDIUM"][1]
    combined_returns = np.concatenate([d_med["pnl_r"].values, mf_med["pnl_r"].values])
    freq_comb = freq_med + freq_5m_med
    med_c, w5_c, prob_c = mc(combined_returns, freq_comb)
    scenarios.append((f"1h MEDIUM + 5m MEDIUM", combined_returns, freq_comb, med_c, w5_c, prob_c))

    d_wide = mc_results["WIDE"][0]
    freq_wide = mc_results["WIDE"][1]
    combined_w = np.concatenate([d_wide["pnl_r"].values, mf_med["pnl_r"].values])
    freq_comb_w = freq_wide + freq_5m_med
    med_cw, w5_cw, prob_cw = mc(combined_w, freq_comb_w)
    scenarios.append((f"1h WIDE + 5m MEDIUM", combined_w, freq_comb_w, med_cw, w5_cw, prob_cw))

print(f"\n{'Scenario':<28} {'t/anno':>7} {'avg_r':>8} {'Mediana':>11} {'Worst5%':>10} {'ProbP':>7}")
print("-"*75)
for name, ret, freq, med, w5, prob in scenarios:
    avg = np.mean(ret) - 0.15
    med_s = f"EUR {med:>7,.0f}" if not pd.isna(med) else "      n/a"
    w5_s  = f"EUR {w5:>7,.0f}" if not pd.isna(w5) else "      n/a"
    prob_s = f"{prob:.1f}%" if not pd.isna(prob) else "   n/a"
    print(f"  {name:<26} {freq:>7.0f} {avg:>+8.3f}R {med_s} {w5_s} {prob_s:>7}")

# ── Breakdown per pattern nella config MEDIUM ─────────────────────────────────
print(f"\n{SEP}")
print("  DETTAGLIO CONFIG MEDIUM per pattern (avg_r, WR, n)")
print(SEP)
d_med_detail = mc_results["MEDIUM"][0]
print(f"\n{'Pattern':<36} {'n':>5} {'avg_r':>8} {'WR':>6}")
print("-"*60)
for pn, g in d_med_detail.groupby("pattern_name"):
    print(f"  {pn:<34} {len(g):>5,} {g['pnl_r'].mean():>+8.3f}R {(g['pnl_r']>0).mean()*100:>5.1f}%")

# ── Distribuzione ore nella config MEDIUM ────────────────────────────────────
print(f"\n{SEP}")
print("  DISTRIBUZIONE ORA ET nella config MEDIUM (inclusa 09:xx)")
print(SEP)
print(f"\n{'Ora ET':>7} {'n':>6} {'avg_r':>8} {'WR':>6}")
print("-"*35)
for h, g in d_med_detail.groupby("hour_et"):
    if len(g) >= 5:
        print(f"  {h:>5}:xx  {len(g):>6,} {g['pnl_r'].mean():>+8.3f}R {(g['pnl_r']>0).mean()*100:>5.1f}%")

print(f"\nFine analisi volume.")
