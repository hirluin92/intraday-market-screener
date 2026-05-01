"""
VERIFICA OOS dei TOP finding prima di implementare.
Tutti i test sul pool TRIPLO 5m, spaccatura per anno (2024 / 2025 / 2026 OOS).
"""
from __future__ import annotations
import os, numpy as np, pandas as pd, psycopg2
from psycopg2.extras import execute_values
import warnings; warnings.filterwarnings("ignore")

CSV_5M = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv"
CSV_1H = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production_2026.csv"
PPR_CACHE = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_ppr_cache_5m.parquet"
SLIP = 0.15
RISK_1H_DEFAULT = 0.015
RISK_5M_DEFAULT = 0.005
CAPITAL = 100_000.0
SLOT_5M = 48; SLOT_1H = 66
SEP = "=" * 92
SEP2 = "-" * 92

PATTERNS = {"double_bottom","double_top","macd_divergence_bull","macd_divergence_bear",
            "rsi_divergence_bull","rsi_divergence_bear"}
SYMBOLS_BLOCKED_5M = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL"}
VAL_SYMS_5M = {"GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL","ACHR","ASTS","JOBY",
    "RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX","NVO","LLY","MRNA","NKE","TGT","MP",
    "NEM","WMT","MU","LUNR","CAT","GS"} - SYMBOLS_BLOCKED_5M

