"""
Analisi per i 26 simboli VALIDATED con n=0 nel dataset produzione.
Mostra quanti trade sopravvivono ad ogni filtro e qual e' il collo di bottiglia.
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

PRODUCTION_PATTERNS = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
})

ZERO_SYMS = [
    "ACHR","APLD","ASTS","CELH","COIN","DELL","HOOD","JOBY","LLY","LUNR",
    "MP","MRNA","MSTR","MU","NET","NNE","OKLO","PLTR","RBLX","RKLB",
    "RXRX","SHOP","SMCI","SMR","SOFI","WULF",
]

SEP = "=" * 90

def hour_et(ts):
    if TZ_ET is not None:
        return ts.astimezone(TZ_ET).hour
    return (ts.hour - 4) % 24

raw = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
raw = raw[raw["entry_filled"] == True].copy()
raw["hour_et"] = raw["pattern_timestamp"].apply(hour_et)

# ═══════════════════════════════════════════════════════════════════════════════
print(SEP)
print("  FUNNEL PER FILTRO — 26 simboli con n=0 in produzione")
print(SEP)
print(f"\n{'Simbolo':<7} {'n_raw':>6} {'pat':>5} {'ore':>5} {'str':>5} {'rsk':>5} {'ent':>5}  Bottleneck")
print("-" * 65)

results = []
for sym in ZERO_SYMS:
    g0 = raw[raw["symbol"] == sym]
    n0 = len(g0)
    if n0 == 0:
        print(f"{sym:<7} {'n/a':>6}")
        continue

    g1 = g0[g0["pattern_name"].isin(PRODUCTION_PATTERNS)]
    g2 = g1[~g1["hour_et"].isin([3, 9])]
    g3 = g2[(g2["pattern_strength"] >= 0.60) & (g2["pattern_strength"] < 0.80)]
    g4 = g3[g3["risk_pct"] <= 1.5]
    if "bars_to_entry" in g4.columns:
        g5 = g4[g4["bars_to_entry"] <= 4]
    else:
        g5 = g4

    n1, n2, n3, n4, n5 = len(g1), len(g2), len(g3), len(g4), len(g5)

    # Identifica il bottleneck principale (dove cade di piu')
    drops = [
        ("pattern",  n0 - n1),
        ("ore ET",   n1 - n2),
        ("strength", n2 - n3),
        ("risk_pct", n3 - n4),
        ("bars",     n4 - n5),
    ]
    bottleneck = max(drops, key=lambda x: x[1])[0]

    print(f"{sym:<7} {n0:>6,} {n1:>5} {n2:>5} {n3:>5} {n4:>5} {n5:>5}  [{bottleneck}]")
    results.append(dict(sym=sym, n0=n0, n1=n1, n2=n2, n3=n3, n4=n4, n5=n5,
                        bottleneck=bottleneck, g0=g0, g1=g1, g2=g2, g3=g3, g4=g4))

# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  BREAKDOWN PATTERN — cosa rimane dopo filtro pattern?")
print(SEP)
print(f"\n{'Simbolo':<7} {'tot':>5}  {'dbl_b':>6} {'dbl_t':>6} {'macd_B':>7} {'macd_b':>7} {'rsi_B':>6} {'rsi_b':>6}  {'engulf':>7}")
print("-" * 72)
for r in results:
    g0, sym = r["g0"], r["sym"]
    tot = r["n0"]
    pat_counts = g0.groupby("pattern_name").size()
    db = pat_counts.get("double_bottom", 0)
    dt = pat_counts.get("double_top", 0)
    mb = pat_counts.get("macd_divergence_bear", 0)
    ml = pat_counts.get("macd_divergence_bull", 0)
    rb = pat_counts.get("rsi_divergence_bear", 0)
    rl = pat_counts.get("rsi_divergence_bull", 0)
    eng = pat_counts.get("engulfing_bullish", 0)
    print(f"{sym:<7} {tot:>5,}  {db:>6} {dt:>6} {mb:>7} {ml:>7} {rb:>6} {rl:>6}  {eng:>7}")

# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  STRENGTH DISTRIBUTION — dopo filtro pattern + ore ET")
print(SEP)
print(f"\n{'Simbolo':<7} {'<0.60':>6} {'0.60-0.70':>10} {'0.70-0.80':>10} {'0.80-0.90':>10} {'>=0.90':>7}  n_dopo_ore")
print("-" * 70)
for r in results:
    g2, sym = r["g2"], r["sym"]
    n = len(g2)
    if n == 0:
        print(f"{sym:<7} (nessun trade dopo pattern+ore)")
        continue
    s = g2["pattern_strength"]
    b1 = (s < 0.60).sum()
    b2 = ((s >= 0.60) & (s < 0.70)).sum()
    b3 = ((s >= 0.70) & (s < 0.80)).sum()
    b4 = ((s >= 0.80) & (s < 0.90)).sum()
    b5 = (s >= 0.90).sum()
    print(f"{sym:<7} {b1:>6} {b2:>10} {b3:>10} {b4:>10} {b5:>7}  n={n}")

# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  RISK_PCT DISTRIBUTION — dopo pattern + ore + strength")
print(SEP)
print(f"\n{'Simbolo':<7} {'<0.5%':>6} {'0.5-1%':>7} {'1-1.5%':>7} {'1.5-2%':>7} {'2-3%':>7} {'>3%':>6}  n_dopo_str")
print("-" * 65)
for r in results:
    g3, sym = r["g3"], r["sym"]
    n = len(g3)
    if n == 0:
        print(f"{sym:<7} (nessun trade dopo pattern+ore+strength)")
        continue
    rp = g3["risk_pct"]
    b1 = (rp < 0.5).sum()
    b2 = ((rp >= 0.5) & (rp < 1.0)).sum()
    b3 = ((rp >= 1.0) & (rp < 1.5)).sum()
    b4 = ((rp >= 1.5) & (rp < 2.0)).sum()
    b5 = ((rp >= 2.0) & (rp < 3.0)).sum()
    b6 = (rp >= 3.0).sum()
    print(f"{sym:<7} {b1:>6} {b2:>7} {b3:>7} {b4:>7} {b5:>7} {b6:>6}  n={n}")

# ═══════════════════════════════════════════════════════════════════════════════
# avg_r per fascia risk_pct nei simboli bloccati da risk
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  AVG_R PER FASCIA RISK_PCT — simboli con bottleneck = risk_pct")
print("  (dopo pattern + ore ET + strength filtrati)")
print(SEP)

risk_bottleneck = [r for r in results if r["bottleneck"] == "risk_pct" and len(r["g3"]) > 0]
for r in risk_bottleneck:
    sym = r["sym"]
    g3 = r["g3"]
    print(f"\n  {sym} (n dopo str={len(g3)}, median_risk={g3['risk_pct'].median():.2f}%):")
    print(f"  {'Fascia risk':>15} {'n':>5} {'avg_r':>8} {'WR':>6}")
    print(f"  {'-'*40}")
    for lo, hi, label in [(0, 0.5, "<0.5%"), (0.5, 1.0, "0.5-1%"),
                           (1.0, 1.5, "1-1.5%"), (1.5, 2.0, "1.5-2%"),
                           (2.0, 3.0, "2-3%"), (3.0, 99, ">3%")]:
        sub = g3[(g3["risk_pct"] >= lo) & (g3["risk_pct"] < hi)]
        if len(sub) < 3:
            continue
        avg = sub["pnl_r"].mean()
        wr = (sub["pnl_r"] > 0).mean() * 100
        mark = " <-- ESCLUSO" if lo >= 1.5 else ""
        print(f"  {label:>15} {len(sub):>5} {avg:>+8.3f}R {wr:>5.1f}%{mark}")

# ═══════════════════════════════════════════════════════════════════════════════
# Stessa analisi per simboli con bottleneck = pattern (tutti engulfing?)
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  SIMBOLI CON BOTTLENECK = PATTERN (tutti engulfing?)")
print(SEP)
pat_bottleneck = [r for r in results if r["bottleneck"] == "pattern"]
for r in pat_bottleneck:
    sym = r["sym"]
    g0 = r["g0"]
    pat_counts = g0.groupby("pattern_name").size().sort_values(ascending=False)
    total = len(g0)
    eng = pat_counts.get("engulfing_bullish", 0)
    print(f"\n  {sym} (n_raw={total}):")
    for pn, cnt in pat_counts.items():
        in_prod = pn in PRODUCTION_PATTERNS
        tag = "OK" if in_prod else "ESCLUSO"
        print(f"    {pn:<40} n={cnt:>5}  [{tag}]")

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario: soglia risk_pct per small cap = 3%
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  SCENARIO: risk_pct <= 3.0% per simboli con bottleneck risk")
print("  (tutti gli altri filtri invariati)")
print(SEP)

SMALL_CAP_SYMS = frozenset({
    "ACHR","APLD","ASTS","CELH","COIN","HOOD","JOBY","LUNR","MP",
    "MRNA","MSTR","MU","NET","NNE","OKLO","PLTR","RBLX","RKLB",
    "RXRX","SHOP","SMCI","SMR","SOFI","WULF","DELL","LLY",
})

print(f"\n{'Simbolo':<7} {'n@1.5%':>8} {'avg@1.5%':>10} {'n@3.0%':>8} {'avg@3.0%':>10} {'delta_n':>8}")
print("-" * 60)

for r in results:
    sym = r["sym"]
    g3 = r["g3"]  # dopo pattern + ore + strength
    if len(g3) == 0:
        continue

    # Filtra per bars_to_entry
    if "bars_to_entry" in g3.columns:
        g3b = g3[g3["bars_to_entry"] <= 4]
    else:
        g3b = g3

    at15 = g3b[g3b["risk_pct"] <= 1.5]
    at30 = g3b[g3b["risk_pct"] <= 3.0]

    n15, n30 = len(at15), len(at30)
    avg15 = at15["pnl_r"].mean() if n15 > 0 else float("nan")
    avg30 = at30["pnl_r"].mean() if n30 > 0 else float("nan")

    avg15_s = f"{avg15:>+10.3f}R" if not pd.isna(avg15) else "       n/a"
    avg30_s = f"{avg30:>+10.3f}R" if not pd.isna(avg30) else "       n/a"
    delta = n30 - n15

    print(f"{sym:<7} {n15:>8} {avg15_s} {n30:>8} {avg30_s} {delta:>+8}")

# Aggregato: pool VALIDATED con soglia differenziata
print(f"\n{SEP}")
print("  AGGREGATO POOL: soglia 1.5% (attuale) vs 3.0% (small cap volatili)")
print(SEP)

VALIDATED_SYMBOLS = frozenset({
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
    "MU","LUNR","CAT","GS",
})

val_df = raw[raw["symbol"].isin(VALIDATED_SYMBOLS)].copy()
val_df = val_df[val_df["pattern_name"].isin(PRODUCTION_PATTERNS)]
val_df = val_df[~val_df["hour_et"].isin([3, 9])]
val_df = val_df[(val_df["pattern_strength"] >= 0.60) & (val_df["pattern_strength"] < 0.80)]
if "bars_to_entry" in val_df.columns:
    val_df = val_df[val_df["bars_to_entry"] <= 4]

at15 = val_df[val_df["risk_pct"] <= 1.5]
at30 = val_df[val_df["risk_pct"] <= 3.0]

print(f"\n  Soglia 1.5% (attuale):  n={len(at15):,}  avg_r={at15['pnl_r'].mean():+.4f}R  WR={(at15['pnl_r']>0).mean()*100:.1f}%")
print(f"  Soglia 3.0% (scenario): n={len(at30):,}  avg_r={at30['pnl_r'].mean():+.4f}R  WR={(at30['pnl_r']>0).mean()*100:.1f}%")
print(f"  Trade aggiuntivi: +{len(at30)-len(at15):,}  avg_r fascia 1.5-3%: {at30[at30['risk_pct']>1.5]['pnl_r'].mean():+.4f}R")

# Fascia 1.5-3% per pattern
print(f"\n  Fascia 1.5-3% per pattern:")
fascia = at30[at30["risk_pct"] > 1.5]
for pn, g in fascia.groupby("pattern_name"):
    if len(g) >= 5:
        print(f"    {pn:<36} n={len(g):>4}  avg_r={g['pnl_r'].mean():>+.3f}R  WR={(g['pnl_r']>0).mean()*100:.1f}%")

print(f"\nFine analisi filtri.")
