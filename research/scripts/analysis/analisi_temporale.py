"""
Analisi temporale: range dati, distribuzione per anno, stabilità per simbolo.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

VALIDATED_PATTERNS_1H = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
    "engulfing_bullish",
})
VALIDATED_PATTERNS_5M = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
})

SEP = "=" * 74

# ── Load ─────────────────────────────────────────────────────────────────────
h_raw = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
m_raw = pd.read_csv("data/val_5m_expanded.csv", parse_dates=["pattern_timestamp"])

h = h_raw[h_raw["entry_filled"] == True].copy()
m = m_raw[m_raw["entry_filled"] == True].copy()
h = h[h["pattern_name"].isin(VALIDATED_PATTERNS_1H)].copy()
m = m[m["pattern_name"].isin(VALIDATED_PATTERNS_5M)].copy()

h["year"] = h["pattern_timestamp"].dt.year
h["month"] = h["pattern_timestamp"].dt.to_period("M")
m["year"] = m["pattern_timestamp"].dt.year
m["month"] = m["pattern_timestamp"].dt.to_period("M")

# ═══════════════════════════════════════════════════════════════════════════
# 1. RANGE TEMPORALE
# ═══════════════════════════════════════════════════════════════════════════
print(SEP)
print("  1. RANGE TEMPORALE")
print(SEP)

for label, df in [("1h", h), ("5m", m)]:
    tmin = df["pattern_timestamp"].min()
    tmax = df["pattern_timestamp"].max()
    months = (tmax.year - tmin.year) * 12 + tmax.month - tmin.month
    print(f"\n{label}:")
    print(f"  MIN: {tmin.strftime('%Y-%m-%d')}")
    print(f"  MAX: {tmax.strftime('%Y-%m-%d')}")
    print(f"  Copertura: {months} mesi")
    print(f"  n totale: {len(df):,}  avg_r={df['pnl_r'].mean():+.4f}R")

    print(f"\n  Trade per anno ({label}):")
    for yr, g in df.groupby("year"):
        n = len(g)
        avg = g["pnl_r"].mean()
        wr = (g["pnl_r"] > 0).mean() * 100
        print(f"    {yr}: n={n:>6,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# 2. PERIODO PER SIMBOLO — CANDIDATI AL BLOCCO E TOP PERFORMER
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  2. ANALISI PERIODO PER SIMBOLO (1h)")
print(SEP)

TO_BLOCK = ["AAPL", "MSFT", "REGN", "BMRN", "TGT", "ABBV", "HON", "GD",
            "SPY", "DIA", "ICE", "VRTX", "CVX"]
TOP_PERF = ["NET", "GE", "RBLX", "SMR", "MU", "CELH", "LUNR", "NVO", "MRNA", "HOOD",
            "ARKK", "C", "SOFI", "DELL", "WULF", "ACHR", "ASTS"]

def sym_period(df, sym):
    g = df[df["symbol"] == sym]
    if len(g) == 0:
        return None
    tmin = g["pattern_timestamp"].min()
    tmax = g["pattern_timestamp"].max()
    months = (tmax.year - tmin.year) * 12 + tmax.month - tmin.month
    return dict(
        sym=sym, n=len(g), avg_r=g["pnl_r"].mean(),
        wr=(g["pnl_r"] > 0).mean() * 100,
        da=tmin.strftime("%Y-%m"), a=tmax.strftime("%Y-%m"),
        mesi=months,
    )

print("\n--- Candidati al BLOCCO ---")
print(f"{'Simbolo':<8} {'n':>6} {'Da':>8} {'A':>8} {'Mesi':>5} {'avg_r':>8} {'WR':>6} {'Affidabile?'}")
print("-" * 74)
for sym in TO_BLOCK:
    r = sym_period(h, sym)
    if r is None:
        print(f"{sym:<8}   n/a — non nel dataset")
        continue
    affid = "SI" if r["mesi"] >= 12 and r["n"] >= 100 else "NO (campione breve)"
    print(f"{r['sym']:<8} {r['n']:>6,} {r['da']:>8} {r['a']:>8} {r['mesi']:>5} {r['avg_r']:>+8.3f}R {r['wr']:>5.1f}% {affid}")

print("\n--- TOP PERFORMER ---")
print(f"{'Simbolo':<8} {'n':>6} {'Da':>8} {'A':>8} {'Mesi':>5} {'avg_r':>8} {'WR':>6} {'Affidabile?'}")
print("-" * 74)
for sym in TOP_PERF:
    r = sym_period(h, sym)
    if r is None:
        print(f"{sym:<8}   n/a — non nel dataset")
        continue
    affid = "SI" if r["mesi"] >= 12 and r["n"] >= 100 else "NO (campione breve)"
    print(f"{r['sym']:<8} {r['n']:>6,} {r['da']:>8} {r['a']:>8} {r['mesi']:>5} {r['avg_r']:>+8.3f}R {r['wr']:>5.1f}% {affid}")

# ═══════════════════════════════════════════════════════════════════════════
# 3. TREND TEMPORALE PER ANNO — TOP 5 E BOTTOM 5
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  3. TREND TEMPORALE PER ANNO (top e bottom)")
print(SEP)

sym_global = []
for sym, g in h.groupby("symbol"):
    if len(g) >= 80:
        sym_global.append((sym, len(g), g["pnl_r"].mean()))

sym_global.sort(key=lambda x: x[2], reverse=True)
top5 = [x[0] for x in sym_global[:5]]
bot5 = [x[0] for x in sym_global[-5:]]
featured = top5 + bot5

years = sorted(h["year"].unique())
print(f"\n{'Simbolo':<8}", end="")
for yr in years:
    print(f"  {yr} avg_r   n", end="")
print("  STABILE?")
print("-" * 90)

for sym in featured:
    g_sym = h[h["symbol"] == sym]
    row_parts = []
    avgs = []
    for yr in years:
        gy = g_sym[g_sym["year"] == yr]
        if len(gy) >= 10:
            a = gy["pnl_r"].mean()
            avgs.append(a)
            row_parts.append(f"  {a:>+7.3f} {len(gy):>4}")
        else:
            avgs.append(None)
            row_parts.append(f"  {'  n/a':>7} {len(gy):>4}")

    valid = [x for x in avgs if x is not None]
    if len(valid) >= 2:
        all_pos = all(x > 0 for x in valid)
        all_neg = all(x < 0 for x in valid)
        mixed = not all_pos and not all_neg
        stab = "ROBUSTO" if all_pos else ("NEGATIVO" if all_neg else "MISTO")
    else:
        stab = "DATI INSUFFICIENTI"

    label = "TOP" if sym in top5 else "BOT"
    print(f"{sym:<8} [{label}]{''.join(row_parts)}  {stab}")

# ═══════════════════════════════════════════════════════════════════════════
# 4. TREND TEMPORALE ESTESO — TUTTI I CANDIDATI AL BLOCCO E TOP PERFORMER
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  4. DETTAGLIO ANNUALE — CANDIDATI BLOCCO")
print(SEP)

print(f"\n{'Simbolo':<8}", end="")
for yr in years:
    print(f"  {yr} avg_r    n", end="")
print("  VERDETTO")
print("-" * 90)

all_check = list(dict.fromkeys(TO_BLOCK + TOP_PERF))  # preserva ordine, no dup
for sym in all_check:
    g_sym = h[h["symbol"] == sym]
    if len(g_sym) == 0:
        print(f"{sym:<8}  [non nel dataset]")
        continue
    row_parts = []
    avgs = []
    ns = []
    for yr in years:
        gy = g_sym[g_sym["year"] == yr]
        if len(gy) >= 10:
            a = gy["pnl_r"].mean()
            avgs.append(a)
            ns.append(len(gy))
            row_parts.append(f"  {a:>+7.3f} {len(gy):>4}")
        else:
            avgs.append(None)
            ns.append(len(gy))
            row_parts.append(f"  {'  n/a':>7} {len(gy):>4}")

    valid = [x for x in avgs if x is not None]
    total_n = sum(ns)
    if len(valid) >= 2:
        all_pos = all(x > 0 for x in valid)
        all_neg = all(x < 0 for x in valid)
        stab = "ROBUSTO" if all_pos else ("CONSISTENTE NEG" if all_neg else "MISTO")
    elif len(valid) == 1:
        stab = "UN ANNO SOLO"
    else:
        stab = "DATI INSUFFICIENTI"

    tag = "BLOCK" if sym in TO_BLOCK else "TOP"
    print(f"{sym:<8} [{tag}] {''.join(row_parts)}  {stab} (tot n={total_n})")

# ═══════════════════════════════════════════════════════════════════════════
# 5. RIEPILOGO: affidabilità per simbolo candidato al blocco
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  5. RIEPILOGO AFFIDABILITA' — DECISIONE BLOCCO")
print(SEP)

print("""
Criteri per blocco sicuro:
  - n >= 100 trade complessivi
  - Periodo >= 12 mesi
  - avg_r negativo o < 0.05R (sotto break-even slippage 0.15R) in almeno 2 anni
  - Non dipendente da un singolo anno anomalo
