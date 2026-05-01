"""
Test alternative TRIPLO 5m:
  1. Cap risk_pct ≤ 0.75% vs 2.0%
  2. MIN_HOUR_ET = 14 vs 11
  3. MIDDAY soglia 0.10/0.90 vs 0.15/0.85 vs 0.20/0.80
  4. OOS 2026 stabilità per ogni config
  5. MC v6 con la config migliore

Riusa filtri esatti di verify_5m_findings.py.
"""
from __future__ import annotations
import os
import psycopg2
from psycopg2.extras import execute_values
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

CSV_5M = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv"
CSV_1H = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production_2026.csv"
PPR_CACHE = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_ppr_cache_5m.parquet"
SLIP   = 0.15
RISK_5M_DEFAULT = 0.005
RISK_1H = 0.015
CAPITAL = 100_000.0

PATTERNS_5M = {
    "double_bottom","double_top",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
}
PATTERNS_1H = PATTERNS_5M  # stesso set
SYMBOLS_BLOCKED_ALPACA_5M = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL"}
VALIDATED_SYMBOLS_ALPACA_5M = {
    "GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT","MU","LUNR","CAT","GS",
} - SYMBOLS_BLOCKED_ALPACA_5M

SEP  = "=" * 84
SEP2 = "-" * 84

