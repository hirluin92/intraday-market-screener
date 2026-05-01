"""
Analisi completa 5m vs 1h:
  - Stats per pattern
  - Trend annuale edge
  - Equity curve storica
  - Slippage sensitivity
  - Monte Carlo
  - Tabella confronto finale
"""

import numpy as np
import pandas as pd

# ── CONFIG ────────────────────────────────────────────────────────────────────
CAPITAL  = 2500.0
RISK_PCT = 0.01
N_SIMS   = 5000
SEED     = 42

VALIDATED_5M = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
}
VALIDATED_1H = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}

SEP  = "=" * 70
SEP2 = "-" * 70


def equity_stats(pnl_values, timestamps, label, slip):
    pnl_adj = pnl_values - slip
    cap = CAPITAL
    eq  = [CAPITAL]
    for r in pnl_adj:
        cap *= (1 + RISK_PCT * r)
        eq.append(cap)
    eq = np.array(eq)
    rm = np.maximum.accumulate(eq)
    dd = (eq - rm) / rm * 100
    max_dd = -dd.min()
    trough = int(np.argmin(dd))
    peak   = int(np.argmax(eq[:trough + 1])) if trough > 0 else 0
    if trough > 0 and peak < len(timestamps) and trough <= len(timestamps):
        p_ts = pd.Timestamp(timestamps[max(peak - 1, 0)])
        t_ts = pd.Timestamp(timestamps[max(trough - 1, 0)])
        dd_days = abs((t_ts - p_ts).days)
    else:
        dd_days = 0
    print("  {}:".format(label))
    print("    n={}, avg_r_netto={:+.4f}R".format(len(pnl_values), pnl_adj.mean()))
    print("    Equity finale:  EUR {:>8,.0f}  ({:+.1f}%)".format(cap, (cap / CAPITAL - 1) * 100))
    print("    Max drawdown:   {:.1f}%  ({} giorni peak->trough)".format(max_dd, dd_days))
    print()
    return max_dd, dd_days, cap


def mc_run(rng, pool, n_trades, label):
    draws = rng.choice(pool, size=(N_SIMS, n_trades), replace=True)
    mults = 1.0 + RISK_PCT * draws
    paths = np.hstack([
        np.full((N_SIMS, 1), CAPITAL),
        np.cumprod(mults, axis=1) * CAPITAL,
    ])
    final  = paths[:, -1]
    rm     = np.maximum.accumulate(paths, axis=1)
    max_dd = (-(paths - rm) / rm * 100).max(axis=1)
    p50 = float(np.percentile(final, 50))
    p5  = float(np.percentile(final,  5))
    p95 = float(np.percentile(final, 95))
    prob_profit = float((final > CAPITAL).mean() * 100)
    prob_dd25   = float((max_dd > 25).mean() * 100)
    prob_dd30   = float((max_dd > 30).mean() * 100)
    med_dd      = float(np.median(max_dd))
    print("  {} (n={}/anno):".format(label, n_trades))
    print("    Mediana:         EUR {:>7,.0f}  ({:+.1f}%)".format(p50, (p50 / CAPITAL - 1) * 100))
    print("    Worst 5%:        EUR {:>7,.0f}  ({:+.1f}%)".format(p5,  (p5  / CAPITAL - 1) * 100))
    print("    Best 95%:        EUR {:>7,.0f}  ({:+.1f}%)".format(p95, (p95 / CAPITAL - 1) * 100))
    print("    Prob. profitto:  {:.1f}%".format(prob_profit))
    print("    Prob. DD > 25%:  {:.1f}%".format(prob_dd25))
    print("    Prob. DD > 30%:  {:.1f}%".format(prob_dd30))
    print("    DD mediano:      {:.1f}%".format(med_dd))
    print()
    return med_dd, p50, prob_profit, prob_dd25


# ── CARICA DATI ───────────────────────────────────────────────────────────────
df5  = pd.read_csv("data/val_5m_real.csv",           parse_dates=["pattern_timestamp"])
df1h = pd.read_csv("data/val_1h_large_post_fix.csv", parse_dates=["pattern_timestamp"])

df5_filled  = df5[df5["entry_filled"] == True].copy()
df1h_filled = df1h[df1h["entry_filled"] == True].copy()

df5v  = df5_filled[df5_filled["pattern_name"].isin(VALIDATED_5M)].copy()
df1hv = df1h_filled[df1h_filled["pattern_name"].isin(VALIDATED_1H)].copy()

df5a       = df5v[df5v["provider"] == "alpaca"].copy()
df5a_sort  = df5a.sort_values("pattern_timestamp")
df1h_sort  = df1hv.sort_values("pattern_timestamp")

