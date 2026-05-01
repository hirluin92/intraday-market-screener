"""
MC realistico €3k start + €200/mese + slot variabili per capitale.

Config:
  - Pool TRIPLO 5m (Config D + risk per ora) — META/TGT/SCHW esclusi
  - Pool 1h (split + risk 1.5% fisso)
  - 24 mesi sim, 5000 simulazioni
  - Capitale variabile → slot variabili (margine IBKR 2:1):
      < €5k:    2+1 (1h 44/m, 5m 24/m)
      €5-10k:   2+2 (1h 44/m, 5m 48/m)
      >= €10k:  3+2 (1h 66/m, 5m 48/m)
"""
from __future__ import annotations
import os, numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

CSV_5M = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv"
CSV_1H = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production_2026.csv"
PPR_CACHE = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_ppr_cache_5m.parquet"
SLIP = 0.15
RISK_1H = 0.015
CAPITAL_START = 3_000.0
DEPOSIT_MONTHLY = 200.0
N_MONTHS = 24
N_SIM = 5_000
SEP = "=" * 102
SEP2 = "-" * 102

PATTERNS = {"double_bottom","double_top","macd_divergence_bull","macd_divergence_bear",
            "rsi_divergence_bull","rsi_divergence_bear"}
SYMBOLS_BLOCKED_5M = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL","META","TGT","SCHW"}
VAL_SYMS_5M = {"GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL","ACHR","ASTS","JOBY",
    "RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX","NVO","LLY","MRNA","NKE","TGT","MP",
    "NEM","WMT","MU","LUNR","CAT","GS"} - SYMBOLS_BLOCKED_5M

# ─── eff_r helpers ────────────────────────────────────────────────────────────
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

def eff_r_cfgd(row):
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


# ─── Slot config per capitale ────────────────────────────────────────────────
def slots_for_capital(cap: float) -> tuple[int, int]:
    """
    Ritorna (slot_cap_1h_per_month, slot_cap_5m_per_month).
    Margine IBKR 2:1 → buying power = 2× cap.
    """
    if cap < 5_000:
        return (44, 24)   # 2+1: 2 slot 1h, 1 slot 5m
    if cap < 10_000:
        return (44, 48)   # 2+2
    return (66, 48)       # 3+2: pieno


# ─── Carica pool TRIPLO ──────────────────────────────────────────────────────
print(SEP)
print("  MC €3k + €200/m + SLOT VARIABILI")
print(SEP)

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
df5 = df_b[df_b["triplo"]].copy()
df5["eff_d"] = df5.apply(eff_r_cfgd, axis=1)
# Risk per ora ET
df5["risk_h"] = df5["hour_et"].apply(
    lambda h: 0.0075 if h==15 else (0.005 if 12<=h<=14 else 0.003))