# ─── eff_r ────────────────────────────────────────────────────────────────────
def cr(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d

def eff_r_split(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        rn=0.5 if r1>=1.0 else (0.0 if r1>=0.5 else -1.0)
        return 0.5*r1+0.5*rn
    if o in ("stop","stopped","sl"): return -1.0
    return pr

def eff_r_cfgc(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
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

def eff_r_cfgd(row):
    """Config D: trail progressivo step 0.5R."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if mfe >= 2.5: lock = 2.0
    elif mfe >= 2.0: lock = 1.5
    elif mfe >= 1.5: lock = 1.0
    elif mfe >= 1.0: lock = 0.5
    elif mfe >= 0.5: lock = 0.0
    else: lock = -1.0
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        runner = max(lock, 0.5) if mfe < r2 else r2
        return 0.5*r1+0.5*runner
    if o in ("stop","stopped","sl"):
        return lock
    return pr

def eff_r_full_tp1(row):
    """Split 100/0: chiude tutto a TP1, no runner."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    if o in ("tp1","tp2"): return r1
    if o in ("stop","stopped","sl"): return -1.0
    return pr

def eff_r_atr_dynamic(row, mult_high=1.25, mult_low=0.85, atr_high=0.5, atr_low=0.2):
    """Config C ma con TP1 multiplier basato su ATR%."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    atr_pct = row.get("atr_pct")
    r1_base=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    # Adjust TP1
    if pd.notna(atr_pct):
        if atr_pct > atr_high:
            r1 = r1_base * mult_high
        elif atr_pct < atr_low:
            r1 = r1_base * mult_low
        else:
            r1 = r1_base
    else:
        r1 = r1_base
    # MFE >= adjusted TP1 → trade fa TP1
    if o == "tp2":
        return 0.5*r1 + 0.5*r2
    if o == "tp1":
        # Verifica se mfe ha raggiunto adjusted r1 (importante se r1 > r1_base)
        if mfe >= r1:
            if mfe >= r2: runner = r2
            elif mfe >= 1.0: runner = 0.5
            elif mfe >= 0.5: runner = 0.0
            else: runner = -1.0
            return 0.5*r1 + 0.5*runner
        # Se mfe < adjusted r1 (perché abbiamo alzato target), il trade non chiude più a TP1
        # Stima: outcome diventa stop o timeout. MFE è quello che ha raggiunto.
        if mfe >= 1.0: return 0.5  # locked breakeven+ via Config C
        if mfe >= 0.5: return 0.0
        return -1.0
    if o in ("stop","stopped","sl"):
        if mfe>=1.0: return 0.5
        if mfe>=0.5: return 0.0
        return -1.0
    return pr


# ─── Carica pool TRIPLO ──────────────────────────────────────────────────────
df_raw = pd.read_csv(CSV_5M)
df_raw["pattern_timestamp"] = pd.to_datetime(df_raw["pattern_timestamp"], utc=True)
df_raw["hour_et"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour

df_b = df_raw[
    df_raw["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df_raw["pattern_name"].isin(PATTERNS) &
    df_raw["provider"].isin(["alpaca"]) &
    (df_raw["pattern_strength"].fillna(0) >= 0.60) &
    df_raw["symbol"].isin(VAL_SYMS_5M) &
    (df_raw["hour_et"] >= 11) & (df_raw["hour_et"] <= 16) &
    (df_raw["risk_pct"] >= 0.50) & (df_raw["risk_pct"] <= 2.00)
].copy()
df_ppr = pd.read_parquet(PPR_CACHE)
df_b = df_b.merge(df_ppr, on=["symbol","exchange","provider","pattern_timestamp"], how="left")

def is_triplo(row):
    h = row["hour_et"]
    if h >= 15: return True
    if h < 11: return False
    if pd.isna(row["ppr"]): return False
    pos = row["ppr"]; d = str(row["direction"]).lower()
    return ((d=="bullish" and pos<=0.10) or (d=="bearish" and pos>=0.90))

df_b["triplo"] = df_b.apply(is_triplo, axis=1)
df = df_b[df_b["triplo"]].copy()
df["year"] = df["pattern_timestamp"].dt.year

# ATR JOIN dal DB (riusa il batch)
print(SEP)
print("  VERIFICA OOS — TOP FINDING")
print(SEP)
print(f"\n  Pool TRIPLO 5m: {len(df):,} trade")
print(f"  Anni: {sorted(df['year'].unique())}")
print(f"  Per anno: " + " ".join(f"{y}={(df['year']==y).sum()}" for y in sorted(df['year'].unique())))

print("\n  Caricamento ATR dal DB...")
conn = psycopg2.connect(host="localhost", port=5432, user="postgres",
                        password="postgres", dbname="intraday_market_screener")
cur = conn.cursor()
keys = [(s,e,p,t) for s,e,p,t in zip(df["symbol"],df["exchange"],df["provider"],df["pattern_timestamp"])]
cur.execute("CREATE TEMP TABLE _kk (sym VARCHAR(32), ex VARCHAR(32), prov VARCHAR(32), ts TIMESTAMPTZ)")
execute_values(cur, "INSERT INTO _kk VALUES %s", keys, page_size=5000)
conn.commit()
cur.execute("""
  SELECT k.sym, k.ex, k.prov, k.ts, ci.atr_14
  FROM _kk k LEFT JOIN candle_indicators ci
    ON ci.symbol=k.sym AND ci.exchange=k.ex AND ci.provider=k.prov
    AND ci.timeframe='5m' AND ci.timestamp=k.ts
""")
atr_rows = cur.fetchall()
conn.close()
atr_map = {(s,e,p,pd.Timestamp(t).tz_convert("UTC")): float(a) if a else None for s,e,p,t,a in atr_rows}
df["atr_14"] = [atr_map.get((s,e,p,t.tz_convert("UTC")), None)
                for s,e,p,t in zip(df["symbol"],df["exchange"],df["provider"],df["pattern_timestamp"])]
df["atr_pct"] = df["atr_14"] / df["entry_price"] * 100

# Calcola tutte le varianti eff_r
df["eff_cfgc"] = df.apply(eff_r_cfgc, axis=1)
df["eff_cfgd"] = df.apply(eff_r_cfgd, axis=1)
df["eff_split"] = df.apply(eff_r_split, axis=1)
df["eff_full_tp1"] = df.apply(eff_r_full_tp1, axis=1)
df["eff_atr_dyn_125"] = df.apply(lambda r: eff_r_atr_dynamic(r, 1.25, 0.85), axis=1)
df["eff_atr_dyn_115"] = df.apply(lambda r: eff_r_atr_dynamic(r, 1.15, 0.85), axis=1)
df["eff_atr_dyn_150"] = df.apply(lambda r: eff_r_atr_dynamic(r, 1.50, 0.85), axis=1)
df["eff_atr_dyn_125_only_high"] = df.apply(lambda r: eff_r_atr_dynamic(r, 1.25, 1.00), axis=1)
df["eff_atr_dyn_only_low"] = df.apply(lambda r: eff_r_atr_dynamic(r, 1.0, 0.85), axis=1)


# ─── Helper: edge per anno ───────────────────────────────────────────────────
def edge_by_year(d, col, years=(2024, 2025, 2026), min_n=20):
    out = {}
    for y in years:
        sub = d[d["year"] == y]
        if len(sub) < min_n:
            out[y] = (None, len(sub))
        else:
            out[y] = ((sub[col]-SLIP).mean(), len(sub))
    return out

def fmt_year(d):
    return " ".join([f"{y}={v[0]:+.4f}(n={v[1]})" if v[0] is not None else f"{y}=n/a(n={v[1]})"
                     for y, v in d.items()])

def stable(d_baseline, d_new, years=(2024,2025,2026)):
    """True se d_new > d_baseline in tutti gli anni con n sufficienti."""
    for y in years:
        bv, _ = d_baseline[y]; nv, _ = d_new[y]
        if bv is None or nv is None: return False
        if nv <= bv: return False
    return True


# ═══ VERIFICA #11 — TP DINAMICO PER ATR ═══════════════════════════════════════
print()
print(SEP)
print("  VERIFICA #11 — TP DINAMICO PER ATR")
print(SEP)
print(f"\n  Baseline (Config C):")
y_cfgc = edge_by_year(df, "eff_cfgc")
for y, (v, n) in y_cfgc.items():
    print(f"    {y}: {v:+.4f}R (n={n})" if v else f"    {y}: n/a (n={n})")

print(f"\n  TP × 1.25 se ATR>0.5%, ×0.85 se ATR<0.2% (proposta originale):")
y_atr = edge_by_year(df, "eff_atr_dyn_125")
for y, (v, n) in y_atr.items():
    bv = y_cfgc[y][0]
    delta = v - bv if (v is not None and bv is not None) else None
    delta_str = f"Δ={delta:+.4f}" if delta is not None else "Δ=n/a"
    print(f"    {y}: {v:+.4f}R (n={n})  vs base {bv:+.4f}R  {delta_str}")

print(f"\n  Varianti TP dinamico per ATR:")
print(f"  {'rule':<48} {'2024':>10} {'2025':>10} {'2026 OOS':>11} {'stab?':<7}")
print("  " + SEP2)
variants = [
    ("TP×1.25 se ATR>0.5% & ×0.85 se ATR<0.2%", "eff_atr_dyn_125"),
    ("TP×1.15 se ATR>0.5% & ×0.85 se ATR<0.2%", "eff_atr_dyn_115"),
    ("TP×1.50 se ATR>0.5% & ×0.85 se ATR<0.2%", "eff_atr_dyn_150"),
    ("TP×1.25 SOLO se ATR>0.5% (no penalty low)", "eff_atr_dyn_125_only_high"),
    ("TP×0.85 SOLO se ATR<0.2% (no boost high)", "eff_atr_dyn_only_low"),
]
for lab, col in variants:
    y_v = edge_by_year(df, col)
    is_stab = stable(y_cfgc, y_v)
    cells = []
    for y in (2024, 2025, 2026):
        bv = y_cfgc[y][0]; nv = y_v[y][0]
        if bv is None or nv is None:
            cells.append(f"{'n/a':>10}")
        else:
            cells.append(f"{nv:+.4f}".rjust(10))
    print(f"  {lab:<48} {cells[0]} {cells[1]} {cells[2]}  {'YES' if is_stab else 'NO':<6}")


# ═══ VERIFICA #7 — RISK SIZE PER ORA ET ═══════════════════════════════════════
print()
print(SEP)
print("  VERIFICA #7 — EDGE PER ORA ET (per anno)")
print(SEP)
print(f"\n  {'Hour':<6} {'2024 eff (n)':>20} {'2025 eff (n)':>20} {'2026 eff (n)':>20}  {'stab15?':<6}")
print("  " + SEP2)
hours = sorted(df["hour_et"].unique())
for h in hours:
    sub = df[df["hour_et"] == h]
    cells = []
    vals = []
    for y in (2024, 2025, 2026):
        s = sub[sub["year"] == y]
        if len(s) < 5:
            cells.append(f"n/a (n={len(s)})".rjust(20))
            vals.append(None)
        else:
            v = (s["eff_cfgc"]-SLIP).mean()
            cells.append(f"{v:+.4f} (n={len(s)})".rjust(20))
            vals.append(v)
    # Stable se tutti i 3 anni > 0.50R per ora 15
    stab = "—"
    if h == 15:
        if all(v is not None and v > 0.50 for v in vals):
            stab = "YES"
        else:
            stab = "NO"
    print(f"  {h:<6} {cells[0]} {cells[1]} {cells[2]}  {stab:<6}")

# Verifica risk-tier OOS-style
print(f"\n  Test: applichiamo risk-tier {{15:0.75%, 12-14:0.50%, 11/16:0.30%}} solo per anno")
def weighted_eq_pct(sub):
    """% equity per mese aggregata con risk variabile per ora."""
    if len(sub) == 0: return None, 0
    risk_for_h = lambda h: 0.0075 if h==15 else (0.005 if 12<=h<=14 else 0.003)
    # Edge medio per trade, pesato per risk
    eff_arr = (sub["eff_cfgc"] - SLIP).values
    risk_arr = sub["hour_et"].map(risk_for_h).values
    # P&L per trade in % equity = eff × risk
    pct_per_trade = eff_arr * risk_arr * 100
    return pct_per_trade.mean(), len(sub)

print(f"  {'periodo':<14} {'%eq/trade base':>16} {'%eq/trade tier':>16}  Δ%")
for y in (2024, 2025, 2026):
    sub = df[df["year"] == y]
    if len(sub) < 30: continue
    base_pct = (sub["eff_cfgc"] - SLIP).mean() * 0.005 * 100
    tier_pct, _ = weighted_eq_pct(sub)
    print(f"  {y:<14} {base_pct:>+16.4f}% {tier_pct:>+16.4f}% Δ={(tier_pct-base_pct):+.4f}pp")


# ═══ VERIFICA #12 — TRAILING CONFIG D ═════════════════════════════════════════
print()
print(SEP)
print("  VERIFICA #12 — TRAILING CONFIG D (steps 0.5R)")
print(SEP)
print(f"\n  {'Anno':<8} {'n':>5} {'Config C':>12} {'Config D':>12} {'Δ':>10}")
print("  " + SEP2)
y_cfgd = edge_by_year(df, "eff_cfgd")
all_pos = True
for y in (2024, 2025, 2026):
    cv = y_cfgc[y][0]; dv = y_cfgd[y][0]; n = y_cfgc[y][1]
    if cv is None or dv is None:
        print(f"  {y:<8} {n:>5} {'n/a':>12} {'n/a':>12} {'n/a':>10}")
        continue
    delta = dv - cv
    if delta <= 0: all_pos = False
    print(f"  {y:<8} {n:>5} {cv:>+12.4f} {dv:>+12.4f} {delta:>+10.4f}")
print(f"\n  Stabile in tutti gli anni: {'YES' if all_pos else 'NO'}")


# ═══ VERIFICA #26 — SPLIT 100/0 ═══════════════════════════════════════════════
print()
print(SEP)
print("  VERIFICA #26 — SPLIT 100/0 (full TP1, no runner)")
print(SEP)
print(f"\n  {'Anno':<8} {'n':>5} {'Split 50/50':>14} {'Full TP1':>14} {'Δ':>10}")
print("  " + SEP2)
y_full = edge_by_year(df, "eff_full_tp1")
all_pos = True
for y in (2024, 2025, 2026):
    sv = y_cfgc[y][0]; fv = y_full[y][0]; n = y_cfgc[y][1]
    if sv is None or fv is None:
        print(f"  {y:<8} {n:>5} {'n/a':>14} {'n/a':>14} {'n/a':>10}")
        continue
    delta = fv - sv
    if delta <= 0: all_pos = False
    print(f"  {y:<8} {n:>5} {sv:>+14.4f} {fv:>+14.4f} {delta:>+10.4f}")
print(f"\n  Full TP1 batte Split (Config C) in tutti gli anni: {'YES' if all_pos else 'NO'}")

# Quanti TP2 perdiamo?
n_tp2 = (df["outcome"] == "tp2").sum()
n_tp1 = (df["outcome"] == "tp1").sum()
print(f"\n  Note trade-off:")
print(f"    Total TP2 nel pool: {n_tp2}/{len(df)} = {n_tp2/len(df)*100:.1f}%")
print(f"    Total TP1: {n_tp1}/{len(df)} = {n_tp1/len(df)*100:.1f}%")
print(f"    Con Full TP1: i {n_tp2} trade TP2 chiudono a +TP1 anziché +TP2")
e_tp1_avg = df[df["outcome"]=="tp2"].apply(
    lambda r: cr(r["entry_price"],r["stop_price"],r["tp1_price"]), axis=1).mean()
e_tp2_avg = df[df["outcome"]=="tp2"].apply(
    lambda r: cr(r["entry_price"],r["stop_price"],r["tp2_price"]), axis=1).mean()
print(f"    Diff: TP2 medio (+{e_tp2_avg:.2f}R) vs TP1 medio (+{e_tp1_avg:.2f}R) = +{e_tp2_avg-e_tp1_avg:.2f}R perso per metà")


# ═══ VERIFICA HOLD MAX ════════════════════════════════════════════════════════
print()
print(SEP)
print("  VERIFICA HOLD MAX (16 vs 24 vs 8)")
print(SEP)
print(f"\n  {'Anno':<8} {'n_24':>5} {'eff_24 (cfgc)':>14} {'eff_16':>10} {'eff_8':>10} {'Δ16':>10} {'Δ8':>10}")
print("  " + SEP2)
for y in (2024, 2025, 2026):
    sub = df[df["year"] == y]
    if len(sub) < 30: continue
    e24 = (sub["eff_cfgc"]-SLIP).mean()
    sub_16 = sub[sub["bars_to_exit"] <= 16]
    e16 = (sub_16["eff_cfgc"]-SLIP).mean() if len(sub_16) else None
    sub_8 = sub[sub["bars_to_exit"] <= 8]
    e8 = (sub_8["eff_cfgc"]-SLIP).mean() if len(sub_8) else None
    d16 = e16-e24 if e16 else None
    d8 = e8-e24 if e8 else None
    print(f"  {y:<8} {len(sub):>5} {e24:>+14.4f} "
          f"{(f'{e16:+.4f}' if e16 else 'n/a'):>10} "
          f"{(f'{e8:+.4f}' if e8 else 'n/a'):>10} "
          f"{(f'{d16:+.4f}' if d16 else 'n/a'):>10} "
          f"{(f'{d8:+.4f}' if d8 else 'n/a'):>10}")


# ═══ COMBO: tutti i finding confermati ════════════════════════════════════════
print()
print(SEP)
print("  COMBO — tutti i finding confermati insieme")
print(SEP)

# Determina cosa è confermato
print("\n  Determinazione finding confermati:")
print(f"  - TP per ATR (proposta 1.25/0.85): vediamo i tre anni")
y_atr_125 = edge_by_year(df, "eff_atr_dyn_125")
print(f"      {fmt_year(y_atr_125)}")
print(f"      Stabile? {stable(y_cfgc, y_atr_125)}")

print(f"  - Config D vs C: stabile? ", end="")
stable_d = all(y_cfgd[y][0] > y_cfgc[y][0] for y in (2024,2025,2026)
               if y_cfgd[y][0] is not None and y_cfgc[y][0] is not None)
print("YES" if stable_d else "NO")

print(f"  - Full TP1 vs Split: stabile? ", end="")
stable_full = all(y_full[y][0] > y_cfgc[y][0] for y in (2024,2025,2026)
                  if y_full[y][0] is not None and y_cfgc[y][0] is not None)
print("YES" if stable_full else "NO")

print(f"  - Risk per ora 15 stabile (>+0.5R OOS)? ", end="")
sub_h15 = df[df["hour_et"] == 15]
v_2026 = (sub_h15[sub_h15["year"]==2026]["eff_cfgc"]-SLIP).mean()
print(f"YES (2026: {v_2026:+.4f}R)" if v_2026 > 0.5 else f"NO (2026: {v_2026:+.4f}R)")


# Combo: Config D + risk per ora
print(f"\n  COMBO 1: Config D (trail steps 0.5R)")
print(f"  COMBO 2: Config D + Risk per ora ET (tier 0.75/0.5/0.3%)")
print(f"  COMBO 3: Config D + TP per ATR (se conferma)")
print(f"  COMBO 4: Config D + Risk per ora + TP per ATR (full stack)")

def build_blocks(d, slot_cap, eff_col):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for _, sub in d.groupby("ym"):
        sub = sub.head(slot_cap)
        if len(sub) > 0:
            blocks.append((sub[eff_col]-SLIP).values)
    return blocks

def build_blocks_with_risk(d, slot_cap, eff_col, risk_col):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for _, sub in d.groupby("ym"):
        sub = sub.head(slot_cap)
        if len(sub) > 0:
            blocks.append(((sub[eff_col]-SLIP).values, sub[risk_col].values))
    return blocks


# 1h pool baseline
df1 = pd.read_csv(CSV_1H)
df1["pattern_timestamp"] = pd.to_datetime(df1["pattern_timestamp"], utc=True)
df1 = df1[
    df1["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df1["pattern_name"].isin(PATTERNS) &
    ~df1["provider"].isin(["ibkr"]) &
    (df1["pattern_strength"].fillna(0) >= 0.60)
].copy()
df1["eff_split"] = df1.apply(eff_r_split, axis=1)
blocks_1h = build_blocks(df1, SLOT_1H, "eff_split")

def run_mc_static_risk(b1, b5_eff, ra=RISK_1H_DEFAULT, rb=RISK_5M_DEFAULT, nsim=2000, seed=42):
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim)
    have_a = len(b1)>0; have_b = len(b5_eff)>0
    ia = np.arange(len(b1)); ib = np.arange(len(b5_eff))
    for i in range(nsim):
        eq = CAPITAL
        for _ in range(12):
            r_a=eq*ra; r_b=eq*rb; pnl=0.0
            if have_a: pnl += (b1[rng.choice(ia)]*r_a).sum()
            if have_b: pnl += (b5_eff[rng.choice(ib)]*r_b).sum()
            eq = max(0, eq+pnl)
        finals[i] = eq
    return dict(med=np.median(finals), p05=np.percentile(finals,5))

def run_mc_dyn_risk(b1, b5_pairs, nsim=2000, seed=42):
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim)
    have_a = len(b1)>0
    ia = np.arange(len(b1)); ib = np.arange(len(b5_pairs))
    for i in range(nsim):
        eq = CAPITAL
        for _ in range(12):
            r_a = eq*RISK_1H_DEFAULT; pnl=0.0
            if have_a: pnl += (b1[rng.choice(ia)]*r_a).sum()
            eff_b, rsk_b = b5_pairs[rng.choice(ib)]
            pnl += (eff_b * eq * rsk_b).sum()
            eq = max(0, eq+pnl)
        finals[i] = eq
    return dict(med=np.median(finals), p05=np.percentile(finals,5))


# Pre-build blocks for each option
blocks_5m_C = build_blocks(df, SLOT_5M, "eff_cfgc")
blocks_5m_D = build_blocks(df, SLOT_5M, "eff_cfgd")
blocks_5m_full = build_blocks(df, SLOT_5M, "eff_full_tp1")
blocks_5m_atr = build_blocks(df, SLOT_5M, "eff_atr_dyn_125")

# Risk per ora: D + risk dinamico
df["risk_for_hour"] = df["hour_et"].apply(
    lambda h: 0.0075 if h==15 else (0.005 if 12<=h<=14 else 0.003))
blocks_5m_D_risk = build_blocks_with_risk(df, SLOT_5M, "eff_cfgd", "risk_for_hour")
blocks_5m_C_risk = build_blocks_with_risk(df, SLOT_5M, "eff_cfgc", "risk_for_hour")

# Combo D + ATR + risk per ora (se ATR conferma)
df["eff_d_atr"] = df.apply(lambda r: eff_r_atr_dynamic(r, 1.25, 0.85), axis=1)  # placeholder = atr_dyn variante
# In realtà serve combinare Config D trailing + ATR-adjusted TP1.
def eff_r_d_atr_combo(row, mult_high=1.25, mult_low=0.85, atr_high=0.5, atr_low=0.2):
    """Config D + ATR-adjusted TP1."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    atr_pct = row.get("atr_pct")
    r1_base=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if pd.notna(atr_pct):
        if atr_pct > atr_high: r1 = r1_base * mult_high
        elif atr_pct < atr_low: r1 = r1_base * mult_low
        else: r1 = r1_base
    else:
        r1 = r1_base
    # Trail Config D lock
    if mfe >= 2.5: lock = 2.0
    elif mfe >= 2.0: lock = 1.5
    elif mfe >= 1.5: lock = 1.0
    elif mfe >= 1.0: lock = 0.5
    elif mfe >= 0.5: lock = 0.0
    else: lock = -1.0
    if o == "tp2":
        return 0.5*r1 + 0.5*r2
    if o == "tp1":
        if mfe >= r1:
            runner = max(lock, 0.5) if mfe < r2 else r2
            return 0.5*r1 + 0.5*runner
        # Se non raggiunge r1 elevato (perché alzato)
        return lock
    if o in ("stop","stopped","sl"):
        return lock
    return pr

df["eff_d_atr_combo"] = df.apply(eff_r_d_atr_combo, axis=1)
blocks_5m_D_atr = build_blocks(df, SLOT_5M, "eff_d_atr_combo")
blocks_5m_D_atr_risk = build_blocks_with_risk(df, SLOT_5M, "eff_d_atr_combo", "risk_for_hour")

print(f"\n  {'Combo':<46} {'n':>5} {'Mediana':>13} {'Worst5%':>13} {'Δmc':>8}")
print("  " + SEP2)
mc_baseline = run_mc_static_risk(blocks_1h, blocks_5m_C)
mc_D = run_mc_static_risk(blocks_1h, blocks_5m_D)
mc_C_risk = run_mc_dyn_risk(blocks_1h, blocks_5m_C_risk)
mc_D_risk = run_mc_dyn_risk(blocks_1h, blocks_5m_D_risk)
mc_atr = run_mc_static_risk(blocks_1h, blocks_5m_atr)
mc_full = run_mc_static_risk(blocks_1h, blocks_5m_full)
mc_D_atr = run_mc_static_risk(blocks_1h, blocks_5m_D_atr)
mc_D_atr_risk = run_mc_dyn_risk(blocks_1h, blocks_5m_D_atr_risk)

results = [
    ("Baseline (Config C, risk 0.5%)", len(df), mc_baseline),
    ("Config D solo", len(df), mc_D),
    ("Config C + Risk per ora", len(df), mc_C_risk),
    ("Config D + Risk per ora", len(df), mc_D_risk),
    ("Config C + TP per ATR", len(df), mc_atr),
    ("Full TP1 (no runner)", len(df), mc_full),
    ("Config D + TP per ATR", len(df), mc_D_atr),
    ("Config D + TP per ATR + Risk per ora (TUTTO)", len(df), mc_D_atr_risk),
]

for lab, n, mc in results:
    delta = (mc["med"]/mc_baseline["med"]-1)*100
    print(f"  {lab:<46} {n:>5} €{mc['med']:>11,.0f} €{mc['p05']:>11,.0f} {delta:>+7.1f}%")


# Per anno con combo finale
print(f"\n  Verifica edge per anno COMBO Config D + TP per ATR + Risk per ora:")
print(f"  {'Anno':<8} {'n':>5} {'eff (combo)':>13} {'eff (base)':>13} {'Δ':>10}")
print("  " + SEP2)
for y in (2024, 2025, 2026):
    sub = df[df["year"] == y]
    if len(sub) < 30: continue
    eff_combo = (sub["eff_d_atr_combo"]-SLIP).mean()
    eff_base = (sub["eff_cfgc"]-SLIP).mean()
    print(f"  {y:<8} {len(sub):>5} {eff_combo:>+13.4f} {eff_base:>+13.4f} {eff_combo-eff_base:>+10.4f}")


print()
print(SEP)
print("  CONCLUSIONI")
print(SEP)