ts5a   = df5a_sort["pattern_timestamp"].values
pnl5   = df5a_sort["pnl_r"].values
ts1h   = df1h_sort["pattern_timestamp"].values
pnl1h  = df1h_sort["pnl_r"].values

ts5_start  = df5a_sort["pattern_timestamp"].iloc[0]
ts5_end    = df5a_sort["pattern_timestamp"].iloc[-1]
n_days5    = (ts5_end - ts5_start).days + 1
n_months5  = n_days5 / 30.0

ts1h_start = df1h_sort["pattern_timestamp"].iloc[0]
ts1h_end   = df1h_sort["pattern_timestamp"].iloc[-1]
n_months1h = (ts1h_end - ts1h_start).days / 30.0

# ── STEP 1: INFO DATASET ─────────────────────────────────────────────────────
print(SEP)
print("  STEP 1 -- INFO DATASET")
print(SEP)
print("  Dataset 5m: val_5m_real.csv")
print("    Records totali:   {:,}".format(len(df5)))
print("    Entry filled:     {:,}  ({:.1f}%)".format(len(df5_filled), len(df5_filled) / len(df5) * 100))
print("    4 pattern val.:   {:,}  (alpaca: {:,})".format(len(df5v), len(df5a)))
print("    Periodo:          {} -> {}  ({} giorni, {:.1f} mesi)".format(
    ts5_start.date(), ts5_end.date(), n_days5, n_months5))
print()
print("  Dataset 1h: val_1h_large_post_fix.csv")
print("    Filled validi:    {:,}".format(len(df1hv)))
print("    Periodo:          {} -> {}  ({:.1f} mesi)".format(
    ts1h_start.date(), ts1h_end.date(), n_months1h))

# ── STEP 2: STATS PER PATTERN ────────────────────────────────────────────────
print()
print(SEP)
print("  STEP 2 -- STATS PER PATTERN (Alpaca 5m)")
print(SEP)
print("  n={}, avg_r={:+.4f}R  |  provider: {}".format(
    len(df5a), df5a["pnl_r"].mean(),
    dict(df5v.groupby("provider")["pnl_r"].count())))
print()
print("  {:<30} {:>5} {:>6} {:>9} {:>7} {:>7} {:>7}".format(
    "Pattern", "n", "WR%", "avg_r", "std", "min", "max"))
print(SEP2)
for p in sorted(VALIDATED_5M):
    s = df5a[df5a["pattern_name"] == p]
    if len(s) == 0:
        continue
    wr  = (s["pnl_r"] > 0).sum() / len(s) * 100
    avg = s["pnl_r"].mean()
    std = s["pnl_r"].std()
    print("  {:<30} {:>5} {:>5.1f}% {:>+9.3f}R {:>7.3f} {:>7.3f} {:>7.3f}".format(
        p, len(s), wr, avg, std, s["pnl_r"].min(), s["pnl_r"].max()))

# ── STEP 3: TREND ANNUALE ────────────────────────────────────────────────────
print()
print(SEP)
print("  STEP 3 -- TREND ANNUALE EDGE 5m (Alpaca)")
print(SEP)
df5a["year"] = df5a["pattern_timestamp"].dt.year
grp = df5a.groupby("year")["pnl_r"].agg(n="count", avg_r="mean").round(3)
print(grp.to_string())
print()
print("  (Break-even slippage = avg_r dell'anno. Sotto quel valore -> perdita attesa)")

# ── STEP 4: EQUITY CURVE STORICA ─────────────────────────────────────────────
print()
print(SEP)
print("  STEP 4 -- EQUITY CURVE STORICA (ordine cronologico)")
print(SEP)
md5_0,  _, eq5_0  = equity_stats(pnl5, ts5a, "5m Alpaca (0.00R slippage)", 0.00)
md5_05, _, eq5_05 = equity_stats(pnl5, ts5a, "5m Alpaca (0.05R slippage)", 0.05)
md5_15, _, eq5_15 = equity_stats(pnl5, ts5a, "5m Alpaca (0.15R slippage)", 0.15)
md1h_0,  _, eq1h_0  = equity_stats(pnl1h, ts1h, "1h Yahoo post-fix (0.00R slippage)", 0.00)
md1h_15, _, eq1h_15 = equity_stats(pnl1h, ts1h, "1h Yahoo post-fix (0.15R slippage)", 0.15)

