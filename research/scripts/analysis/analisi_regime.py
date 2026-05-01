"""
Analisi critica: pattern × regime REALE (SPY 1d EMA50 da DB).
Usa val_1h_production.csv + spy_1d.csv (estratto dal DB).
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

SEP = "=" * 80

PATTERNS_BEAR_ONLY = frozenset({"engulfing_bullish", "macd_divergence_bull", "rsi_divergence_bull"})
PATTERNS_SHORT_UNIV = frozenset({"macd_divergence_bear", "rsi_divergence_bear"})
PATTERNS_UNIV = frozenset({"double_bottom", "double_top"})

ALL_PATTERNS = [
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
    "engulfing_bullish",
]

# ── Carica SPY 1d e calcola EMA50 ────────────────────────────────────────────
spy = pd.read_csv("data/spy_1d.csv", parse_dates=["day"])
spy = spy.sort_values("day").drop_duplicates("day").reset_index(drop=True)
spy["ema50"] = spy["close"].ewm(span=50, adjust=False).mean()
spy["pct_vs_ema"] = (spy["close"] - spy["ema50"]) / spy["ema50"] * 100
spy["regime"] = spy["pct_vs_ema"].apply(
    lambda x: "BULL" if x > 2.0 else ("BEAR" if x < -2.0 else "NEUTRAL")
)

print(SEP)
print("  SPY REGIME — distribuzione nel dataset")
print(SEP)
rc = spy["regime"].value_counts()
for r, n in rc.items():
    pct_ema = spy[spy["regime"]==r]["pct_vs_ema"].mean()
    print(f"  {r:<8}: {n:>4} giorni ({n/len(spy)*100:.1f}%)  pct_ema medio={pct_ema:>+.1f}%")
print(f"  Totale: {len(spy)} giorni  [{spy['day'].min().date()} a {spy['day'].max().date()}]")

# Build dict: date → regime
spy_map = dict(zip(spy["day"].dt.date, spy["regime"]))
spy_pct_map = dict(zip(spy["day"].dt.date, spy["pct_vs_ema"]))

# ── Carica dataset produzione ─────────────────────────────────────────────────
prod = pd.read_csv("data/val_1h_production.csv", parse_dates=["pattern_timestamp"])
prod["date"] = prod["pattern_timestamp"].dt.date
prod["regime"] = prod["date"].map(spy_map)

# Quanti trade non matchano (date fuori range SPY)
no_match = prod["regime"].isna().sum()
prod = prod.dropna(subset=["regime"]).copy()
print(f"\n  Dataset produzione: {len(prod):,} trade con regime assegnato ({no_match} senza match)")

# Distribuzione regime nel dataset produzione
print(f"\n  Regime nei trade produzione:")
for r in ["BULL","NEUTRAL","BEAR"]:
    n = (prod["regime"]==r).sum()
    print(f"  {r:<8}: {n:>5,} trade ({n/len(prod)*100:.1f}%)")

# ══════════════════════════════════════════════════════════════════════════════
# ANALISI 1 — Ogni pattern per regime REALE
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 1 — avg_r per PATTERN × REGIME REALE")
print(SEP)

def regime_stats(g):
    if len(g) == 0:
        return "  n/a      n/a  "
    return f"{len(g):>5,}  {g['pnl_r'].mean():>+.3f}R  {(g['pnl_r']>0).mean()*100:>4.0f}%"

print(f"\n{'Pattern':<36} {'BULL (n/avg_r/WR)':>22} {'BEAR (n/avg_r/WR)':>22} {'NEUT (n/avg_r/WR)':>22}  {'Conf':<12}")
print("-" * 110)

pattern_regime_data = {}
for pn in ALL_PATTERNS:
    g = prod[prod["pattern_name"] == pn]
    gb = g[g["regime"] == "BULL"]
    gbr = g[g["regime"] == "BEAR"]
    gn = g[g["regime"] == "NEUTRAL"]

    avg_b = gb["pnl_r"].mean() if len(gb) > 0 else float("nan")
    avg_br = gbr["pnl_r"].mean() if len(gbr) > 0 else float("nan")
    avg_n = gn["pnl_r"].mean() if len(gn) > 0 else float("nan")

    # Classificazione configurazione attuale vs dati
    if pn in PATTERNS_BEAR_ONLY:
        conf = "BEAR only"
    elif pn in PATTERNS_SHORT_UNIV:
        conf = "Universale"
    elif pn in PATTERNS_UNIV:
        conf = "Universale"
    else:
        conf = "BEAR+score84"

    pattern_regime_data[pn] = dict(avg_b=avg_b, avg_br=avg_br, avg_n=avg_n,
                                    n_b=len(gb), n_br=len(gbr), n_n=len(gn))

    bs = regime_stats(gb)
    brs = regime_stats(gbr)
    ns = regime_stats(gn)
    print(f"  {pn:<34} {bs:>22} {brs:>22} {ns:>22}  {conf}")

# ══════════════════════════════════════════════════════════════════════════════
# ANALISI 2 — pattern × regime × direction
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 2 — avg_r per PATTERN × REGIME × DIRECTION")
print(SEP)

print(f"\n{'Pattern':<34} {'Regime':<8} {'Dir':>8} {'n':>6} {'avg_r':>8} {'WR':>6}  Note")
print("-"*85)

for pn in ALL_PATTERNS:
    g = prod[prod["pattern_name"] == pn]
    for regime in ["BULL", "NEUTRAL", "BEAR"]:
        gr = g[g["regime"] == regime]
        for direction in sorted(gr["direction"].unique()):
            gd = gr[gr["direction"] == direction]
            if len(gd) < 5:
                continue
            avg = gd["pnl_r"].mean()
            wr = (gd["pnl_r"] > 0).mean() * 100
            note = ""
            if pn in PATTERNS_BEAR_ONLY and regime != "BEAR":
                note = "<-- BLOCCATO in prod"
            elif pn in PATTERNS_BEAR_ONLY and regime == "BEAR":
                note = "(attivo)"
            print(f"  {pn:<32} {regime:<8} {direction:>8} {len(gd):>6,} {avg:>+8.3f}R {wr:>5.1f}%  {note}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
# ANALISI 3 — Con vs senza regime filter
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 3 — CON vs SENZA regime filter")
print(SEP)

# "Con regime filter attuale" = dataset produzione tal quale
# (il dataset produzione NON ha il regime filter perché il CSV non lo applica,
#  ma possiamo simularlo: escludiamo i bear-only in regime BULL/NEUTRAL)

# Con regime filter: esclude bear-only in BULL e NEUTRAL
mask_bear_only_wrong_regime = (
    prod["pattern_name"].isin(PATTERNS_BEAR_ONLY) & (prod["regime"].isin(["BULL","NEUTRAL"]))
)
df_with_filter = prod[~mask_bear_only_wrong_regime].copy()
df_without_filter = prod.copy()

# Conta quanti trade bear-only sarebbero bloccati in BULL/NEUTRAL
blocked = prod[mask_bear_only_wrong_regime]
print(f"\n  Trade bear-only eseguiti in regime BULL/NEUTRAL nel dataset: {len(blocked):,}")
print(f"  (questi NON sarebbero eseguiti con il regime filter attivo)")
print(f"  avg_r di questi trade bloccati: {blocked['pnl_r'].mean():>+.4f}R  WR={(blocked['pnl_r']>0).mean()*100:.1f}%")
print(f"  Per pattern:")
for pn, g in blocked.groupby("pattern_name"):
    if len(g) >= 3:
        for reg, gg in g.groupby("regime"):
            if len(gg) >= 3:
                print(f"    {pn:<36} {reg:<8} n={len(gg):>4}  avg_r={gg['pnl_r'].mean():>+.3f}R  WR={(gg['pnl_r']>0).mean()*100:.1f}%")

print(f"\n{'Config':<35} {'n':>6} {'avg_r':>9} {'WR':>6}  Note")
print("-"*65)
for label, df in [
    ("Con regime filter (bear-only solo BEAR)", df_with_filter),
    ("Senza regime filter (tutti i pattern)", df_without_filter),
]:
    n = len(df)
    avg = df["pnl_r"].mean()
    wr = (df["pnl_r"]>0).mean()*100
    print(f"  {label:<33} {n:>6,} {avg:>+9.4f}R {wr:>5.1f}%")

# ══════════════════════════════════════════════════════════════════════════════
# ANALISI 4 — Configurazione regime ottimale
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 4 — REGIME OTTIMALE PER PATTERN (basato sui dati)")
print(SEP)

THRESHOLD_VIABLE = 0.20  # avg_r minimo per considerare un regime "attivo"

print(f"\n{'Pattern':<36} {'BULL':>8} {'BEAR':>8} {'NEUT':>8}  {'Attuale':>14}  {'Ottimale':>20}  {'Cambia?'}")
print("-"*115)

changes = []
for pn in ALL_PATTERNS:
    d = pattern_regime_data[pn]
    bull_ok = (not pd.isna(d["avg_b"])) and d["avg_b"] >= THRESHOLD_VIABLE and d["n_b"] >= 10
    bear_ok = (not pd.isna(d["avg_br"])) and d["avg_br"] >= THRESHOLD_VIABLE and d["n_br"] >= 10
    neut_ok = (not pd.isna(d["avg_n"])) and d["avg_n"] >= THRESHOLD_VIABLE and d["n_n"] >= 10

    b_s = f"{d['avg_b']:>+.3f}R" if not pd.isna(d["avg_b"]) and d["n_b"]>=5 else "  n/a"
    br_s = f"{d['avg_br']:>+.3f}R" if not pd.isna(d["avg_br"]) and d["n_br"]>=5 else "  n/a"
    n_s = f"{d['avg_n']:>+.3f}R" if not pd.isna(d["avg_n"]) and d["n_n"]>=5 else "  n/a"

    # Attuale
    if pn in PATTERNS_BEAR_ONLY:
        current = "BEAR only"
        current_regimes = frozenset(["BEAR"])
    elif pn == "engulfing_bullish":
        current = "BEAR+score84"
        current_regimes = frozenset(["BEAR"])
    else:
        current = "Universale"
        current_regimes = frozenset(["BULL","BEAR","NEUTRAL"])

    # Ottimale dai dati
    opt_regimes = []
    if bull_ok: opt_regimes.append("BULL")
    if bear_ok: opt_regimes.append("BEAR")
    if neut_ok: opt_regimes.append("NEUT")
    optimal = "+".join(opt_regimes) if opt_regimes else "NESSUNO"

    optimal_set = frozenset(["BULL" if "BULL" in opt_regimes else "",
                              "BEAR" if "BEAR" in opt_regimes else "",
                              "NEUTRAL" if "NEUT" in opt_regimes else ""] ) - frozenset([""])

    cambia = "SI" if optimal_set != current_regimes else "no"
    if cambia == "SI":
        changes.append((pn, current, optimal))

    print(f"  {pn:<34} {b_s:>8} {br_s:>8} {n_s:>8}  {current:>14}  {optimal:>20}  {cambia}")

if changes:
    print(f"\n  MODIFICHE SUGGERITE:")
    for pn, cur, opt in changes:
        print(f"    {pn}: {cur} -> {opt}")

# ══════════════════════════════════════════════════════════════════════════════
# ANALISI 5 — Simboli per regime
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 5 — SIMBOLI per REGIME (top simboli per volume)")
print(SEP)

print(f"\n{'Simbolo':<8} {'n tot':>6} {'BULL avg_r':>11} {'BEAR avg_r':>11} {'NEUT avg_r':>11}  {'Migliore':>8}  {'Peggiore':>8}")
print("-"*80)

sym_regime = []
for sym, g in prod.groupby("symbol"):
    n = len(g)
    if n < 10:
        continue
    gb  = g[g["regime"]=="BULL"]
    gbr = g[g["regime"]=="BEAR"]
    gn  = g[g["regime"]=="NEUTRAL"]
    avg_b  = gb["pnl_r"].mean()  if len(gb)  >= 5 else float("nan")
    avg_br = gbr["pnl_r"].mean() if len(gbr) >= 5 else float("nan")
    avg_n  = gn["pnl_r"].mean()  if len(gn)  >= 5 else float("nan")
    avgs = {k:v for k,v in [("BULL",avg_b),("BEAR",avg_br),("NEUT",avg_n)] if not pd.isna(v)}
    best = max(avgs, key=avgs.get) if avgs else "?"
    worst = min(avgs, key=avgs.get) if avgs else "?"
    sym_regime.append((sym, n, avg_b, avg_br, avg_n, best, worst))

sym_regime.sort(key=lambda x: x[1], reverse=True)

for sym, n, avg_b, avg_br, avg_n, best, worst in sym_regime[:30]:
    b_s  = f"{avg_b:>+.3f}R" if not pd.isna(avg_b)  else "    n/a"
    br_s = f"{avg_br:>+.3f}R" if not pd.isna(avg_br) else "    n/a"
    n_s  = f"{avg_n:>+.3f}R" if not pd.isna(avg_n)  else "    n/a"
    print(f"  {sym:<6} {n:>6,} {b_s:>11} {br_s:>11} {n_s:>11}  {best:>8}  {worst:>8}")

# Simboli con forte regime-dipendenza
print(f"\n  SIMBOLI CON FORTE DIPENDENZA DA REGIME (diff > 0.50R tra best e worst):")
print(f"\n  {'Simbolo':<8} {'BULL':>8} {'BEAR':>8} {'NEUT':>8} {'Diff':>7} {'Attivo in'}")
print("-"*60)
for sym, n, avg_b, avg_br, avg_n, best, worst in sym_regime:
    avgs = [v for v in [avg_b, avg_br, avg_n] if not pd.isna(v)]
    if len(avgs) < 2:
        continue
    diff = max(avgs) - min(avgs)
    if diff > 0.50:
        b_s  = f"{avg_b:>+.3f}R"  if not pd.isna(avg_b)  else "   n/a"
        br_s = f"{avg_br:>+.3f}R" if not pd.isna(avg_br) else "   n/a"
        n_s  = f"{avg_n:>+.3f}R"  if not pd.isna(avg_n)  else "   n/a"
        ok_regimes = [r for r,v in [("BULL",avg_b),("BEAR",avg_br),("NEUT",avg_n)]
                     if not pd.isna(v) and v >= 0.20]
        print(f"  {sym:<6} {b_s:>8} {br_s:>8} {n_s:>8} {diff:>+7.3f}R  {','.join(ok_regimes) or 'nessuno'}")

# ══════════════════════════════════════════════════════════════════════════════
# RIEPILOGO FINALE
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  RIEPILOGO — avg_r pool per configurazione regime")
print(SEP)

configs = {
    "Attuale (bear-only solo BEAR)": df_with_filter,
    "Senza regime filter":           df_without_filter,
}

# Configurazione ottimale dai dati
def apply_optimal_filter(df):
    # Dai dati: tutti i pattern funzionano in tutti i regimi (avg_r > 0.20R)
    # eccetto dove l'analisi mostra chiaramente il contrario
    # Qui applico i risultati dell'analisi 4
    mask = pd.Series(True, index=df.index)
    for pn in ALL_PATTERNS:
        d = pattern_regime_data.get(pn, {})
        for regime, key in [("BULL","avg_b"),("BEAR","avg_br"),("NEUTRAL","avg_n")]:
            avg = d.get(key, float("nan"))
            n_key = {"avg_b":"n_b","avg_br":"n_br","avg_n":"n_n"}[key]
            n = d.get(n_key, 0)
            if not pd.isna(avg) and avg < 0.0 and n >= 10:
                # Blocca solo se chiaramente negativo e campione sufficiente
                m = (df["pattern_name"] == pn) & (df["regime"] == regime)
                mask[m] = False
    return df[mask]

df_optimal = apply_optimal_filter(df_without_filter)
configs["Ottimale (blocca solo se avg_r<0 con n>=10)"] = df_optimal

for label, df in configs.items():
    n = len(df)
    avg = df["pnl_r"].mean()
    wr = (df["pnl_r"]>0).mean()*100
    print(f"\n  {label}:")
    print(f"    n={n:,}  avg_r={avg:>+.4f}R  WR={wr:.1f}%")
    for regime in ["BULL","NEUTRAL","BEAR"]:
        g = df[df["regime"]==regime]
        if len(g) > 0:
            print(f"    {regime:<8}: n={len(g):>4,}  avg_r={g['pnl_r'].mean():>+.4f}R  WR={(g['pnl_r']>0).mean()*100:.1f}%")

print(f"\nFine analisi regime.")