df1 = pd.read_csv(CSV_1H)
df1["pattern_timestamp"] = pd.to_datetime(df1["pattern_timestamp"], utc=True)
df1 = df1[
    df1["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df1["pattern_name"].isin(PATTERNS) &
    ~df1["provider"].isin(["ibkr"]) &
    (df1["pattern_strength"].fillna(0) >= 0.60)
].copy()
df1["eff_split"] = df1.apply(eff_r_split, axis=1)

print(f"\n  Pool TRIPLO 5m: {len(df5):,} trade (Config D)")
print(f"    META/TGT/SCHW esclusi (drop universo apr 2026)")
print(f"    avg_eff_d-slip = {(df5['eff_d']-SLIP).mean():+.4f}R")
print(f"    avg risk_h     = {df5['risk_h'].mean()*100:.3f}%")
print(f"  Pool 1h: {len(df1):,} trade (Config C split)")
print(f"    avg_eff-slip = {(df1['eff_split']-SLIP).mean():+.4f}R")


# ─── Build monthly blocks ────────────────────────────────────────────────────
def build_blocks_5m(d):
    """Lista blocchi mensili 5m: ognuno è (eff_arr, risk_arr) ordinato per timestamp."""
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for _, sub in d.groupby("ym", sort=True):
        if len(sub) > 0:
            eff = (sub["eff_d"] - SLIP).values
            rsk = sub["risk_h"].values
            blocks.append((eff, rsk))
    return blocks

def build_blocks_1h(d):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for _, sub in d.groupby("ym", sort=True):
        if len(sub) > 0:
            blocks.append((sub["eff_split"] - SLIP).values)
    return blocks

blocks_5m = build_blocks_5m(df5)
blocks_1h = build_blocks_1h(df1)
print(f"\n  Blocchi mensili: 1h={len(blocks_1h)} | 5m={len(blocks_5m)}")
print(f"  Trade/mese mediano: 1h={int(np.median([len(b) for b in blocks_1h]))} | "
      f"5m={int(np.median([len(b[0]) for b in blocks_5m]))}")


# ─── MC engine: capitale variabile + slot variabili + deposit mensile ────────
def run_mc(blocks_a, blocks_b, edge_a=1.0, edge_b=1.0,
          cap_start=CAPITAL_START, deposit=DEPOSIT_MONTHLY,
          n_months=N_MONTHS, n_sim=N_SIM, seed=42, ra_pct=RISK_1H):
    """
    Ritorna:
      finals: array equity finali (n_sim,)
      trace_eq: matrice equity per mese (n_sim, n_months)  — per percentili mensili
      milestones: dict {soglia: array_mesi_per_sim} per equity > soglia
    """
    rng = np.random.default_rng(seed)
    finals = np.empty(n_sim)
    trace_eq = np.empty((n_sim, n_months))
    milestone_levels = [5_000, 10_000, 25_000, 50_000, 100_000]
    milestones = {m: np.full(n_sim, -1, dtype=int) for m in milestone_levels}

    ia = np.arange(len(blocks_a)); ib = np.arange(len(blocks_b))

    for i in range(n_sim):
        eq = cap_start
        for m in range(n_months):
            # 1. Aggiungi deposit a inizio mese
            eq += deposit
            # 2. Determina slot per capitale
            slot1, slot5 = slots_for_capital(eq)
            # 3. Campiona blocco mensile e prendi primi slot trade
            r_a = eq * ra_pct  # 1h risk fisso 1.5%
            blk_a = blocks_a[rng.choice(ia)]
            blk_a_used = blk_a[:slot1]
            pnl = (blk_a_used * edge_a * r_a).sum()
            # 5m: risk variabile per ora del trade
            eff_b, risk_b = blocks_b[rng.choice(ib)]
            eff_b_used  = eff_b[:slot5]
            risk_b_used = risk_b[:slot5]
            pnl += (eff_b_used * edge_b * eq * risk_b_used).sum()
            eq = max(0.0, eq + pnl)
            # 4. Track milestones
            for m_level in milestone_levels:
                if milestones[m_level][i] < 0 and eq >= m_level:
                    milestones[m_level][i] = m + 1  # 1-indexed
            trace_eq[i, m] = eq
        finals[i] = eq
    return dict(finals=finals, trace=trace_eq, milestones=milestones)


# ─── Run principale ─────────────────────────────────────────────────────────
print(f"\n  Simulazione: {N_SIM:,} sim × {N_MONTHS} mesi (€{CAPITAL_START:,.0f} start + €{DEPOSIT_MONTHLY:.0f}/m)")
print(f"  Slot variabili: <€5k=2+1 | €5-10k=2+2 | >=€10k=3+2")
print(f"  Calcolo MC...")

mc100 = run_mc(blocks_1h, blocks_5m, edge_a=1.0, edge_b=1.0)
mc50  = run_mc(blocks_1h, blocks_5m, edge_a=0.5, edge_b=0.5, seed=43)
mc25  = run_mc(blocks_1h, blocks_5m, edge_a=0.25, edge_b=0.25, seed=44)
mc10  = run_mc(blocks_1h, blocks_5m, edge_a=0.10, edge_b=0.10, seed=45)


# ═══ TABELLA 1 — Equity mensile (mediana, p5, p95) ═══════════════════════════
print()
print(SEP)
print("  TABELLA 1 — Equity mensile (edge 100%)")
print(SEP)
print(f"\n  {'Mese':>4} {'Slot':<6} {'Trade/m':>8} {'Versato':>9} {'Mediana eq':>12} "
      f"{'p5 eq':>10} {'p95 eq':>12} {'Profitto med':>13}")
print("  " + SEP2)
total_deposited = CAPITAL_START
for m in range(N_MONTHS):
    total_deposited += DEPOSIT_MONTHLY
    med_eq = np.median(mc100["trace"][:, m])
    p05_eq = np.percentile(mc100["trace"][:, m], 5)
    p95_eq = np.percentile(mc100["trace"][:, m], 95)
    s1, s5 = slots_for_capital(med_eq)
    slot_str = "2+1" if (s1, s5) == (44, 24) else ("2+2" if s5 == 48 and s1 == 44 else "3+2")
    trade_per_m = s1 + s5
    profit_m = med_eq - total_deposited
    print(f"  {m+1:>4} {slot_str:<6} {trade_per_m:>8} €{total_deposited:>7,.0f} "
          f"€{med_eq:>10,.0f} €{p05_eq:>8,.0f} €{p95_eq:>10,.0f} €{profit_m:>+11,.0f}")


# ═══ TABELLA 2 — Edge degradation a 24 mesi ═══════════════════════════════════
print()
print(SEP)
print("  TABELLA 2 — Edge degradation a 24 mesi")
print(SEP)
total_dep_24m = CAPITAL_START + DEPOSIT_MONTHLY * N_MONTHS
print(f"\n  Versato totale dopo 24 mesi: €{total_dep_24m:,.0f}")
print(f"\n  {'Edge':>6} {'Mediana 24m':>13} {'Worst 5%':>11} {'p25':>11} {'p75':>11} "
      f"{'Profitto med':>14} {'ROI med':>9}")
print("  " + SEP2)
for label, mc in [("100%", mc100), ("50%", mc50), ("25%", mc25), ("10%", mc10)]:
    f = mc["finals"]
    med = np.median(f); p05 = np.percentile(f, 5)
    p25 = np.percentile(f, 25); p75 = np.percentile(f, 75)
    profit = med - total_dep_24m
    roi = profit / total_dep_24m * 100
    print(f"  {label:>6} €{med:>11,.0f} €{p05:>9,.0f} €{p25:>9,.0f} €{p75:>9,.0f} "
          f"€{profit:>+12,.0f} {roi:>+7.1f}%")


# ═══ TABELLA 3 — Confronto slot fisso vs variabile ═══════════════════════════
print()
print(SEP)
print("  TABELLA 3 — Confronto slot policy")
print(SEP)

def run_mc_fixed_slots(blocks_a, blocks_b, slot1_fixed, slot5_fixed,
                       cap_start=CAPITAL_START, deposit=DEPOSIT_MONTHLY,
                       n_months=N_MONTHS, n_sim=N_SIM, seed=46):
    rng = np.random.default_rng(seed)
    finals = np.empty(n_sim)
    trace = np.empty((n_sim, n_months))
    ia = np.arange(len(blocks_a)); ib = np.arange(len(blocks_b))
    for i in range(n_sim):
        eq = cap_start
        for m in range(n_months):
            eq += deposit
            r_a = eq * RISK_1H
            blk_a = blocks_a[rng.choice(ia)][:slot1_fixed]
            pnl = (blk_a * r_a).sum()
            eff_b, risk_b = blocks_b[rng.choice(ib)]
            pnl += (eff_b[:slot5_fixed] * eq * risk_b[:slot5_fixed]).sum()
            eq = max(0.0, eq + pnl)
            trace[i, m] = eq
        finals[i] = eq
    return dict(finals=finals, trace=trace)

print(f"\n  {'Config':<48} {'Mediana 12m':>13} {'Mediana 24m':>13}")
print("  " + SEP2)

# 3+2 fisso (irrealistico ad inizio: con €3k non hai €1500 per 1.5%× cap)
mc_3p2 = run_mc_fixed_slots(blocks_1h, blocks_5m, 66, 48)
mc_2p1 = run_mc_fixed_slots(blocks_1h, blocks_5m, 44, 24)
mc_2p2 = run_mc_fixed_slots(blocks_1h, blocks_5m, 44, 48)

print(f"  {'3+2 fisso (irrealistico con €3k)':<48} "
      f"€{np.median(mc_3p2['trace'][:,11]):>11,.0f} €{np.median(mc_3p2['finals']):>11,.0f}")
print(f"  {'2+2 fisso tutto il periodo':<48} "
      f"€{np.median(mc_2p2['trace'][:,11]):>11,.0f} €{np.median(mc_2p2['finals']):>11,.0f}")
print(f"  {'2+1 fisso tutto il periodo':<48} "
      f"€{np.median(mc_2p1['trace'][:,11]):>11,.0f} €{np.median(mc_2p1['finals']):>11,.0f}")
print(f"  {'Slot variabile per capitale (proposto)':<48} "
      f"€{np.median(mc100['trace'][:,11]):>11,.0f} €{np.median(mc100['finals']):>11,.0f}")


# ═══ TABELLA 4 — Milestone ═══════════════════════════════════════════════════
print()
print(SEP)
print("  TABELLA 4 — Quando raggiungo i milestone? (mediana mesi su sim raggiungenti)")
print(SEP)
print(f"\n  {'Milestone':<22} {'Edge 100%':<24} {'Edge 50%':<24} {'Edge 25%':<24} {'Edge 10%':<24}")
print("  " + SEP2)
milestone_levels = [5_000, 10_000, 25_000, 50_000, 100_000]
for ml in milestone_levels:
    cells = []
    for mc in [mc100, mc50, mc25, mc10]:
        arr = mc["milestones"][ml]
        reached = arr[arr > 0]
        if len(reached) > 0:
            med_mesi = int(np.median(reached))
            pct_reach = len(reached) / N_SIM * 100
            cells.append(f"mese {med_mesi:>2}  ({pct_reach:.0f}% sim)".ljust(24))
        else:
            cells.append("non raggiunto".ljust(24))
    label = f"€{ml:>6,.0f} unlock {('2+2' if ml==5000 else '3+2' if ml==10000 else '—')}"
    print(f"  {label:<22} {cells[0]} {cells[1]} {cells[2]} {cells[3]}")


# ═══ Equity mensile per edge degradation ═════════════════════════════════════
print()
print(SEP)
print("  EQUITY MEDIANA per scenario (sample mesi 1, 6, 12, 18, 24)")
print(SEP)
print(f"\n  {'Edge':<6}", end="")
for m in [1, 6, 12, 18, 24]:
    print(f" mese{m:>2}".rjust(13), end="")
print()
print("  " + SEP2)
for label, mc in [("100%", mc100), ("50%", mc50), ("25%", mc25), ("10%", mc10)]:
    print(f"  {label:<6}", end="")
    for m in [1, 6, 12, 18, 24]:
        med = np.median(mc["trace"][:, m-1])
        print(f"€{med:>10,.0f}".rjust(13), end="")
    print()


# ═══ Confronto deterministico vs MC ═══════════════════════════════════════════
print()
print(SEP)
print("  CHECK DETERMINISTICO (risk costante = avg, no varianza)")
print(SEP)
avg_eff_5m = (df5["eff_d"] - SLIP).mean()
avg_risk_5m = df5["risk_h"].mean()
avg_eff_1h = (df1["eff_split"] - SLIP).mean()
n_5m_med = int(np.median([len(b[0]) for b in blocks_5m]))
n_1h_med = int(np.median([len(b) for b in blocks_1h]))

print(f"\n  Deterministico edge 100%, capitale variabile:")
eq_det = CAPITAL_START
for m in range(N_MONTHS):
    eq_det += DEPOSIT_MONTHLY
    s1, s5 = slots_for_capital(eq_det)
    use_n_5m = min(n_5m_med, s5)
    use_n_1h = min(n_1h_med, s1)
    pnl = use_n_1h * avg_eff_1h * eq_det * RISK_1H + use_n_5m * avg_eff_5m * eq_det * avg_risk_5m
    eq_det += pnl
    if (m+1) in [1, 3, 6, 12, 18, 24]:
        s_str = "2+1" if (s1,s5)==(44,24) else ("2+2" if s5==48 and s1==44 else "3+2")
        print(f"    Mese {m+1:>2}: eq=€{eq_det:>9,.0f}  slot {s_str}  trade/m={use_n_1h+use_n_5m}")


print()
print(SEP)
print("  RIEPILOGO")
print(SEP)
print(f"  Pool 5m: {len(df5):,} trade Config D | edge_avg={avg_eff_5m:+.4f}R")
print(f"  Pool 1h: {len(df1):,} trade Config C | edge_avg={avg_eff_1h:+.4f}R")
print(f"  Capitale start: €{CAPITAL_START:,.0f}  +€{DEPOSIT_MONTHLY:.0f}/mese × {N_MONTHS} = "
      f"€{CAPITAL_START + DEPOSIT_MONTHLY*N_MONTHS:,.0f} versato totale")
print(f"  Sim: {N_SIM:,}  |  Mesi: {N_MONTHS}")
print()
print(f"  Mediana 24m, edge 100%:  €{np.median(mc100['finals']):,.0f}")
print(f"  Mediana 24m, edge 50%:   €{np.median(mc50['finals']):,.0f}")
print(f"  Mediana 24m, edge 25%:   €{np.median(mc25['finals']):,.0f}")
print(f"  Mediana 24m, edge 10%:   €{np.median(mc10['finals']):,.0f}")
