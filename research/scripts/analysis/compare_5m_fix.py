"""
Confronto PRIMA/DOPO fix 5m:
  val_5m_real.csv  = dataset senza fix
  val_5m_fixed.csv = dataset con Fix 1 (entry <=3 bar) + Fix 2 (no open ET)
"""

import numpy as np
import pandas as pd

CAPITAL  = 2500.0
RISK_PCT = 0.01
N_SIMS   = 5000
SEED     = 42

VALIDATED_5M = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
}

SEP  = "=" * 72
SEP2 = "-" * 72


def load_alpaca(path):
    df = pd.read_csv(path, parse_dates=["pattern_timestamp"])
    df = df[df["entry_filled"] == True].copy()
    df = df[df["pattern_name"].isin(VALIDATED_5M)].copy()
    df = df[df["provider"] == "alpaca"].copy()
    return df


def equity_stats(pnl_values, label, slip):
    pnl_adj = pnl_values - slip
    cap = CAPITAL
    eq  = [CAPITAL]
    for r in pnl_adj:
        cap *= (1 + RISK_PCT * r)
        eq.append(cap)
    eq  = np.array(eq)
    rm  = np.maximum.accumulate(eq)
    dd  = (eq - rm) / rm * 100
    return {
        "label":   label,
        "n":       len(pnl_values),
        "avg_r":   pnl_adj.mean(),
        "equity":  cap,
        "gain":    (cap / CAPITAL - 1) * 100,
        "max_dd":  -dd.min(),
    }


def mc_stats(rng, pool, n_trades):
    draws  = rng.choice(pool, size=(N_SIMS, n_trades), replace=True)
    mults  = 1.0 + RISK_PCT * draws
    paths  = np.hstack([np.full((N_SIMS, 1), CAPITAL),
                        np.cumprod(mults, axis=1) * CAPITAL])
    final  = paths[:, -1]
    rm     = np.maximum.accumulate(paths, axis=1)
    max_dd = (-(paths - rm) / rm * 100).max(axis=1)
    return {
        "p50":         float(np.percentile(final, 50)),
        "p5":          float(np.percentile(final, 5)),
        "prob_profit": float((final > CAPITAL).mean() * 100),
        "dd_med":      float(np.median(max_dd)),
        "dd_25":       float((max_dd > 25).mean() * 100),
        "dd_30":       float((max_dd > 30).mean() * 100),
    }


# ── CARICA ───────────────────────────────────────────────────────────────────
df_pre  = load_alpaca("data/val_5m_real.csv")
df_post = load_alpaca("data/val_5m_fixed.csv")

# ── STEP 1: STATS PER PATTERN ────────────────────────────────────────────────
print()
print(SEP)
print("  STEP 1 -- STATS PER PATTERN (Alpaca 5m, 4 pattern validati)")
print(SEP)

for df, label in [(df_pre, "PRIMA fix"), (df_post, "DOPO fix")]:
    ts = df["pattern_timestamp"].sort_values()
    n_months = (ts.iloc[-1] - ts.iloc[0]).days / 30.0
    tpm = len(df) / n_months if n_months > 0 else 0
    print()
    print("  {}  n={:,}  avg_r={:+.4f}R  {:.0f} trade/mese".format(
        label, len(df), df["pnl_r"].mean(), tpm))
    print("  {:<30} {:>5} {:>6} {:>9} {:>7}".format("Pattern", "n", "WR%", "avg_r", "std"))
    print("  " + "-" * 58)
    for p in sorted(VALIDATED_5M):
        s = df[df["pattern_name"] == p]
        if len(s) == 0:
            continue
        wr  = (s["pnl_r"] > 0).sum() / len(s) * 100
        avg = s["pnl_r"].mean()
        std = s["pnl_r"].std()
        print("  {:<30} {:>5} {:>5.1f}% {:>+9.3f}R {:>7.3f}".format(
            p, len(s), wr, avg, std))

# ── STEP 2: TREND ANNUALE ────────────────────────────────────────────────────
print()
print(SEP)
print("  STEP 2 -- TREND ANNUALE EDGE 5m (Alpaca)")
print(SEP)