""")

for sym in TO_BLOCK:
    g_sym = h[h["symbol"] == sym]
    if len(g_sym) == 0:
        print(f"{sym:<8}: NON nel dataset — non presente in universo attivo")
        continue
    tmin = g_sym["pattern_timestamp"].min()
    tmax = g_sym["pattern_timestamp"].max()
    months = (tmax.year - tmin.year) * 12 + tmax.month - tmin.month
    global_avg = g_sym["pnl_r"].mean()
    n_tot = len(g_sym)

    yr_avgs = {}
    for yr, gy in g_sym.groupby("year"):
        if len(gy) >= 10:
            yr_avgs[yr] = (gy["pnl_r"].mean(), len(gy))

    neg_years = sum(1 for v, _ in yr_avgs.values() if v < 0.05)
    years_with_data = len(yr_avgs)

    # Verdetto
    if n_tot >= 100 and months >= 12 and neg_years >= 2:
        verdict = "BLOCCA (confermato)"
    elif n_tot >= 100 and months >= 12 and neg_years == 1 and global_avg < 0.05:
        verdict = "BLOCCA (globale sotto break-even, 1 anno negativo)"
    elif n_tot >= 100 and months >= 12:
        verdict = "MONITOR (dati sufficienti ma non chiaramente negativo)"
    else:
        verdict = "DATI INSUFFICIENTI — non bloccare ancora"

    yr_str = ", ".join(f"{yr}:{v:+.2f}R(n={n})" for yr, (v, n) in sorted(yr_avgs.items()))
    print(f"\n{sym} (n={n_tot}, {months}m, global={global_avg:+.3f}R):")
    print(f"  Per anno: {yr_str}")
    print(f"  => {verdict}")

print(f"\n{SEP}")
print("  6. POOL 1h COMPLESSIVO — avg_r PER ANNO")
print(SEP)
print()
for yr, g in h.groupby("year"):
    n = len(g)
    avg = g["pnl_r"].mean()
    wr = (g["pnl_r"] > 0).mean() * 100
    # quanti simboli
    nsym = g["symbol"].nunique()
    print(f"  {yr}: n={n:>6,}  avg_r={avg:+.4f}R  WR={wr:.1f}%  simboli={nsym}")

print("\nFine analisi temporale.")