# ─── eff_r helpers ────────────────────────────────────────────────────────────
def cr1(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d
def cr2(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d

def eff_r_split_runner(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr1(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr2(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1 + 0.5*r2
    if o=="tp1":
        rn = 0.5 if r1>=1.0 else (0.0 if r1>=0.5 else -1.0)
        return 0.5*r1 + 0.5*rn
    if o in ("stop","stopped","sl"): return -1.0
    return pr

def eff_r_config_c(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r", 0) or 0)
    r1=cr1(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr2(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o == "tp2": return 0.5*r1 + 0.5*r2
    if o == "tp1":
        if mfe >= r2: runner = r2
        elif mfe >= 1.0: runner = 0.5
        elif mfe >= 0.5: runner = 0.0
        else: runner = -1.0
        return 0.5*r1 + 0.5*runner
    if o in ("stop","stopped","sl"):
        if mfe >= 1.0: return 0.5
        if mfe >= 0.5: return 0.0
        return -1.0
    return pr


# ─── Stats helper ─────────────────────────────────────────────────────────────
def stats(df, label, cfg="cfgc"):
    if len(df) == 0:
        print(f"  {label:<48} n=0")
        return None
    col = "eff_r_cfgc" if cfg=="cfgc" else "eff_r_split"
    s = df[col] - SLIP
    return dict(label=label, n=len(df), avg=df[col].mean(),
                eff=s.mean(), wr=(s>0).mean()*100,
                p25=s.quantile(0.25), p75=s.quantile(0.75))

def fmt(s):
    if s is None: return ""
    return (f"  {s['label']:<48} n={s['n']:>5} | avg_r={s['avg']:>+.4f} | "
            f"eff_r-slip={s['eff']:>+.4f} | WR={s['wr']:>5.1f}%")


# ─── Carica dataset 5m + JOIN DB con cache ────────────────────────────────────
print(SEP)
print("  TEST ALTERNATIVE TRIPLO 5m")
print(SEP)

df_raw = pd.read_csv(CSV_5M)
df_raw["pattern_timestamp"] = pd.to_datetime(df_raw["pattern_timestamp"], utc=True)
df_raw["hour_et"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour

# Filtri base (NO MIDDAY filter ancora — applicato dopo)
df_base = df_raw[
    df_raw["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df_raw["pattern_name"].isin(PATTERNS_5M) &
    df_raw["provider"].isin(["alpaca"]) &
    (df_raw["pattern_strength"].fillna(0) >= 0.60) &
    df_raw["symbol"].isin(VALIDATED_SYMBOLS_ALPACA_5M) &
    (df_raw["hour_et"] >= 11) & (df_raw["hour_et"] <= 16) &
    (df_raw["risk_pct"] >= 0.50) & (df_raw["risk_pct"] <= 2.00)
].copy()
print(f"  Pool base (pre-MIDDAY): {len(df_base):,} trade")
print(f"  Range: {df_base['pattern_timestamp'].min().date()} → {df_base['pattern_timestamp'].max().date()}")

# Cache JOIN DB per price_position_in_range
if os.path.exists(PPR_CACHE):
    df_ppr = pd.read_parquet(PPR_CACHE)
    print(f"  PPR loaded from cache: {len(df_ppr):,}")
    df_base = df_base.merge(df_ppr, on=["symbol","exchange","provider","pattern_timestamp"], how="left")
else:
    print(f"  PPR cache not found, querying DB ({len(df_base)} keys)...")
    conn = psycopg2.connect(host="localhost", port=5432, user="postgres",
                            password="postgres", dbname="intraday_market_screener")
    cur = conn.cursor()
    cur.execute("CREATE TEMP TABLE _k (sym VARCHAR(32), ex VARCHAR(32), prov VARCHAR(32), ts TIMESTAMPTZ)")
    keys = [(s, e, p, t) for s, e, p, t in zip(
        df_base["symbol"], df_base["exchange"], df_base["provider"], df_base["pattern_timestamp"])]
    execute_values(cur, "INSERT INTO _k VALUES %s", keys, page_size=5000)
    conn.commit()
    cur.execute("""
      SELECT k.sym, k.ex, k.prov, k.ts, ci.price_position_in_range
      FROM _k k
      LEFT JOIN candle_indicators ci ON
        ci.symbol=k.sym AND ci.exchange=k.ex AND ci.provider=k.prov
        AND ci.timeframe='5m' AND ci.timestamp=k.ts
    """)
    rows = cur.fetchall()
    conn.close()
    df_ppr = pd.DataFrame(rows, columns=["symbol","exchange","provider","pattern_timestamp","ppr"])
    df_ppr["ppr"] = pd.to_numeric(df_ppr["ppr"], errors="coerce")
    df_ppr["pattern_timestamp"] = pd.to_datetime(df_ppr["pattern_timestamp"], utc=True)
    # Cache for reuse
    df_ppr.to_parquet(PPR_CACHE, index=False)
    print(f"  PPR cached: {len(df_ppr):,}")
    df_base = df_base.merge(df_ppr, on=["symbol","exchange","provider","pattern_timestamp"], how="left")

# Calcola eff_r per ogni trade (cfgc + split)
df_base["eff_r_cfgc"]  = df_base.apply(eff_r_config_c, axis=1)
df_base["eff_r_split"] = df_base.apply(eff_r_split_runner, axis=1)


# ─── Funzione per applicare filtro TRIPLO con soglie variabili ────────────────
def apply_triplo(df, midday_low=0.10, midday_high=0.90, min_hour=11, max_risk=2.00):
    """Applica filtro TRIPLO + custom params. Restituisce subset filtrato."""
    df = df[df["risk_pct"] <= max_risk].copy()
    df = df[df["hour_et"] >= min_hour].copy()

    def passes(row):
        h = row["hour_et"]
        if h >= 15:  # ALPHA — no midday filter
            return True
        if h < 11 or h < min_hour:
            return False
        # 11-14: MIDDAY_F
        if pd.isna(row["ppr"]):
            return False
        pos = row["ppr"]
        d = str(row["direction"]).lower()
        return ((d == "bullish" and pos <= midday_low) or
                (d == "bearish" and pos >= midday_high))
    df["pass"] = df.apply(passes, axis=1)
    return df[df["pass"]].copy()


# ═══ BASELINE: pool TRIPLO attuale ═══════════════════════════════════════════
df_baseline = apply_triplo(df_base, midday_low=0.10, midday_high=0.90,
                           min_hour=11, max_risk=2.00)
df_baseline["year"] = df_baseline["pattern_timestamp"].dt.year
print()
print(SEP)
print("  BASELINE — TRIPLO attuale (midday 0.10/0.90, hour>=11, risk<=2.0%)")
print(SEP)
print(fmt(stats(df_baseline, "Baseline TRIPLO")))


# ═══ TEST 1: cap risk_pct ═══════════════════════════════════════════════════════
print()
print(SEP)
print("  TEST 1 — Cap risk_pct sul TRIPLO (cfg C trailing)")
print(SEP)
print(f"  {'risk cap':<18} {'n':>5} {'avg_r':>9} {'eff_r-slip':>11} {'WR':>6}  {'p25':>9} {'p75':>9}")
print("  " + SEP2)
risk_results = []
for max_r in [2.00, 1.50, 1.25, 1.00, 0.75, 0.60]:
    df_x = apply_triplo(df_base, max_risk=max_r)
    s = stats(df_x, f"risk <= {max_r:.2f}%")
    if s:
        print(f"  risk <= {max_r:.2f}%       {s['n']:>5} {s['avg']:>+9.4f} {s['eff']:>+11.4f} "
              f"{s['wr']:>5.1f}%  {s['p25']:>+9.4f} {s['p75']:>+9.4f}")
        risk_results.append((max_r, s, df_x))


# ═══ TEST 2: MIN_HOUR_ET ═════════════════════════════════════════════════════════
print()
print(SEP)
print("  TEST 2 — MIN_HOUR_ET sul TRIPLO (cfg C trailing)")
print(SEP)
print(f"  {'min_hour':<14} {'n':>5} {'avg_r':>9} {'eff_r-slip':>11} {'WR':>6}  {'p25':>9} {'p75':>9}")
print("  " + SEP2)
hour_results = []
for mh in [11, 12, 13, 14, 15]:
    df_x = apply_triplo(df_base, min_hour=mh)
    s = stats(df_x, f"min_hour={mh}")
    if s:
        print(f"  min_hour={mh:<5}    {s['n']:>5} {s['avg']:>+9.4f} {s['eff']:>+11.4f} "
              f"{s['wr']:>5.1f}%  {s['p25']:>+9.4f} {s['p75']:>+9.4f}")
        hour_results.append((mh, s, df_x))


# ═══ TEST 3: soglia MIDDAY ════════════════════════════════════════════════════════
print()
print(SEP)
print("  TEST 3 — Soglia MIDDAY sul TRIPLO (cfg C trailing)")
print(SEP)
print(f"  {'soglia':<16} {'n':>5} {'avg_r':>9} {'eff_r-slip':>11} {'WR':>6}  {'p25':>9} {'p75':>9}")
print("  " + SEP2)
midday_results = []
for lo, hi in [(0.05, 0.95), (0.10, 0.90), (0.15, 0.85),
               (0.20, 0.80), (0.25, 0.75), (0.30, 0.70)]:
    df_x = apply_triplo(df_base, midday_low=lo, midday_high=hi)
    s = stats(df_x, f"midday {lo:.2f}/{hi:.2f}")
    if s:
        print(f"  {lo:.2f} / {hi:.2f}      {s['n']:>5} {s['avg']:>+9.4f} {s['eff']:>+11.4f} "
              f"{s['wr']:>5.1f}%  {s['p25']:>+9.4f} {s['p75']:>+9.4f}")
        midday_results.append(((lo,hi), s, df_x))


# ═══ TEST 4: OOS 2026 stabilità per ogni config ════════════════════════════════
print()
print(SEP)
print("  TEST 4 — OOS 2026 stabilità per le top config")
print(SEP)

# Pick top configs
top_risk_caps = [2.00, 1.00, 0.75]
top_hours = [11, 14, 15]
top_middays = [(0.10, 0.90), (0.15, 0.85), (0.20, 0.80)]

print(f"\n  Per anno (cfgc - slip):")
print(f"  {'config':<48} {'2024':>10} {'2025':>10} {'2026':>10}  {'n_2026':>7}")
print("  " + SEP2)

def yearly(df, label):
    df = df.copy()
    df["year"] = df["pattern_timestamp"].dt.year
    out = {}
    for y in [2024, 2025, 2026]:
        sub = df[df["year"] == y]
        if len(sub) >= 5:
            out[y] = (sub["eff_r_cfgc"] - SLIP).mean()
        else:
            out[y] = None
    n_oos = (df["year"] == 2026).sum()
    fmt_v = lambda v: f"{v:>+10.4f}" if v is not None else f"{'n/a':>10}"
    print(f"  {label:<48} {fmt_v(out[2024])} {fmt_v(out[2025])} {fmt_v(out[2026])}  {n_oos:>7}")
    return out

# Test 1 best configs
print()
print("  >>> Test 1 (cap risk):")
for max_r in top_risk_caps:
    df_x = apply_triplo(df_base, max_risk=max_r)
    yearly(df_x, f"risk <= {max_r:.2f}%")

print()
print("  >>> Test 2 (min hour):")
for mh in top_hours:
    df_x = apply_triplo(df_base, min_hour=mh)
    yearly(df_x, f"min_hour={mh}")

print()
print("  >>> Test 3 (midday soglia):")
for lo, hi in top_middays:
    df_x = apply_triplo(df_base, midday_low=lo, midday_high=hi)
    yearly(df_x, f"midday {lo:.2f}/{hi:.2f}")

# Combinazioni
print()
print("  >>> Combinazioni promettenti:")
combos = [
    (1.00, 11, 0.10, 0.90, "risk<=1.0 + base TRIPLO"),
    (1.00, 14, 0.10, 0.90, "risk<=1.0 + min_hour=14"),
    (0.75, 11, 0.10, 0.90, "risk<=0.75 + base TRIPLO"),
    (0.75, 14, 0.10, 0.90, "risk<=0.75 + min_hour=14"),
    (1.00, 11, 0.15, 0.85, "risk<=1.0 + midday 0.15"),
    (1.00, 11, 0.20, 0.80, "risk<=1.0 + midday 0.20"),
    (0.75, 11, 0.20, 0.80, "risk<=0.75 + midday 0.20"),
    (1.00, 14, 0.20, 0.80, "risk<=1.0 + h14 + midday 0.20"),
]
combo_results = []
for max_r, mh, lo, hi, lab in combos:
    df_x = apply_triplo(df_base, midday_low=lo, midday_high=hi,
                        min_hour=mh, max_risk=max_r)
    out = yearly(df_x, lab)
    s = stats(df_x, lab)
    if s:
        combo_results.append((lab, s, df_x, out))


# ═══ TEST 5: MC v6 con la config migliore ═════════════════════════════════════
print()
print(SEP)
print("  TEST 5 — Riepilogo CONFIG MIGLIORE + MC v6")
print(SEP)

# Pick config: max eff con n>=200 e edge OOS 2026 positivo (stabilità)
candidates = [(s, df_x, out) for lab, s, df_x, out in combo_results
              if s["n"] >= 200 and out.get(2026) is not None and out[2026] > 0]
candidates.append((stats(df_baseline, "BASELINE TRIPLO"), df_baseline, None))

# Aggiungi anche le migliori dei test singoli
for max_r, s, df_x in risk_results:
    if s["n"] >= 200:
        df_y = df_x.copy()
        df_y["year"] = df_y["pattern_timestamp"].dt.year
        oos = (df_y[df_y["year"]==2026]["eff_r_cfgc"] - SLIP).mean() if (df_y["year"]==2026).sum() >= 5 else None
        out = {2026: oos}
        candidates.append((s, df_x, out))

# Sort per eff
candidates.sort(key=lambda x: -x[0]["eff"])

print(f"\n  Top 8 configurazioni (eff_r-slip discendente):")
print(f"  {'config':<46} {'n':>5} {'eff_r-slip':>11} {'WR':>6} {'2026_oos':>10}")
print("  " + SEP2)
for s, df_x, out in candidates[:8]:
    oos_str = f"{out[2026]:>+10.4f}" if (out and out.get(2026) is not None) else f"{'n/a':>10}"
    print(f"  {s['label']:<46} {s['n']:>5} {s['eff']:>+11.4f} {s['wr']:>5.1f}% {oos_str}")

# Pick the actual best (highest eff with n>=400 and OOS positive)
best_choice = None
for s, df_x, out in candidates:
    if s["n"] >= 400:
        if out is None or out.get(2026) is None or out.get(2026) > 0:
            best_choice = (s, df_x, out)
            break

if best_choice:
    s_best, df_best, out_best = best_choice
    print(f"\n  Config MIGLIORE selezionata: {s_best['label']}")
    print(f"  n={s_best['n']:,} | eff_r-slip={s_best['eff']:+.4f} | WR={s_best['wr']:.1f}%")
    print(f"  Delta vs baseline TRIPLO: eff {s_best['eff']:+.4f} vs +0.8050  = "
          f"{(s_best['eff']-0.8050)*100/0.8050:+.1f}%")
else:
    print(f"\n  Nessuna config supera baseline con n>=400.")
    s_best = stats(df_baseline, "BASELINE")
    df_best = df_baseline


# ─── MC v6 con config migliore vs baseline ───────────────────────────────────
print()
print(SEP)
print("  MC v6 — Config migliore vs BASELINE TRIPLO (€100k, 12m)")
print(SEP)

def build_monthly_blocks(df, slot_cap, eff_col="eff_r_cfgc"):
    df = df.sort_values("pattern_timestamp").copy()
    df["ym"] = df["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for ym, sub in df.groupby("ym", sort=True):
        sub = sub.head(slot_cap)
        if len(sub) > 0:
            blocks.append((sub[eff_col] - SLIP).values)
    return blocks

# Per il MC ho bisogno anche del pool 1h (riuso quello aggiornato)
df1 = pd.read_csv(CSV_1H)
df1["pattern_timestamp"] = pd.to_datetime(df1["pattern_timestamp"], utc=True)
df1 = df1[
    df1["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df1["pattern_name"].isin(PATTERNS_1H) &
    ~df1["provider"].isin(["ibkr"]) &
    (df1["pattern_strength"].fillna(0) >= 0.60)
].copy()
df1["eff_r_split"] = df1.apply(eff_r_split_runner, axis=1)
df1["eff_r_cfgc"]  = df1.apply(eff_r_config_c, axis=1)  # 1h non usa Config C ma per analisi

# Per 1h uso split (configurazione attuale)
blocks_1h_split = build_monthly_blocks(df1, slot_cap=66, eff_col="eff_r_split")

# Per 5m uso Config C (configurazione attuale produzione)
SLOT_5M = 48  # cap noto
blocks_5m_baseline = build_monthly_blocks(df_baseline, slot_cap=SLOT_5M, eff_col="eff_r_cfgc")
blocks_5m_best     = build_monthly_blocks(df_best,     slot_cap=SLOT_5M, eff_col="eff_r_cfgc")

def run_mc(blocks_a, blocks_b, ra=0.015, rb=RISK_5M_DEFAULT,
           cap=CAPITAL, nsim=5000, seed=42, n_months=12):
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim); dds = np.empty(nsim)
    have_a = len(blocks_a) > 0; have_b = len(blocks_b) > 0
    idx_a = np.arange(len(blocks_a)); idx_b = np.arange(len(blocks_b))
    for i in range(nsim):
        eq = cap; pk = cap; md = 0.0
        for _ in range(n_months):
            risk_a = eq*ra; risk_b = eq*rb; pnl = 0.0
            if have_a:
                pnl += (blocks_a[rng.choice(idx_a)] * risk_a).sum()
            if have_b:
                pnl += (blocks_b[rng.choice(idx_b)] * risk_b).sum()
            eq = max(0, eq + pnl)
            if eq > pk: pk = eq
            if pk > 0:
                dd = (pk-eq)/pk
                if dd > md: md = dd
        finals[i] = eq; dds[i] = md
    return dict(med=np.median(finals), p05=np.percentile(finals,5),
                p95=np.percentile(finals,95), prob=(finals>cap).mean(),
                dd_p95=np.percentile(dds,95))

print("  Calcolo MC...")
mc_baseline = run_mc(blocks_1h_split, blocks_5m_baseline)
mc_best     = run_mc(blocks_1h_split, blocks_5m_best)

print()
print(f"  {'Config':<42} {'Mediana':>12} {'Worst5%':>12} {'ProbP':>6} {'DDp95':>6}")
print("  " + SEP2)
print(f"  {'Baseline TRIPLO (5m attuale)':<42} {mc_baseline['med']:>12,.0f} "
      f"{mc_baseline['p05']:>12,.0f} {mc_baseline['prob']*100:>5.1f}% {mc_baseline['dd_p95']*100:>5.1f}%")
print(f"  {'Best 5m: '+s_best['label']:<42} {mc_best['med']:>12,.0f} "
      f"{mc_best['p05']:>12,.0f} {mc_best['prob']*100:>5.1f}% {mc_best['dd_p95']*100:>5.1f}%")
print(f"\n  Delta mediana: {(mc_best['med']/mc_baseline['med']-1)*100:+.1f}%")
print(f"  Delta worst5%: {(mc_best['p05']/mc_baseline['p05']-1)*100:+.1f}%")

# Solo 5m con riskmgmt diversi
SLOT_5M = 48
print()
print("  Solo 5m (per isolare contributo):")
mc5_base = run_mc([], blocks_5m_baseline, ra=0, rb=RISK_5M_DEFAULT)
mc5_best = run_mc([], blocks_5m_best, ra=0, rb=RISK_5M_DEFAULT)
print(f"  {'5m baseline':<42} {mc5_base['med']:>12,.0f}")
print(f"  {'5m best':<42} {mc5_best['med']:>12,.0f}")
print(f"  Delta solo 5m: {(mc5_best['med']/mc5_base['med']-1)*100:+.1f}%")

# Slot cap rivisto se config più restrittiva (n/mese diventa più basso)
df_best_m = df_best.copy()
df_best_m["ym"] = df_best_m["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
ns_per_month = df_best_m.groupby("ym").size()
print()
print(f"  Trade/mese best config: med={ns_per_month.median():.0f} | "
      f"min={ns_per_month.min()} | max={ns_per_month.max()} | n_mesi={len(ns_per_month)}")
print(f"  Slot cap 48 vs n/mese best: {'limita' if ns_per_month.median() > 48 else 'non limita'}")

print()
print(SEP)
print("  CONCLUSIONI")
print(SEP)
print(f"  Pool TRIPLO baseline: {len(df_baseline):,} trade")
print(f"  Best config:          {s_best['label']} ({s_best['n']:,} trade)")
print(f"  Edge baseline:        +0.8050R  (Config C trailing)")
print(f"  Edge best:            {s_best['eff']:+.4f}R")
print(f"  MC mediana baseline:  €{mc_baseline['med']:,.0f}")
print(f"  MC mediana best:      €{mc_best['med']:,.0f}")