for df, label in [(df_pre, "PRIMA fix"), (df_post, "DOPO fix")]:
    df2 = df.copy()
    df2["year"] = df2["pattern_timestamp"].dt.year
    grp = df2.groupby("year")["pnl_r"].agg(n="count", avg_r="mean").round(3)
    print()
    print("  {}:".format(label))
    print(grp.to_string())

# ── STEP 3: EQUITY CURVE STORICA ─────────────────────────────────────────────
print()
print(SEP)
print("  STEP 3 -- EQUITY CURVE STORICA (ordinata per timestamp)")
print(SEP)

print()
print("  {:<35} {:>6} {:>9} {:>12} {:>9}".format(
    "Scenario", "n", "avg_r", "Equity", "MaxDD"))
print(SEP2)

for df, lbl in [(df_pre.sort_values("pattern_timestamp"), "PRIMA"),
                (df_post.sort_values("pattern_timestamp"), "DOPO")]:
    for slip in [0.00, 0.05, 0.10, 0.15]:
        st = equity_stats(df["pnl_r"].values, "{} slip={:.2f}R".format(lbl, slip), slip)
        print("  {:<35} {:>6} {:>+9.4f}R {:>10,.0f} EUR {:>8.1f}%".format(
            st["label"], st["n"], st["avg_r"], st["equity"], st["max_dd"]))
    print()

# ── STEP 4: MONTE CARLO ──────────────────────────────────────────────────────
print(SEP)
print("  STEP 4 -- MONTE CARLO 12 mesi (5000 sim, EUR 2,500, 1% risk)")
print(SEP)

rng = np.random.default_rng(SEED)

for df, label in [(df_pre, "PRIMA fix"), (df_post, "DOPO fix")]:
    ts  = df["pattern_timestamp"].sort_values()
    nm  = (ts.iloc[-1] - ts.iloc[0]).days / 30.0
    n12 = round(len(df) / nm * 12) if nm > 0 else 0
    print()
    print("  {}  ({} trade/anno proiettati):".format(label, n12))
    print("  {:<12} {:>10} {:>10} {:>14} {:>10} {:>10}".format(
        "Slippage", "Mediana", "Worst 5%", "Prob. profitto", "DD med", "DD>25%"))
    print("  " + "-" * 68)
    for slip in [0.05, 0.15]:
        pool = df["pnl_r"].values - slip
        mc   = mc_stats(rng, pool, n12)
        print("  {:<12} {:>10,.0f} {:>10,.0f} {:>13.1f}% {:>9.1f}% {:>9.1f}%".format(
            "{:.2f}R".format(slip),
            mc["p50"], mc["p5"],
            mc["prob_profit"],
            mc["dd_med"],
            mc["dd_25"],
        ))

# ── STEP 5: TABELLA CONFRONTO FINALE ─────────────────────────────────────────
print()
print(SEP)
print("  CONFRONTO PRIMA/DOPO FIX")
print(SEP)

ts_pre  = df_pre["pattern_timestamp"].sort_values()
ts_post = df_post["pattern_timestamp"].sort_values()
nm_pre  = (ts_pre.iloc[-1]  - ts_pre.iloc[0]).days  / 30.0
nm_post = (ts_post.iloc[-1] - ts_post.iloc[0]).days / 30.0
n12_pre  = round(len(df_pre)  / nm_pre  * 12) if nm_pre  > 0 else 0
n12_post = round(len(df_post) / nm_post * 12) if nm_post > 0 else 0

rng2 = np.random.default_rng(SEED + 100)

mc_pre_05  = mc_stats(rng2, df_pre["pnl_r"].values  - 0.05, n12_pre)
mc_pre_15  = mc_stats(rng2, df_pre["pnl_r"].values  - 0.15, n12_pre)
mc_post_05 = mc_stats(rng2, df_post["pnl_r"].values - 0.05, n12_post)
mc_post_15 = mc_stats(rng2, df_post["pnl_r"].values - 0.15, n12_post)

# Equity storica
eq_pre_0  = equity_stats(df_pre["pnl_r"].values,  "pre 0.00", 0.00)
eq_post_0 = equity_stats(df_post["pnl_r"].values, "pst 0.00", 0.00)
eq_pre_15  = equity_stats(df_pre["pnl_r"].values,  "pre 0.15", 0.15)
eq_post_15 = equity_stats(df_post["pnl_r"].values, "pst 0.15", 0.15)

