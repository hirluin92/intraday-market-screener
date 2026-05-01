"""
Test risk sizing 5m sulla config best (risk≤0.75 + min_hour=14).
Confronta MC v6 con varie risk size 5m vs baseline TRIPLO + risk 0.5%.

Anche test Opzione B: tier-based risk sizing (proporzionale a risk_pct trade).
"""
from __future__ import annotations
import os, numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

CSV_5M  = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv"
CSV_1H  = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production_2026.csv"
PPR_CACHE = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_ppr_cache_5m.parquet"
SLIP   = 0.15
RISK_1H_DEFAULT = 0.015
RISK_5M_DEFAULT = 0.005
CAPITAL = 100_000.0
SLOT_1H = 66
SLOT_5M = 48

PATTERNS = {
    "double_bottom","double_top",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
}
SYMBOLS_BLOCKED_5M = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL"}
VAL_SYMS_5M = {
    "GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT","MU","LUNR","CAT","GS",
} - SYMBOLS_BLOCKED_5M

SEP = "=" * 84

# ─── eff_r ────────────────────────────────────────────────────────────────────
def cr(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d

def eff_r_split_runner(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        rn=0.5 if r1>=1.0 else (0.0 if r1>=0.5 else -1.0)
        return 0.5*r1+0.5*rn
    if o in ("stop","stopped","sl"): return -1.0
    return pr

def eff_r_config_c(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r", 0) or 0)
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        if mfe>=r2: runner=r2
        elif mfe>=1.0: runner=0.5
        elif mfe>=0.5: runner=0.0
        else: runner=-1.0
        return 0.5*r1+0.5*runner
    if o in ("stop","stopped","sl"):
        if mfe>=1.0: return 0.5
        if mfe>=0.5: return 0.0
        return -1.0
    return pr


# ─── Load + filtri ────────────────────────────────────────────────────────────
print(SEP)
print("  TEST RISK SIZING 5m — Opzione A (size 1.5×) e B (tier-based)")
print(SEP)

df_raw = pd.read_csv(CSV_5M)
df_raw["pattern_timestamp"] = pd.to_datetime(df_raw["pattern_timestamp"], utc=True)
df_raw["hour_et"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour

df_base = df_raw[
    df_raw["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df_raw["pattern_name"].isin(PATTERNS) &
    df_raw["provider"].isin(["alpaca"]) &
    (df_raw["pattern_strength"].fillna(0) >= 0.60) &
    df_raw["symbol"].isin(VAL_SYMS_5M) &
    (df_raw["hour_et"] >= 11) & (df_raw["hour_et"] <= 16) &
    (df_raw["risk_pct"] >= 0.50) & (df_raw["risk_pct"] <= 2.00)
].copy()

df_ppr = pd.read_parquet(PPR_CACHE)
df_base = df_base.merge(df_ppr, on=["symbol","exchange","provider","pattern_timestamp"], how="left")
df_base["eff_r_cfgc"] = df_base.apply(eff_r_config_c, axis=1)
df_base["eff_r_split"] = df_base.apply(eff_r_split_runner, axis=1)

def apply_triplo(df, midday_low=0.10, midday_high=0.90, min_hour=11, max_risk=2.00):
    df = df[df["risk_pct"] <= max_risk].copy()
    df = df[df["hour_et"] >= min_hour].copy()
    def passes(row):
        h = row["hour_et"]
        if h >= 15: return True
        if h < min_hour: return False
        if pd.isna(row["ppr"]): return False
        pos = row["ppr"]; d = str(row["direction"]).lower()
        return ((d=="bullish" and pos<=midday_low) or
                (d=="bearish" and pos>=midday_high))
    return df[df.apply(passes, axis=1)].copy()

df_baseline = apply_triplo(df_base, max_risk=2.00, min_hour=11)
df_best     = apply_triplo(df_base, max_risk=0.75, min_hour=14)

print(f"  Pool baseline TRIPLO: {len(df_baseline):,} trade")
print(f"  Pool best (risk≤0.75 + h14): {len(df_best):,} trade")


# ─── 1h pool ──────────────────────────────────────────────────────────────────
df1 = pd.read_csv(CSV_1H)
df1["pattern_timestamp"] = pd.to_datetime(df1["pattern_timestamp"], utc=True)
df1 = df1[
    df1["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df1["pattern_name"].isin(PATTERNS) &
    ~df1["provider"].isin(["ibkr"]) &
    (df1["pattern_strength"].fillna(0) >= 0.60)
].copy()
df1["eff_r_split"] = df1.apply(eff_r_split_runner, axis=1)
print(f"  Pool 1h: {len(df1):,} trade")


# ─── Bootstrap blocchi mensili ────────────────────────────────────────────────
def build_blocks(df, slot_cap, eff_col="eff_r_cfgc", risk_col=None):
    """Ritorna lista di (eff_array, risk_array) per mese."""
    df = df.sort_values("pattern_timestamp").copy()
    df["ym"] = df["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for ym, sub in df.groupby("ym", sort=True):
        sub = sub.head(slot_cap)
        if len(sub) == 0: continue
        eff = (sub[eff_col] - SLIP).values
        if risk_col is not None:
            rsk = sub[risk_col].values
            blocks.append((eff, rsk))
        else:
            blocks.append((eff, None))
    return blocks


def run_mc(blocks_a, blocks_b, ra=RISK_1H_DEFAULT, rb=RISK_5M_DEFAULT,
           tier_b=False, cap=CAPITAL, nsim=5000, seed=42, n_months=12):
    """
    blocks_*: lista di (eff_arr, risk_arr_or_None) per mese.
    tier_b: se True, applica risk size proporzionale a risk_pct del trade per pool B.
    """
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim); dds = np.empty(nsim)
    have_a = len(blocks_a) > 0; have_b = len(blocks_b) > 0
    idx_a = np.arange(len(blocks_a)); idx_b = np.arange(len(blocks_b))
    for i in range(nsim):
        eq = cap; pk = cap; md = 0.0
        for _ in range(n_months):
            risk_a_dollars = eq*ra
            risk_b_base = eq*rb
            pnl = 0.0
            if have_a:
                eff_a, _ = blocks_a[rng.choice(idx_a)]
                pnl += (eff_a * risk_a_dollars).sum()
            if have_b:
                eff_b, risk_b_arr = blocks_b[rng.choice(idx_b)]
                if tier_b and risk_b_arr is not None:
                    # Tier sizing: risk size scala inversamente con risk_pct trade
                    # rp 0.5-0.75 → 1.0×, 0.75-1.5 → 0.7×, >1.5 → 0.5×
                    multipliers = np.where(risk_b_arr <= 0.75, 1.0,
                                  np.where(risk_b_arr <= 1.5, 0.7, 0.5))
                    pnl += (eff_b * risk_b_base * multipliers).sum()
                else:
                    pnl += (eff_b * risk_b_base).sum()
            eq = max(0, eq + pnl)
            if eq > pk: pk = eq
            if pk > 0:
                dd = (pk-eq)/pk
                if dd > md: md = dd
        finals[i] = eq; dds[i] = md
    return dict(med=np.median(finals), p05=np.percentile(finals,5),
                p25=np.percentile(finals,25), p75=np.percentile(finals,75),
                p95=np.percentile(finals,95), prob=(finals>cap).mean(),
                dd_med=np.median(dds), dd_p95=np.percentile(dds,95))


# Build blocks
blocks_1h     = build_blocks(df1,         SLOT_1H, eff_col="eff_r_split")
blocks_5m_bl  = build_blocks(df_baseline, SLOT_5M, eff_col="eff_r_cfgc", risk_col="risk_pct")
blocks_5m_bst = build_blocks(df_best,     SLOT_5M, eff_col="eff_r_cfgc", risk_col="risk_pct")


# ═══ Determinismo: media trade/mese ═══════════════════════════════════════════
print()
print(SEP)
print("  Volume mensile e EV deterministico")
print(SEP)
print(f"  Pool 1h:        {len(blocks_1h)} blocchi | n/mese mediano: {np.median([len(b[0]) for b in blocks_1h]):.0f}")
print(f"  Pool 5m base:   {len(blocks_5m_bl)} blocchi | n/mese mediano: {np.median([len(b[0]) for b in blocks_5m_bl]):.0f}")
print(f"  Pool 5m best:   {len(blocks_5m_bst)} blocchi | n/mese mediano: {np.median([len(b[0]) for b in blocks_5m_bst]):.0f}")

avg_5m_bl  = np.mean([b[0].mean() for b in blocks_5m_bl])
avg_5m_bst = np.mean([b[0].mean() for b in blocks_5m_bst])
n_5m_bl    = np.median([len(b[0]) for b in blocks_5m_bl])
n_5m_bst   = np.median([len(b[0]) for b in blocks_5m_bst])

print()
print(f"  EV deterministico mensile (deterministico, no compounding):")
print(f"  baseline 5m @0.5%: {n_5m_bl:.0f} × {avg_5m_bl:+.4f}R × 0.5% = {n_5m_bl*avg_5m_bl*0.005*100:+.2f}% equity")
for r in [0.005, 0.0075, 0.010]:
    ev = n_5m_bst * avg_5m_bst * r
    print(f"  best 5m     @{r*100:.2f}%: {n_5m_bst:.0f} × {avg_5m_bst:+.4f}R × {r*100:.2f}% = {ev*100:+.2f}% equity")


# ═══ MC scenarios ═════════════════════════════════════════════════════════════
print()
print(SEP)
print("  MC v6 — €100k, 12 mesi, 5,000 sim")
print(SEP)

scenarios = [
    ("Baseline TRIPLO 5m @ 0.5% risk",         blocks_5m_bl,  RISK_5M_DEFAULT, False),
    ("Best 5m @ 0.5% risk",                    blocks_5m_bst, 0.0050, False),
    ("Best 5m @ 0.75% risk (1.5×)",            blocks_5m_bst, 0.0075, False),
    ("Best 5m @ 1.0% risk (2.0×)",             blocks_5m_bst, 0.0100, False),
    ("Baseline TRIPLO 5m @ tier-based",        blocks_5m_bl,  RISK_5M_DEFAULT, True),
    ("Best 5m @ tier-based (0.5% base)",       blocks_5m_bst, 0.0050, True),
]

print(f"\n  {'Scenario':<42} {'Mediana':>11} {'Worst5%':>11} {'p25':>10} {'p75':>11} "
      f"{'ProbP':>6} {'DDmed':>6} {'DDp95':>6}")
print("  " + "-"*98)
results = []
for lab, blks, r, tier in scenarios:
    mc = run_mc(blocks_1h, blks, ra=RISK_1H_DEFAULT, rb=r, tier_b=tier)
    results.append((lab, mc, r))
    print(f"  {lab:<42} {mc['med']:>11,.0f} {mc['p05']:>11,.0f} {mc['p25']:>10,.0f} "
          f"{mc['p75']:>11,.0f} {mc['prob']*100:>5.1f}% "
          f"{mc['dd_med']*100:>5.1f}% {mc['dd_p95']*100:>5.1f}%")

# Solo 5m isolato
print()
print(f"  {'Solo 5m (no 1h, isolato)':<42} {'Mediana':>11} {'Worst5%':>11} {'DDp95':>6}")
print("  " + "-"*70)
for lab, blks, r, tier in scenarios:
    mc = run_mc([], blks, ra=0, rb=r, tier_b=tier)
    print(f"  {lab:<42} {mc['med']:>11,.0f} {mc['p05']:>11,.0f} {mc['dd_p95']*100:>5.1f}%")


# ═══ Verifica drawdown comparativo ═════════════════════════════════════════════
print()
print(SEP)
print("  RIEPILOGO: delta vs baseline")
print(SEP)
baseline = results[0][1]
print(f"  {'Scenario':<42} {'Δ Mediana':>11} {'Δ Worst5%':>11} {'Δ DDp95':>10}")
print("  " + "-"*78)
for lab, mc, r in results[1:]:
    dm = (mc['med']/baseline['med']-1)*100
    dw = (mc['p05']/baseline['p05']-1)*100
    ddd = (mc['dd_p95']-baseline['dd_p95'])*100
    print(f"  {lab:<42} {dm:>+10.1f}% {dw:>+10.1f}% {ddd:>+9.2f}pp")


# ═══ Test Opzione B più granulare ══════════════════════════════════════════════
print()
print(SEP)
print("  Opzione B — Tier-based risk sizing (varie soglie)")
print(SEP)
print("  Verifica che il tier-based mantenga edge senza esporre troppo i risk alti")
print()

# Tier-based: simula solo, no MC
tier_versions = [
    ("flat 0.5%",            lambda rp: 1.0),
    ("inv-linear",            lambda rp: max(0.4, min(1.0, 0.75/rp))),
    ("conservative tier",     lambda rp: 1.0 if rp<=0.75 else (0.7 if rp<=1.5 else 0.5)),
    ("aggressive tier",       lambda rp: 1.2 if rp<=0.75 else (0.8 if rp<=1.5 else 0.5)),
    ("ultra-conservative",    lambda rp: 1.0 if rp<=0.75 else (0.5 if rp<=1.5 else 0.25)),
]

# Sul baseline TRIPLO
df_b = df_baseline.copy()
df_b["mult"] = df_b["risk_pct"].apply(lambda rp: 1.0)
df_b["weighted_eff"] = (df_b["eff_r_cfgc"] - SLIP) * df_b["mult"]

print(f"  {'Variant':<30} {'avg weighted eff':>18} {'avg mult':>10}")
print("  " + "-"*66)
for name, fn in tier_versions:
    df_b["mult"] = df_b["risk_pct"].apply(fn)
    df_b["weighted_eff"] = (df_b["eff_r_cfgc"] - SLIP) * df_b["mult"]
    print(f"  {name:<30} {df_b['weighted_eff'].mean():>+18.4f} {df_b['mult'].mean():>10.4f}")


# ═══ MC con tier conservativo aggressive ═══════════════════════════════════════
print()
print(SEP)
print("  MC tier 'conservative' (default) vs 'aggressive' (1.2× sui setup low-risk)")
print(SEP)


def run_mc_custom_tier(blocks_b, multiplier_fn, ra=RISK_1H_DEFAULT, rb=RISK_5M_DEFAULT,
                       cap=CAPITAL, nsim=5000, seed=42, n_months=12):
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim); dds = np.empty(nsim)
    idx_a = np.arange(len(blocks_1h)); idx_b = np.arange(len(blocks_b))
    for i in range(nsim):
        eq = cap; pk = cap; md = 0.0
        for _ in range(n_months):
            r_a = eq*ra; r_b = eq*rb
            pnl = 0.0
            eff_a, _ = blocks_1h[rng.choice(idx_a)]
            pnl += (eff_a * r_a).sum()
            eff_b, risk_b_arr = blocks_b[rng.choice(idx_b)]
            mults = np.array([multiplier_fn(rp) for rp in risk_b_arr])
            pnl += (eff_b * r_b * mults).sum()
            eq = max(0, eq + pnl)
            if eq > pk: pk = eq
            if pk > 0:
                dd = (pk-eq)/pk
                if dd > md: md = dd
        finals[i] = eq; dds[i] = md
    return dict(med=np.median(finals), p05=np.percentile(finals,5),
                p95=np.percentile(finals,95),
                dd_med=np.median(dds), dd_p95=np.percentile(dds,95))

print(f"\n  {'Tier variant on BASELINE':<32} {'Mediana':>11} {'Worst5%':>11} {'DDp95':>6}")
print("  " + "-"*72)
for name, fn in tier_versions:
    mc = run_mc_custom_tier(blocks_5m_bl, fn)
    print(f"  {name:<32} {mc['med']:>11,.0f} {mc['p05']:>11,.0f} {mc['dd_p95']*100:>5.1f}%")

print(f"\n  {'Tier variant on BEST':<32} {'Mediana':>11} {'Worst5%':>11} {'DDp95':>6}")
print("  " + "-"*72)
for name, fn in tier_versions:
    mc = run_mc_custom_tier(blocks_5m_bst, fn)
    print(f"  {name:<32} {mc['med']:>11,.0f} {mc['p05']:>11,.0f} {mc['dd_p95']*100:>5.1f}%")


print()
print(SEP)
print("  CONCLUSIONI")
print(SEP)
