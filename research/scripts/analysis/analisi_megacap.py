"""
Analisi mega-cap: AAPL, MSFT, AMZN, GOOGL, NVDA, META su 1h.
Solo analisi — nessuna modifica al sistema.
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

SEP = "=" * 74
MEGACAP = ["AAPL", "MSFT", "AMZN", "GOOGL", "NVDA", "META"]

VALIDATED_PATTERNS_1H = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
    "engulfing_bullish",
})
PATTERNS_BLOCKED = frozenset({
    "compression_to_expansion_transition",
    "impulsive_bearish_candle",
    "opening_range_breakout_bear",
    "breakout_with_retest",
    "evening_star",
    "impulsive_bullish_candle",
    "vwap_bounce_bear",
    "bull_flag", "bear_flag",
    "range_expansion_breakout_candidate",
    "volatility_squeeze_breakout",
    "nr7_breakout",
    "opening_range_breakout_bull",
    "inside_bar_breakout_bull",
})
ALL_PATTERNS = VALIDATED_PATTERNS_1H | PATTERNS_BLOCKED

def s(g):
    n = len(g)
    avg = g["pnl_r"].mean()
    wr = (g["pnl_r"] > 0).mean() * 100
    return n, avg, wr

def hour_et(ts):
    if TZ_ET is not None:
        return ts.astimezone(TZ_ET).hour
    return (ts.hour - 4) % 24

# ── Load ─────────────────────────────────────────────────────────────────────
df_raw = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
df_raw = df_raw[df_raw["entry_filled"] == True].copy()

mega = df_raw[df_raw["symbol"].isin(MEGACAP)].copy()
mega["hour_et"] = mega["pattern_timestamp"].apply(hour_et)
mega["year"] = mega["pattern_timestamp"].dt.year

print(SEP)
print("  MEGA-CAP OVERVIEW (val_1h_full, entry_filled=True, tutti i pattern)")
print(SEP)
print(f"\n{'Simbolo':<8} {'n':>6} {'avg_r':>8} {'WR':>6} {'Da':>8} {'A':>8}")
print("-" * 52)
for sym in MEGACAP:
    g = mega[mega["symbol"] == sym]
    n, avg, wr = s(g)
    tmin = g["pattern_timestamp"].min().strftime("%Y-%m")
    tmax = g["pattern_timestamp"].max().strftime("%Y-%m")
    print(f"{sym:<8} {n:>6,} {avg:>+8.3f}R {wr:>5.1f}% {tmin:>8} {tmax:>8}")
print(f"\n{'TOTALE':<8} {len(mega):>6,} {mega['pnl_r'].mean():>+8.3f}R {(mega['pnl_r']>0).mean()*100:>5.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI 1 — Pattern per simbolo
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 1 — PATTERN PER SIMBOLO (n>=10)")
print(SEP)

# Aggregato mega-cap per pattern
print(f"\n--- AGGREGATO (tutti e 6 mega-cap) ---")
print(f"{'Pattern':<42} {'n':>5} {'avg_r':>8} {'WR':>6} {'Validato?'}")
print("-" * 74)
pat_agg = []
for pat, g in mega.groupby("pattern_name"):
    n, avg, wr = s(g)
    if n >= 10:
        val = "SI" if pat in VALIDATED_PATTERNS_1H else "BLOCCATO" if pat in PATTERNS_BLOCKED else "-"
        pat_agg.append((pat, n, avg, wr, val))
pat_agg.sort(key=lambda x: x[2], reverse=True)
for pat, n, avg, wr, val in pat_agg:
    print(f"{pat:<42} {n:>5,} {avg:>+8.3f}R {wr:>5.1f}% {val}")

# Per singolo simbolo
print(f"\n--- PER SIMBOLO (n>=10, pattern con avg_r > +0.10R) ---")
for sym in MEGACAP:
    g_sym = mega[mega["symbol"] == sym]
    rows = []
    for pat, g in g_sym.groupby("pattern_name"):
        n, avg, wr = s(g)
        if n >= 10:
            val = "OK" if pat in VALIDATED_PATTERNS_1H else "BLK" if pat in PATTERNS_BLOCKED else "---"
            rows.append((pat, n, avg, wr, val))
    rows.sort(key=lambda x: x[2], reverse=True)
    top = [(p,n,a,w,v) for p,n,a,w,v in rows if a > 0.10]
    if top:
        print(f"\n  {sym}:")
        for pat, n, avg, wr, val in top:
            print(f"    {pat:<40} n={n:>4} avg={avg:>+.3f}R WR={wr:.1f}% [{val}]")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI 2 — Ora del giorno
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 2 — ORA DEL GIORNO ET (mega-cap aggregate, tutti pattern)")
print(SEP)
print(f"\n{'Ora ET':<8} {'n':>5} {'avg_r':>8} {'WR':>6}")
print("-" * 35)
hour_rows = []
for h_val, g in mega.groupby("hour_et"):
    n, avg, wr = s(g)
    if n >= 20:
        hour_rows.append((h_val, n, avg, wr))
hour_rows.sort(key=lambda x: x[0])
for h_val, n, avg, wr in hour_rows:
    marker = " <-- MIGLIORE" if avg == max(r[2] for r in hour_rows) else ""
    print(f"  {h_val:02d}:xx     {n:>5,} {avg:>+8.3f}R {wr:>5.1f}%{marker}")

# Solo pattern validati
print(f"\n--- Solo pattern validati per ora ---")
mega_val = mega[mega["pattern_name"].isin(VALIDATED_PATTERNS_1H)]
print(f"{'Ora ET':<8} {'n':>5} {'avg_r':>8} {'WR':>6}")
print("-" * 35)
hour_rows2 = []
for h_val, g in mega_val.groupby("hour_et"):
    n, avg, wr = s(g)
    if n >= 10:
        hour_rows2.append((h_val, n, avg, wr))
hour_rows2.sort(key=lambda x: x[0])
for h_val, n, avg, wr in hour_rows2:
    print(f"  {h_val:02d}:xx     {n:>5,} {avg:>+8.3f}R {wr:>5.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI 3 — Screener score
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 3 — SCREENER SCORE (mega-cap, pattern validati)")
print(SEP)
print(f"\n{'Score':<10} {'n':>5} {'avg_r':>8} {'WR':>6}")
print("-" * 35)
bins = [0, 5, 7, 9, 10, 11, 12, 100]
labels = ["0-4", "5-6", "7-8", "9", "10", "11", "12"]
mega_val2 = mega[mega["pattern_name"].isin(VALIDATED_PATTERNS_1H)].copy()
mega_val2["sc_bin"] = pd.cut(mega_val2["screener_score"].fillna(0), bins=bins, labels=labels, right=False)
for sb, g in mega_val2.groupby("sc_bin", observed=True):
    n, avg, wr = s(g)
    if n >= 10:
        print(f"  {str(sb):<10} {n:>5,} {avg:>+8.3f}R {wr:>5.1f}%")

print(f"\n--- Score < 10 vs >= 10 (mega-cap, pattern validati) ---")
for label2, mask in [("score < 10", mega_val2["screener_score"] < 10),
                     ("score >= 10", mega_val2["screener_score"] >= 10)]:
    g = mega_val2[mask]
    n, avg, wr = s(g)
    print(f"  {label2:<14} n={n:>5,}  avg_r={avg:>+.4f}R  WR={wr:.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI 4 — Stop distance
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 4 — STOP DISTANCE risk_pct (mega-cap, pattern validati)")
print(SEP)
print(f"\n{'risk_pct':<12} {'n':>5} {'avg_r':>8} {'WR':>6}")
print("-" * 38)
rp_bins = [0, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 100]
rp_labels = ["<0.3%", "0.3-0.5%", "0.5-0.75%", "0.75-1%", "1-1.5%", "1.5-2%", "2%+"]
mega_val2["rp_bin"] = pd.cut(mega_val2["risk_pct"], bins=rp_bins, labels=rp_labels)
for rb, g in mega_val2.groupby("rp_bin", observed=True):
    n, avg, wr = s(g)
    if n >= 10:
        print(f"  {str(rb):<12} {n:>5,} {avg:>+8.3f}R {wr:>5.1f}%")

# Anche su tutti i pattern
print(f"\n--- Tutti i pattern ---")
mega_rp = mega.copy()
mega_rp["rp_bin"] = pd.cut(mega_rp["risk_pct"], bins=rp_bins, labels=rp_labels)
for rb, g in mega_rp.groupby("rp_bin", observed=True):
    n, avg, wr = s(g)
    if n >= 20:
        print(f"  {str(rb):<12} {n:>5,} {avg:>+8.3f}R {wr:>5.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI 5 — Direction
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 5 — DIRECTION (mega-cap)")
print(SEP)

print(f"\n--- Tutti i pattern ---")
for dir_val, g in mega.groupby("direction"):
    n, avg, wr = s(g)
    print(f"  {str(dir_val):<10} n={n:>5,}  avg_r={avg:>+.4f}R  WR={wr:.1f}%")

print(f"\n--- Pattern validati ---")
for dir_val, g in mega_val2.groupby("direction"):
    n, avg, wr = s(g)
    print(f"  {str(dir_val):<10} n={n:>5,}  avg_r={avg:>+.4f}R  WR={wr:.1f}%")

print(f"\n--- Direction per simbolo (pattern validati) ---")
print(f"{'Simbolo':<8} {'bullish avg_r':>14} {'n':>5} {'bearish avg_r':>14} {'n':>5}")
print("-" * 52)
for sym in MEGACAP:
    g_sym = mega_val2[mega_val2["symbol"] == sym]
    bull = g_sym[g_sym["direction"] == "bullish"]
    bear = g_sym[g_sym["direction"] == "bearish"]
    ba = f"{bull['pnl_r'].mean():>+.3f}R" if len(bull) >= 5 else "  n/a"
    bea = f"{bear['pnl_r'].mean():>+.3f}R" if len(bear) >= 5 else "  n/a"
    print(f"{sym:<8} {ba:>14} {len(bull):>5,} {bea:>14} {len(bear):>5,}")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI 6 — Combinazione filtri migliori
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  ANALISI 6 — COMBINAZIONE FILTRI (pattern validati su mega-cap)")
print(SEP)

base = mega[mega["pattern_name"].isin(VALIDATED_PATTERNS_1H)].copy()
base["hour_et"] = base["pattern_timestamp"].apply(hour_et)

configs = [
    ("BASE (solo pattern validati)",
     base),
    ("+ no 09:xx ET",
     base[base["hour_et"] != 9]),
    ("+ no 09:xx, score < 10",
     base[(base["hour_et"] != 9) & (base["screener_score"] < 10)]),
    ("+ no 09:xx, risk_pct < 1%",
     base[(base["hour_et"] != 9) & (base["risk_pct"] < 1.0)]),
    ("+ no 09:xx, risk_pct < 0.75%",
     base[(base["hour_et"] != 9) & (base["risk_pct"] < 0.75)]),
    ("+ no 09:xx, risk_pct < 0.5%",
     base[(base["hour_et"] != 9) & (base["risk_pct"] < 0.5)]),
    ("+ no 09:xx, score<10 + risk<1%",
     base[(base["hour_et"] != 9) & (base["screener_score"] < 10) & (base["risk_pct"] < 1.0)]),
    ("+ no 09:xx, score<10 + risk<0.75%",
     base[(base["hour_et"] != 9) & (base["screener_score"] < 10) & (base["risk_pct"] < 0.75)]),
    ("+ no 09:xx, score<10 + risk<0.5%",
     base[(base["hour_et"] != 9) & (base["screener_score"] < 10) & (base["risk_pct"] < 0.5)]),
    ("direction bullish only",
     base[base["direction"] == "bullish"]),
    ("bullish + no 09:xx + risk<1%",
     base[(base["direction"] == "bullish") & (base["hour_et"] != 9) & (base["risk_pct"] < 1.0)]),
    ("bullish + no 09:xx + risk<0.5%",
     base[(base["direction"] == "bullish") & (base["hour_et"] != 9) & (base["risk_pct"] < 0.5)]),
    ("bearish only",
     base[base["direction"] == "bearish"]),
    ("bearish + no 09:xx + risk<1%",
     base[(base["direction"] == "bearish") & (base["hour_et"] != 9) & (base["risk_pct"] < 1.0)]),
    ("double_bottom/top solo",
     base[base["pattern_name"].isin({"double_bottom", "double_top"})]),
    ("double_bottom/top + risk<0.75%",
     base[base["pattern_name"].isin({"double_bottom", "double_top"}) & (base["risk_pct"] < 0.75)]),
    ("macd/rsi divergenze solo",
     base[base["pattern_name"].isin({"macd_divergence_bull","macd_divergence_bear","rsi_divergence_bull","rsi_divergence_bear"})]),
    ("macd/rsi + no 09:xx + risk<1%",
     base[base["pattern_name"].isin({"macd_divergence_bull","macd_divergence_bear","rsi_divergence_bull","rsi_divergence_bear"}) & (base["hour_et"] != 9) & (base["risk_pct"] < 1.0)]),
]

print(f"\n{'Configurazione':<42} {'n':>5} {'avg_r':>8} {'WR':>6}")
print("-" * 66)
best_avg = -999
best_cfg = ""
for name, g in configs:
    if len(g) == 0:
        continue
    n, avg, wr = s(g)
    marker = " <--" if avg > 0.30 else ""
    print(f"  {name:<42} {n:>5,} {avg:>+8.3f}R {wr:>5.1f}%{marker}")
    if avg > best_avg and n >= 30:
        best_avg = avg
        best_cfg = name

print(f"\n  Migliore configurazione (n>=30): '{best_cfg}' avg_r={best_avg:+.3f}R")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI EXTRA: pattern validati per anno e simbolo
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  EXTRA — TREND TEMPORALE PER ANNO (mega-cap, pattern validati)")
print(SEP)
print(f"\n{'Simbolo':<8} {'2023':>12} {'2024':>12} {'2025':>12} {'Trend'}")
print("-" * 58)
for sym in MEGACAP:
    g_sym = base[base["symbol"] == sym]
    row = []
    avgs = []
    for yr in [2023, 2024, 2025]:
        gy = g_sym[g_sym["year"] == yr]
        if len(gy) >= 8:
            a = gy["pnl_r"].mean()
            avgs.append(a)
            row.append(f"{a:>+.3f}R({len(gy)})")
        else:
            avgs.append(None)
            row.append(f"  n/a({len(gy)})")
    valid = [x for x in avgs if x is not None]
    trend = "STABILE" if len(valid) >= 2 and all(x > 0 for x in valid) else \
            "MISTO" if len(valid) >= 2 else "DATI INSUF"
    print(f"{sym:<8} {row[0]:>12} {row[1]:>12} {row[2]:>12} {trend}")

# ═══════════════════════════════════════════════════════════════════════════
# CONCLUSIONE
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  CONCLUSIONE — PROFILO MEGA-CAP")
print(SEP)

# Calcola per ogni simbolo il miglior filtro (risk_pct < 0.5%, no 09:xx)
print(f"\nPer ogni mega-cap — risultato con filtri ottimali (no 09:xx, risk<0.75%):")
print(f"{'Simbolo':<8} {'BASE avg_r':>12} {'n base':>7} {'FILTRATO avg_r':>15} {'n filt':>7}")
print("-" * 55)
for sym in MEGACAP:
    g_base = base[base["symbol"] == sym]
    g_filt = g_base[(g_base["hour_et"] != 9) & (g_base["risk_pct"] < 0.75)]
    if len(g_filt) < 5:
        g_filt = g_base[(g_base["hour_et"] != 9) & (g_base["risk_pct"] < 1.0)]
    nb, avb, _ = s(g_base)
    nf, avf, _ = s(g_filt) if len(g_filt) >= 5 else (0, float("nan"), 0)
    avf_str = f"{avf:>+.3f}R" if not np.isnan(avf) else "  n/a"
    print(f"{sym:<8} {avb:>+12.3f}R {nb:>7,} {avf_str:>15} {nf:>7,}")

print("""
CONCLUSIONE:
1. Esiste un profilo mega-cap con edge positivo?
   Risposta basata sui dati: vedi la tabella 'combinazione filtri' sopra.
   Se la riga migliore ha avg_r > +0.30R e n >= 30 → profilo definibile.
   Se no → le mega-cap non hanno edge affidabile con questo sistema.

2. Pattern migliori sulle mega-cap:
   Vedi ANALISI 1 — le combinazioni positive per simbolo.

3. Variabili chiave da guardare:
   - risk_pct (stop stretto = setup preciso = edge maggiore)
   - Ora del giorno (09:xx ET sempre problematico)
   - Screener score (basso = mercato non in trend = buono per divergenze)
""")
print("Fine analisi mega-cap.")