print()
print("  {:<30} {:>14} {:>14}".format("Metrica", "PRIMA fix", "DOPO fix"))
print(SEP2)

rows = [
    ("n trade",                           "{:,}".format(len(df_pre)),   "{:,}".format(len(df_post))),
    ("Trade/anno proiettati",             str(n12_pre),                  str(n12_post)),
    ("avg_r pre-slippage",                "{:+.4f}R".format(df_pre["pnl_r"].mean()),
                                          "{:+.4f}R".format(df_post["pnl_r"].mean())),
    ("Break-even slippage",               "{:.4f}R".format(df_pre["pnl_r"].mean()),
                                          "{:.4f}R".format(df_post["pnl_r"].mean())),
    ("Equity storica @0.00R slip",        "EUR {:,.0f} ({:+.1f}%)".format(eq_pre_0["equity"],  eq_pre_0["gain"]),
                                          "EUR {:,.0f} ({:+.1f}%)".format(eq_post_0["equity"], eq_post_0["gain"])),
    ("Max DD storico @0.00R slip",        "{:.1f}%".format(eq_pre_0["max_dd"]),
                                          "{:.1f}%".format(eq_post_0["max_dd"])),
    ("Equity storica @0.15R slip",        "EUR {:,.0f} ({:+.1f}%)".format(eq_pre_15["equity"],  eq_pre_15["gain"]),
                                          "EUR {:,.0f} ({:+.1f}%)".format(eq_post_15["equity"], eq_post_15["gain"])),
    ("Max DD storico @0.15R slip",        "{:.1f}%".format(eq_pre_15["max_dd"]),
                                          "{:.1f}%".format(eq_post_15["max_dd"])),
    ("--- MC @0.05R slip ---",            "", ""),
    ("  MC mediana 12m",                  "EUR {:,.0f}".format(mc_pre_05["p50"]),
                                          "EUR {:,.0f}".format(mc_post_05["p50"])),
    ("  MC prob. profitto",               "{:.1f}%".format(mc_pre_05["prob_profit"]),
                                          "{:.1f}%".format(mc_post_05["prob_profit"])),
    ("  MC DD mediano",                   "{:.1f}%".format(mc_pre_05["dd_med"]),
                                          "{:.1f}%".format(mc_post_05["dd_med"])),
    ("  MC DD > 25%",                     "{:.1f}%".format(mc_pre_05["dd_25"]),
                                          "{:.1f}%".format(mc_post_05["dd_25"])),
    ("--- MC @0.15R slip ---",            "", ""),
    ("  MC mediana 12m",                  "EUR {:,.0f}".format(mc_pre_15["p50"]),
                                          "EUR {:,.0f}".format(mc_post_15["p50"])),
    ("  MC prob. profitto",               "{:.1f}%".format(mc_pre_15["prob_profit"]),
                                          "{:.1f}%".format(mc_post_15["prob_profit"])),
    ("  MC DD mediano",                   "{:.1f}%".format(mc_pre_15["dd_med"]),
                                          "{:.1f}%".format(mc_post_15["dd_med"])),
    ("  MC DD > 25%",                     "{:.1f}%".format(mc_pre_15["dd_25"]),
                                          "{:.1f}%".format(mc_post_15["dd_25"])),
]

for r in rows:
    if r[1] == "" and r[2] == "":
        print("  {}".format(r[0]))
    else:
        print("  {:<30} {:>14} {:>14}".format(*r))

# ── STEP 6: COMBINATO 1h + 5m (se post-fix è abbastanza buono) ───────────────
avg_r_post = df_post["pnl_r"].mean()
dd_mc_post = mc_post_15["dd_med"]
be_post    = avg_r_post

print()
print(SEP)
print("  VALUTAZIONE POST-FIX")
print(SEP)
print()
print("  avg_r post-fix:         {:+.4f}R".format(avg_r_post))
print("  Break-even slippage:    {:.4f}R".format(be_post))
print("  MC DD mediano @0.15R:   {:.1f}%".format(dd_mc_post))
print()

if avg_r_post > 0.30 and dd_mc_post < 20:
    soglia_ok = True
    print("  SOGLIA RAGGIUNTA: avg_r > 0.30R e DD @0.15R < 20%")
    print("  Il 5m e' utilizzabile. Calcolo combinato 1h + 5m:")
