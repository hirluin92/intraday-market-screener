"""
Monte Carlo v6 — corretto post-audit.

Fix vs v5:
  - Slot cap REALE da hold misurato:
      1h: 66/mese (hold 0.96 giorni, non 3)
      5m: 48/mese (cicli 2.30/h, non 2.0)
  - Bootstrap MENSILE: campiona blocchi mensili interi per preservare la
    varianza reale (1h std=62.7 trade/mese!). Niente più assunzione "n_month
    costante".
  - Edge 5m haircut: usa pool OOS 2026 (eff_r post-slip ≈ +0.154R) come
    proxy realistico, non l'IS (~+0.232R).
  - Compound mensile (immutato vs v5).
  - Edge degradation 1h: scenari 100/75/50/25/10% applicati al pool 1h.

Uso:
  python monte_carlo_v6.py --csv1h <path> --csv5m <path>
  Default cerca research/datasets/{val_1h_production_2026.csv | val_5m_v2.csv}
"""
from __future__ import annotations
import argparse
import os
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ─── Config ────────────────────────────────────────────────────────────────────
RNG_SEED   = 42
N_SIM      = 5_000
CAPITAL    = 100_000.0
RISK_1H    = 0.015
RISK_5M    = 0.005
SLIP       = 0.15
MIN_STR    = 0.60

# Slot cap REALI da audit (Step 5)
SLOT_CAP_1H = 66    # 3 slot × 21gg / 0.96gg hold
SLOT_CAP_5M = 48    # 2 slot × 2.30 cicli/h × 21gg × 50% fill

# OOS 2026 cutoff per haircut 5m
OOS_5M_FROM = pd.Timestamp("2026-01-01", tz="UTC")
OOS_1H_FROM = pd.Timestamp("2025-11-01", tz="UTC")

PATTERNS = {
    "double_bottom","double_top",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
}
HOURS_5M = {11, 12, 13, 14, 15}

SEP  = "=" * 78
SEP2 = "-" * 78


# ─── Formula eff_r (immutata) ─────────────────────────────────────────────────
def cr1(e, s, t):
    d = abs(float(e)-float(s))
    return 0.0 if d < 1e-10 else abs(float(t)-float(e)) / d

def cr2(e, s, t):
    d = abs(float(e)-float(s))
    return 0.0 if d < 1e-10 else abs(float(t)-float(e)) / d

def eff_r(row) -> float:
    o = str(row["outcome"]); pr = float(row["pnl_r"])
    r1 = cr1(row["entry_price"], row["stop_price"], row["tp1_price"])
    r2 = cr2(row["entry_price"], row["stop_price"], row["tp2_price"])
    if o == "tp2": return 0.5*r1 + 0.5*r2
    if o == "tp1":
        runner = 0.5 if r1 >= 1.0 else (0.0 if r1 >= 0.5 else -1.0)
        return 0.5*r1 + 0.5*runner
    if o in ("stop","stopped","sl"): return -1.0
    return pr