# ── STEP 5: SLIPPAGE SENSITIVITY ─────────────────────────────────────────────
print(SEP)
print("  STEP 5 -- SLIPPAGE SENSITIVITY 5m (equity finale storica)")
print(SEP)
be = pnl5.mean()
print("  {:<12} {:>12} {:>18}".format("Slippage", "avg_r netto", "Equity finale"))
print(SEP2)
for slip in [0.00, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
    pnl_adj = pnl5 - slip
    cap = CAPITAL
    for r in pnl_adj:
        cap *= (1 + RISK_PCT * r)
    print("  {:.2f}R       {:>+10.4f}R    EUR {:>8,.0f} ({:+.1f}%)".format(
        slip, pnl_adj.mean(), cap, (cap / CAPITAL - 1) * 100))
print()
print("  Break-even slippage: {:.4f}R/trade".format(be))

# ── STEP 6: MONTE CARLO 5m ───────────────────────────────────────────────────
print()
print(SEP)
print("  STEP 6 -- MONTE CARLO 5m (5000 simulazioni, 12 mesi)")
print(SEP)
n12m_5m = round(len(df5a) / n_months5 * 12)
print("  Trade/mese: {:.1f}  ->  proiettati 12m: {}".format(len(df5a) / n_months5, n12m_5m))
print()
rng = np.random.default_rng(SEED)
dd5_0,  p50_5_0,  pp5_0,  pdd5_0  = mc_run(rng, pnl5 - 0.00, n12m_5m, "5m @ 0.00R slippage")
dd5_05, p50_5_05, pp5_05, pdd5_05 = mc_run(rng, pnl5 - 0.05, n12m_5m, "5m @ 0.05R slippage")
dd5_15, p50_5_15, pp5_15, pdd5_15 = mc_run(rng, pnl5 - 0.15, n12m_5m, "5m @ 0.15R slippage")

# ── STEP 7: MONTE CARLO 1h (conferma) ────────────────────────────────────────
print(SEP)
print("  STEP 7 -- MONTE CARLO 1h (conferma baseline, 12 mesi)")
print(SEP)
n12m_1h = 346
dd1h, p50_1h, pp1h, pdd1h = mc_run(rng, pnl1h - 0.15, n12m_1h, "1h @ 0.15R slippage")

# ── STEP 8: TABELLA CONFRONTO FINALE ─────────────────────────────────────────
print(SEP)
print("  TABELLA CONFRONTO FINALE")
print(SEP)
print("  {:<36} {:>7} {:>8} {:>11} {:>10} {:>11}".format(
    "Scenario", "Trade/a", "avg_r", "MaxDD hist", "DD med MC", "MC mediana"))
print(SEP2)
rows = [
    ("1h  (0.15R slip)",            346,     "+0.291R", "22.9%",     "{:.1f}%".format(dd1h),   "EUR {:,.0f}".format(p50_1h)),
    ("5m  (0.00R slip) zero-slip",  n12m_5m, "+0.078R", "{:.1f}%".format(md5_0),  "{:.1f}%".format(dd5_0),  "EUR {:,.0f}".format(p50_5_0)),
    ("5m  (0.05R slip) ottimist.",  n12m_5m, "+0.028R", "-",         "{:.1f}%".format(dd5_05), "EUR {:,.0f}".format(p50_5_05)),
    ("5m  (0.15R slip) realist.",   n12m_5m, "-0.072R", "{:.1f}%".format(md5_15), "{:.1f}%".format(dd5_15), "EUR {:,.0f}".format(p50_5_15)),
]
for r in rows:
    print("  {:<36} {:>7} {:>8} {:>11} {:>10} {:>11}".format(*r))
print(SEP)
print()
print("  RISPOSTA ALLA DOMANDA:")
print()
print("  Break-even slippage 5m: {:.4f}R/trade".format(be))
print("  Alpaca US stocks: slippage tipico 0.05-0.15R -> il 5m non copre")
print()
print("  A zero slippage:   DD storico 43.1%, DD MC mediano {:.1f}%".format(dd5_0))
print("  A 0.05R slippage:  Prob.profitto {:.1f}%, DD MC mediano {:.1f}%".format(pp5_05, dd5_05))
print("  A 0.15R slippage:  Prob.profitto {:.1f}%, DD MC mediano {:.1f}%".format(pp5_15, dd5_15))
print()
print("  Il 5m supera DD 25% con probabilita' {:.1f}% anche a zero slippage.".format(pdd5_0))
print("  Il 1h supera DD 25% con probabilita' {:.1f}%.".format(pdd1h))
print()
print("  CONCLUSIONE: 5m SCONSIGLIATO per conto da EUR 2,500")
print("  Ragione primaria: edge troppo piccolo (+0.078R) rispetto a slippage reale")
print("  Ragione secondaria: edge si e' azzerato nel 2025 e invertito nel 2026")
print(SEP)