else:
    soglia_ok = False
    print("  SOGLIA NON RAGGIUNTA: avg_r={:+.4f}R (soglia 0.30R) | DD={:.1f}% (soglia <20%)".format(
        avg_r_post, dd_mc_post))
    print("  Il 5m e' ancora borderline. Calcolo combinato 1h + 5m comunque:")

print()

# Calcola combinato comunque
n12_1h    = 346
pnl_1h_raw = pd.read_csv("data/val_1h_large_post_fix.csv")
pnl_1h_raw = pnl_1h_raw[pnl_1h_raw["entry_filled"] == True]
VALID_1H = {"double_bottom","double_top","macd_divergence_bull","macd_divergence_bear",
            "rsi_divergence_bull","rsi_divergence_bear"}
pnl_1h = pnl_1h_raw[pnl_1h_raw["pattern_name"].isin(VALID_1H)]["pnl_r"].values
pnl_1h_adj = pnl_1h - 0.15

pnl_5m_adj = df_post["pnl_r"].values - 0.15
n12_total  = n12_1h + n12_post

rng3 = np.random.default_rng(SEED + 200)

print("  Combinato 1h ({} t/a, 0.15R slip) + 5m post-fix ({} t/a, 0.15R slip) = {} t/a:".format(
    n12_1h, n12_post, n12_total))

# Bootstrap proporzionale
n_per_sim_1h = n12_1h
n_per_sim_5m = n12_post

draws_1h = rng3.choice(pnl_1h_adj, size=(N_SIMS, n_per_sim_1h), replace=True)
draws_5m = rng3.choice(pnl_5m_adj, size=(N_SIMS, n_per_sim_5m), replace=True)
draws_all = np.concatenate([draws_1h, draws_5m], axis=1)

# Shuffle
rand_ord = rng3.random((N_SIMS, n12_total))
idx_ord  = np.argsort(rand_ord, axis=1)
draws_all = draws_all[np.arange(N_SIMS)[:, None], idx_ord]

mults = 1.0 + RISK_PCT * draws_all
paths = np.hstack([np.full((N_SIMS, 1), CAPITAL),
                   np.cumprod(mults, axis=1) * CAPITAL])
final  = paths[:, -1]
rm     = np.maximum.accumulate(paths, axis=1)
max_dd = (-(paths - rm) / rm * 100).max(axis=1)

p50  = float(np.percentile(final, 50))
p5   = float(np.percentile(final, 5))
p95  = float(np.percentile(final, 95))

print()
print("  {:<30} {:>12} {:>12} {:>12}".format(
    "Scenario", "Solo 1h", "Solo 5m", "Combinato"))
print(SEP2)

mc_1h_only = mc_stats(rng3, pnl_1h_adj, n12_1h)
mc_5m_only = mc_stats(rng3, pnl_5m_adj, n12_post)

comp_rows = [
    ("Trade/anno",       str(n12_1h),       str(n12_post),   str(n12_total)),
    ("MC mediana 12m",   "EUR {:,.0f}".format(mc_1h_only["p50"]),
                         "EUR {:,.0f}".format(mc_5m_only["p50"]),
                         "EUR {:,.0f}".format(p50)),
    ("Prob. profitto",   "{:.1f}%".format(mc_1h_only["prob_profit"]),
                         "{:.1f}%".format(mc_5m_only["prob_profit"]),
                         "{:.1f}%".format((final > CAPITAL).mean() * 100)),
    ("DD mediano",       "{:.1f}%".format(mc_1h_only["dd_med"]),
                         "{:.1f}%".format(mc_5m_only["dd_med"]),
                         "{:.1f}%".format(float(np.median(max_dd)))),
    ("DD > 25%",         "{:.1f}%".format(mc_1h_only["dd_25"]),
                         "{:.1f}%".format(mc_5m_only["dd_25"]),
                         "{:.1f}%".format((max_dd > 25).mean() * 100)),
    ("Worst 5%",         "EUR {:,.0f}".format(mc_1h_only["p5"]),
                         "EUR {:,.0f}".format(mc_5m_only["p5"]),
                         "EUR {:,.0f}".format(p5)),
]
for r in comp_rows:
    print("  {:<30} {:>12} {:>12} {:>12}".format(*r))

print()
print(SEP)