# ─── Bootstrap mensile ────────────────────────────────────────────────────────
def build_monthly_blocks(df, slip=SLIP, slot_cap=None):
    """
    Ritorna lista di array eff_r-slip per ogni mese. Ogni mese mantiene la sua
    distribuzione interna (n trade + sequenza outcome).
    Se slot_cap è impostato, applica head(slot_cap) per mese.
    """
    df = df.sort_values("pattern_timestamp").copy()
    df["ym"] = df["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for ym, sub in df.groupby("ym", sort=True):
        sub = sub.head(slot_cap) if slot_cap else sub
        if len(sub) > 0:
            blocks.append((sub["eff_r"] - slip).values)
    return blocks


def run_mc_v6_blocks(blocks_a, blocks_b,
                     risk_a_pct, risk_b_pct,
                     cap=CAPITAL, nsim=N_SIM, seed=RNG_SEED,
                     edge_a=1.0, edge_b=1.0,
                     n_months=12):
    """
    Bootstrap mensile: ad ogni mese, campiona UN blocco mensile da blocks_a e
    UN blocco mensile da blocks_b (con replacement). Applica edge multipliers.
    Compound mensile: risk fissato all'inizio del mese sull'equity.
    """
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim)
    dds    = np.empty(nsim)

    have_a = len(blocks_a) > 0 and risk_a_pct > 0
    have_b = len(blocks_b) > 0 and risk_b_pct > 0
    idx_a = np.arange(len(blocks_a)) if have_a else None
    idx_b = np.arange(len(blocks_b)) if have_b else None

    for i in range(nsim):
        eq = cap; pk = cap; md = 0.0
        for _ in range(n_months):
            risk_a = eq * risk_a_pct
            risk_b = eq * risk_b_pct
            pnl = 0.0
            if have_a:
                blk = blocks_a[rng.choice(idx_a)]
                pnl += (blk * edge_a * risk_a).sum()
            if have_b:
                blk = blocks_b[rng.choice(idx_b)]
                pnl += (blk * edge_b * risk_b).sum()
            eq = max(0.0, eq + pnl)
            if eq > pk: pk = eq
            if pk > 0:
                dd = (pk - eq) / pk
                if dd > md: md = dd
        finals[i] = eq
        dds[i]    = md

    return dict(
        med=np.median(finals), mean=finals.mean(),
        p05=np.percentile(finals, 5),
        p25=np.percentile(finals, 25),
        p75=np.percentile(finals, 75),
        p95=np.percentile(finals, 95),
        prob=(finals > cap).mean(),
        dd_med=np.median(dds), dd_p95=np.percentile(dds, 95),
    )


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    base = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets"
    ap.add_argument("--csv1h", default=os.path.join(base, "val_1h_production_2026.csv"))
    ap.add_argument("--csv5m", default=os.path.join(base, "val_5m_v2.csv"))
    args = ap.parse_args()

    if not os.path.exists(args.csv1h):
        # fallback al dataset vecchio se quello nuovo non esiste ancora
        fb = os.path.join(base, "val_1h_production.csv")
        print(f"  WARN: {args.csv1h} non trovato, uso fallback {fb}")
        args.csv1h = fb

    print(SEP)
    print("  MONTE CARLO v6 — BOOTSTRAP MENSILE + SLOT CAP REALI + HAIRCUT 5m")
    print(SEP)
    print(f"  csv1h: {args.csv1h}")
    print(f"  csv5m: {args.csv5m}")

    # 1h
    df1 = pd.read_csv(args.csv1h)
    df1["pattern_timestamp"] = pd.to_datetime(df1["pattern_timestamp"], utc=True)
    df1 = df1[
        df1["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
        df1["pattern_name"].isin(PATTERNS) &
        ~df1["provider"].isin(["ibkr"]) &
        (df1["pattern_strength"].fillna(0) >= MIN_STR)
    ].copy()
    df1["eff_r"] = df1.apply(eff_r, axis=1)

    # 5m
    df5 = pd.read_csv(args.csv5m)
    df5["pattern_timestamp"] = pd.to_datetime(df5["pattern_timestamp"], utc=True)
    df5["hour_et"] = df5["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
    df5 = df5[
        df5["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
        df5["pattern_name"].isin(PATTERNS) &
        df5["provider"].isin(["alpaca"]) &
        df5["hour_et"].isin(HOURS_5M) &
        (df5["pattern_strength"].fillna(0) >= MIN_STR)
    ].copy()
    df5["eff_r"] = df5.apply(eff_r, axis=1)

    # Range temporali
    print()
    print(f"  1h: {len(df1):,} trade | {df1['pattern_timestamp'].min().date()} → {df1['pattern_timestamp'].max().date()}")
    print(f"  5m: {len(df5):,} trade | {df5['pattern_timestamp'].min().date()} → {df5['pattern_timestamp'].max().date()}")

    # Split IS / OOS
    df1_is  = df1[df1["pattern_timestamp"] <  OOS_1H_FROM].copy()
    df1_oos = df1[df1["pattern_timestamp"] >= OOS_1H_FROM].copy()
    df5_is  = df5[df5["pattern_timestamp"] <  OOS_5M_FROM].copy()
    df5_oos = df5[df5["pattern_timestamp"] >= OOS_5M_FROM].copy()

    def stat(df, lab):
        if len(df) == 0:
            return f"  {lab:<22} n=0"
        pool = (df["eff_r"] - SLIP).values
        wr = (pool>0).mean()*100
        ar = df["pnl_r"].mean()
        ers = pool.mean()
        return f"  {lab:<22} n={len(df):>5} | avg_r={ar:+.4f} | eff_r-slip={ers:+.4f} | WR={wr:.1f}%"

    print()
    print(SEP)
    print("  EDGE PER PERIODO")
    print(SEP)
    print(stat(df1_is,  "1h IS (<2025-11-01)"))
    print(stat(df1_oos, "1h OOS (>=2025-11)"))
    print(stat(df5_is,  "5m IS (<2026-01-01)"))
    print(stat(df5_oos, "5m OOS (>=2026-01)"))

    # Edge ratio (haircut implicito)
    if len(df1_oos) > 0 and len(df1_is) > 0:
        e1_is  = (df1_is["eff_r"]-SLIP).mean()
        e1_oos = (df1_oos["eff_r"]-SLIP).mean()
        edge_ratio_1h = e1_oos / e1_is if e1_is != 0 else 0
        print(f"\n  1h edge OOS/IS ratio: {edge_ratio_1h*100:.1f}%  (haircut da applicare)")
    else:
        edge_ratio_1h = None

    e5_is  = (df5_is["eff_r"]-SLIP).mean()
    e5_oos = (df5_oos["eff_r"]-SLIP).mean()
    edge_ratio_5m = e5_oos / e5_is if e5_is != 0 else 0
    print(f"  5m edge OOS/IS ratio: {edge_ratio_5m*100:.1f}%  (haircut da applicare)")

    # ─── Build monthly blocks ─────────────────────────────────────────────────
    blocks_1h_full  = build_monthly_blocks(df1, slot_cap=SLOT_CAP_1H)
    blocks_5m_full  = build_monthly_blocks(df5, slot_cap=SLOT_CAP_5M)
    blocks_1h_is    = build_monthly_blocks(df1_is, slot_cap=SLOT_CAP_1H)
    blocks_5m_is    = build_monthly_blocks(df5_is, slot_cap=SLOT_CAP_5M)
    blocks_1h_oos   = build_monthly_blocks(df1_oos, slot_cap=SLOT_CAP_1H)
    blocks_5m_oos   = build_monthly_blocks(df5_oos, slot_cap=SLOT_CAP_5M)

    print()
    print(SEP)
    print("  BLOCCHI MENSILI DISPONIBILI (post slot cap)")
    print(SEP)
    def desc_blocks(b, lab):
        if not b:
            print(f"  {lab:<26} 0 blocchi")
            return
        ns = [len(x) for x in b]
        ms = [x.mean() for x in b]
        print(f"  {lab:<26} {len(b):>2} blocchi | trade/mese: med={np.median(ns):.0f} "
              f"min={min(ns)} max={max(ns)} | avg_r-slip per mese: med={np.median(ms):+.3f}")
    desc_blocks(blocks_1h_full, "1h tutto (cap 66)")
    desc_blocks(blocks_1h_is,   "1h IS")
    desc_blocks(blocks_1h_oos,  "1h OOS")
    desc_blocks(blocks_5m_full, "5m tutto (cap 48)")
    desc_blocks(blocks_5m_is,   "5m IS")
    desc_blocks(blocks_5m_oos,  "5m OOS")

    # ─── MC v6 Scenari ────────────────────────────────────────────────────────
    print()
    print(SEP)
    print("  MC v6 — €100k, 12 mesi, 5,000 sim, BOOTSTRAP MENSILE")
    print(SEP)

    scenarios = []

    # Scenario 1: tutto IS (worst-case ottimistico = uses solo IS pool, edge 100%)
    scenarios.append(("IS-only (pool 1h+5m IS)",
                      blocks_1h_is,  blocks_5m_is,  1.0, 1.0))

    # Scenario 2: tutto pool aggregato (default)
    scenarios.append(("Aggregato (full pool)",
                      blocks_1h_full, blocks_5m_full, 1.0, 1.0))

    # Scenario 3: 1h IS + 5m OOS (test realistico — 5m mostra degradation)
    scenarios.append(("1h IS + 5m OOS",
                      blocks_1h_is, blocks_5m_oos, 1.0, 1.0))

    # Scenario 4: tutto OOS (se disponibile)
    if blocks_1h_oos and blocks_5m_oos:
        scenarios.append(("OOS-only (fwd test)",
                          blocks_1h_oos, blocks_5m_oos, 1.0, 1.0))

    # Scenario 5: IS pool + edge haircut realistico (1h 50%, 5m al ratio OOS)
    edge_5m_h = max(0.5, edge_ratio_5m)  # haircut 5m da OOS
    edge_1h_h = edge_ratio_1h if edge_ratio_1h else 0.75
    scenarios.append((f"IS + haircut (1h@{edge_1h_h*100:.0f}%, 5m@{edge_5m_h*100:.0f}%)",
                      blocks_1h_is, blocks_5m_is, edge_1h_h, edge_5m_h))

    print(f"  {'Scenario':<40} {'Mediana':>11} {'Worst5%':>11} {'Best95%':>11} "
          f"{'ProbP':>6} {'DDp95':>6} {'Rend%':>8}")
    print("  " + SEP2)
    for lb, b1, b5, e1, e5 in scenarios:
        if not (b1 or b5):
            print(f"  {lb:<40}  (insufficienti blocchi)")
            continue
        mc = run_mc_v6_blocks(b1, b5, RISK_1H, RISK_5M,
                              edge_a=e1, edge_b=e5, nsim=N_SIM, seed=RNG_SEED)
        rend = (mc['med']/CAPITAL-1)*100
        print(f"  {lb:<40} {mc['med']:>11,.0f} {mc['p05']:>11,.0f} {mc['p95']:>11,.0f} "
              f"{mc['prob']*100:>5.1f}%  {mc['dd_p95']*100:>5.1f}% {rend:>+7.1f}%")

    # ─── Edge degradation ─────────────────────────────────────────────────────
    print()
    print(SEP)
    print("  EDGE DEGRADATION — pool aggregato, scenari 1h scalati")
    print(SEP)
    print(f"  {'Edge 1h':>8} {'Edge 5m':>8} {'Mediana':>11} {'Worst5%':>11} {'p25':>11} {'p75':>11} "
          f"{'ProbP':>6} {'DDp95':>6}  Note")
    print("  " + SEP2)
    deg_scenarios = [
        (1.00, 1.00, ""),
        (0.75, 0.75, ""),
        (0.50, 0.66, "5m a OOS ratio"),
        (0.50, 0.50, ""),
        (0.25, 0.50, "1h forte degrad."),
        (0.25, 0.25, "scenario stress"),
        (0.10, 0.25, ""),
    ]
    for e1, e5, note in deg_scenarios:
        mc = run_mc_v6_blocks(blocks_1h_full, blocks_5m_full,
                              RISK_1H, RISK_5M,
                              edge_a=e1, edge_b=e5,
                              nsim=2000, seed=99)
        print(f"  {e1*100:>6.0f}% {e5*100:>7.0f}% {mc['med']:>11,.0f} {mc['p05']:>11,.0f} "
              f"{mc['p25']:>11,.0f} {mc['p75']:>11,.0f} "
              f"{mc['prob']*100:>5.1f}%  {mc['dd_p95']*100:>5.1f}%  {note}")

    # ─── Confronto v5 vs v6 ───────────────────────────────────────────────────
    print()
    print(SEP)
    print("  CONFRONTO v5 vs v6 (€100k, 12 mesi, edge 100%)")
    print(SEP)
    # Replico v5: pool aggregato, n_month costante = 21+84
    pool1 = (df1["eff_r"] - SLIP).values
    pool5 = (df5["eff_r"] - SLIP).values
    rng = np.random.default_rng(42)
    finals_v5 = np.empty(N_SIM)
    for i in range(N_SIM):
        eq = CAPITAL
        for _ in range(12):
            r1 = eq*RISK_1H; r5 = eq*RISK_5M
            p = (rng.choice(pool1, 21, replace=True)*r1).sum() + \
                (rng.choice(pool5, 84, replace=True)*r5).sum()
            eq = max(0, eq+p)
        finals_v5[i] = eq

    mc_v6 = run_mc_v6_blocks(blocks_1h_full, blocks_5m_full,
                             RISK_1H, RISK_5M, nsim=N_SIM, seed=42)

    print(f"  {'Versione':<35} {'Mediana':>12} {'Worst5%':>12} {'Best95%':>12} {'ProbP':>6}")
    print("  " + SEP2)
    print(f"  {'v5 (n=21+84, pool aggreg.)':<35} "
          f"{np.median(finals_v5):>12,.0f} "
          f"{np.percentile(finals_v5,5):>12,.0f} "
          f"{np.percentile(finals_v5,95):>12,.0f} "
          f"{(finals_v5>CAPITAL).mean()*100:>5.1f}%")
    print(f"  {'v6 (cap 66+48, bootstrap mens.)':<35} "
          f"{mc_v6['med']:>12,.0f} {mc_v6['p05']:>12,.0f} {mc_v6['p95']:>12,.0f} "
          f"{mc_v6['prob']*100:>5.1f}%")

    print()
    print(SEP)
    print("  RIEPILOGO")
    print(SEP)
    print(f"  Slot cap usati: 1h={SLOT_CAP_1H}/mese | 5m={SLOT_CAP_5M}/mese")
    print(f"  Bootstrap: campiona blocchi mensili interi (preserva varianza+correlazioni)")
    print(f"  Slip: {SLIP}R round-trip applicato a ogni eff_r")
    print(f"  Pool 1h: {len(df1):,} trade | Pool 5m: {len(df5):,} trade")
    print(f"  Blocchi mensili 1h: {len(blocks_1h_full)} | 5m: {len(blocks_5m_full)}")
    print(SEP)


if __name__ == "__main__":
    main()
