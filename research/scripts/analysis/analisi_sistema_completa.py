"""
Analisi sistema completa — Parti A, B, C.
Dataset: val_1h_full.csv + val_5m_expanded.csv (6+4 pattern validati).
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import pytz

SEP = "=" * 72
SUB = "-" * 56

PATTERNS_1H = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}
PATTERNS_5M = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
}
BLOCKED_5M = {"SPY", "AAPL", "MSFT", "GOOGL", "WMT"}
ET = pytz.timezone("America/New_York")

# ── Load ───────────────────────────────────────────────────────────────────────
df1r = pd.read_csv("data/val_1h_full.csv")
df1r["pattern_timestamp"] = pd.to_datetime(df1r["pattern_timestamp"], utc=True)
df1r["_hour_et"] = df1r["pattern_timestamp"].dt.tz_convert(ET).dt.hour
df1r["_ts_h"]   = df1r["pattern_timestamp"].dt.floor("h")

df5r = pd.read_csv("data/val_5m_expanded.csv")
df5r["pattern_timestamp"] = pd.to_datetime(df5r["pattern_timestamp"], utc=True)
df5r["_hour_et"] = df5r["pattern_timestamp"].dt.tz_convert(ET).dt.hour

# Filtered pools (6 pattern 1h, 4 pattern 5m, no blocked hours yet — we test those separately)
df1 = df1r[
    df1r["entry_filled"].astype(bool) &
    df1r["pattern_name"].isin(PATTERNS_1H)
].copy()

df5 = df5r[
    df5r["entry_filled"].astype(bool) &
    df5r["provider"].eq("alpaca") &
    df5r["pattern_name"].isin(PATTERNS_5M) &
    ~df5r["symbol"].isin(BLOCKED_5M)
].copy()

print(SEP)
print(f"  BASE 1h: n={len(df1):,}  avg_r={df1['pnl_r'].mean():+.4f}R  "
      f"WR={(df1['pnl_r']>0).mean()*100:.1f}%")
print(f"  BASE 5m: n={len(df5):,}  avg_r={df5['pnl_r'].mean():+.4f}R  "
      f"WR={(df5['pnl_r']>0).mean()*100:.1f}%")
print(SEP)


# ==============================================================================
# A1 — CONFLUENZA (regola dei 2 pattern)
# ==============================================================================
print()
print(SEP)
print("  A1 — REGOLA DEI 2 PATTERN (confluenza)")
print(SEP)

# Rebuild confluence from full dataset (all patterns per symbol+hour)
# Use ALL entry_filled patterns (not just the 6 validated) because confluence
# counts ALL validated patterns detected at the same time
conf_all = df1r[df1r["entry_filled"].astype(bool)].copy()
conf_cnt = (conf_all.groupby(["symbol", "_ts_h"])["pattern_name"]
            .count().reset_index().rename(columns={"pattern_name": "n_patterns_total"}))
df1 = df1.merge(conf_cnt, on=["symbol", "_ts_h"], how="left")
df1["n_patterns_total"] = df1["n_patterns_total"].fillna(1).astype(int)

print("  Distribuzione confluenza (6 pattern validati 1h, entry_filled):")
g_conf = df1.groupby("n_patterns_total")["pnl_r"].agg(
    n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
)
g_conf["pct"] = g_conf["n"] / len(df1) * 100
baseline_r = df1["pnl_r"].mean()
for k, row in g_conf.iterrows():
    flag = " <<<" if row["avg_r"] < 0.15 else ""
    print(f"  {k} pattern/barra: n={int(row['n']):>5} ({row['pct']:>5.1f}%)  "
          f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")

r_conf2 = df1[df1["n_patterns_total"] >= 2]["pnl_r"].mean()
r_conf1 = df1[df1["n_patterns_total"] == 1]["pnl_r"].mean()
n_dropped = (df1["n_patterns_total"] == 1).sum()
print()
print(f"  Con confluenza >= 2: n={int((df1['n_patterns_total']>=2).sum()):,}  "
      f"avg_r={r_conf2:+.4f}R  (+{r_conf2-r_conf1:+.4f}R vs 1-pattern)")
print(f"  Trade scartati se minimo=2: {n_dropped:,} ({n_dropped/len(df1)*100:.1f}%)")
print(f"  Baseline senza filtro: avg_r={baseline_r:+.4f}R")
print()

# Per pattern
print("  avg_r per pattern per livello di confluenza (1 vs 2+):")
for pn in sorted(PATTERNS_1H):
    sub = df1[df1["pattern_name"] == pn]
    r1 = sub[sub["n_patterns_total"] == 1]["pnl_r"].mean()
    r2 = sub[sub["n_patterns_total"] >= 2]["pnl_r"].mean()
    n1 = (sub["n_patterns_total"] == 1).sum()
    n2 = (sub["n_patterns_total"] >= 2).sum()
    print(f"  {pn:<32}: 1-pat n={n1:>4} {r1:+.4f}R | 2+-pat n={n2:>4} {r2:+.4f}R")


# ==============================================================================
# A2 — SOGLIA MIN_STRENGTH
# ==============================================================================
print()
print(SEP)
print("  A2 — SOGLIA MIN_STRENGTH (attuale >= 0.70 in SIGNAL_MIN_STRENGTH)")
print(SEP)

# Note: current live filter discards strength < 0.70. Pool already has all
# strength values since backtest doesn't apply the live strength filter.
for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    print(f"  -- {tf_label} --")
    for lo, hi, label in [
        (0.50, 0.60, "0.50-0.60"),
        (0.60, 0.70, "0.60-0.70"),
        (0.70, 0.80, "0.70-0.80"),
        (0.80, 0.90, "0.80-0.90"),
        (0.50, 0.70, "0.50-0.70 (sotto soglia)"),
        (0.60, 1.00, "0.60+ (soglia abbassata)"),
        (0.70, 1.00, "0.70+ (soglia attuale)"),
    ]:
        sub = df_tf[(df_tf["pattern_strength"] >= lo) & (df_tf["pattern_strength"] < hi)]
        if len(sub) >= 20:
            print(f"  strength {label:<24}: n={len(sub):>5}  "
                  f"avg_r={sub['pnl_r'].mean():+.4f}R  WR={(sub['pnl_r']>0).mean()*100:.1f}%")
    print()


# ==============================================================================
# A3 — REGIME FILTER
# ==============================================================================
print(SEP)
print("  A3 — SCREENER SCORE COME PROXY REGIME (market_regime non in CSV)")
print("  screener_score = structural(0-9) + direction_bonus(0-3)")
print("  Components: market_regime(trend=3,range=2,neutral=1) +")
print("              volatility_regime(high=3,normal=2,low=1) +")
print("              candle_expansion(expansion=3,normal=2,compression=1) +")
print("              direction_bias(+3/+2/+1)")
print(SEP)

for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    print(f"  -- {tf_label} screener_score distribution --")
    # Score range in data
    print(f"  range: [{df_tf['screener_score'].min()}, {df_tf['screener_score'].max()}]  "
          f"mean={df_tf['screener_score'].mean():.1f}")
    g = df_tf.groupby("screener_score")["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    for score, row in g.iterrows():
        if row["n"] >= 30:
            flag = " ***" if row["avg_r"] > 0.8 else (" <<" if row["avg_r"] < 0.3 else "")
            print(f"  score={score:>2}: n={int(row['n']):>5}  "
                  f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")
    print()

# screener_score components (structural vs direction)
print("  A3b — Strutturale score (inferita dal range score vs pattern direction):")
df1["_struct_proxy"] = df1["screener_score"] - 3  # rimuovi max direction bonus
g_dir = df1.groupby("direction")["screener_score"].agg(
    n="count", mean="mean", min="min", max="max"
)
for d, row in g_dir.iterrows():
    print(f"  direction={d}: n={int(row['n']):<5} score mean={row['mean']:.2f}  "
          f"[{int(row['min'])},{int(row['max'])}]")


# ==============================================================================
# A4 — TAKE PROFIT LEVELS
# ==============================================================================
print()
print(SEP)
print("  A4 — TAKE PROFIT LEVELS")
print(SEP)

for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    # Compute actual R multiples from prices
    df_tf = df_tf.copy()
    df_tf["_entry"]  = pd.to_numeric(df_tf["entry_price"], errors="coerce")
    df_tf["_stop"]   = pd.to_numeric(df_tf["stop_price"],  errors="coerce")
    df_tf["_tp1"]    = pd.to_numeric(df_tf["tp1_price"],   errors="coerce")
    df_tf["_tp2"]    = pd.to_numeric(df_tf["tp2_price"],   errors="coerce")

    # Risk = |entry - stop|
    df_tf["_risk"]   = (df_tf["_entry"] - df_tf["_stop"]).abs()
    # TP1 R = (tp1 - entry) / risk (for long), (entry - tp1) / risk (for short)
    mask_bull = df_tf["direction"] == "bullish"
    df_tf["_tp1_r"] = np.where(
        mask_bull,
        (df_tf["_tp1"] - df_tf["_entry"]) / df_tf["_risk"].replace(0, np.nan),
        (df_tf["_entry"] - df_tf["_tp1"]) / df_tf["_risk"].replace(0, np.nan),
    )
    df_tf["_tp2_r"] = np.where(
        mask_bull,
        (df_tf["_tp2"] - df_tf["_entry"]) / df_tf["_risk"].replace(0, np.nan),
        (df_tf["_entry"] - df_tf["_tp2"]) / df_tf["_risk"].replace(0, np.nan),
    )

    valid = df_tf[df_tf["_risk"] > 0].copy()
    print(f"  -- {tf_label} (n={len(valid):,}) --")
    print(f"  TP1 R medio: {valid['_tp1_r'].median():.3f}R  "
          f"[{valid['_tp1_r'].quantile(0.05):.2f} – {valid['_tp1_r'].quantile(0.95):.2f}]")
    print(f"  TP2 R medio: {valid['_tp2_r'].median():.3f}R  "
          f"[{valid['_tp2_r'].quantile(0.05):.2f} – {valid['_tp2_r'].quantile(0.95):.2f}]")

    # Outcome distribution
    g_oc = valid.groupby("outcome")["pnl_r"].agg(
        n="count", avg_r="mean"
    )
    g_oc["pct"] = g_oc["n"] / len(valid) * 100
    print(f"  Outcome:")
    for oc, row in g_oc.sort_values("n", ascending=False).iterrows():
        print(f"    {str(oc):10s}: {int(row['n']):>5} ({row['pct']:>5.1f}%)  "
              f"avg_r={row['avg_r']:+.4f}R")

    # Simulate TP1 ±20%
    tp1_hit = valid["outcome"] == "tp1"
    tp2_hit = valid["outcome"] == "tp2"
    stop_hit = valid["outcome"] == "stop"

    avg_tp1_r = valid.loc[tp1_hit, "_tp1_r"].mean()
    avg_tp2_r = valid.loc[tp2_hit, "_tp2_r"].mean()
    avg_stop_r = valid.loc[stop_hit, "pnl_r"].mean()
    avg_timeout_r = valid.loc[valid["outcome"] == "timeout", "pnl_r"].mean()

    print(f"  TP1 R attuale: {avg_tp1_r:.3f}R (atteso quando hit)")
    print(f"  TP2 R attuale: {avg_tp2_r:.3f}R (atteso quando hit)")

    # If we tighten TP1 by 20%: WR rises but R per win shrinks
    # Approximate: trades that hit stop but were near TP1 might now hit
    # We can't simulate this precisely without bar-by-bar MFE data
    # Instead: use actual pnl_r distribution
    tp1_rate = tp1_hit.mean()
    tp2_rate = tp2_hit.mean()
    stop_rate = stop_hit.mean()

    print(f"  TP1 rate: {tp1_rate*100:.1f}%  TP2 rate: {tp2_rate*100:.1f}%  "
          f"Stop rate: {stop_rate*100:.1f}%")
    print()

    # Per-pattern TP analysis
    print(f"  TP1/TP2 per pattern ({tf_label}):")
    for pn in sorted(PATTERNS_1H if tf_label == "1h" else PATTERNS_5M):
        sub = valid[valid["pattern_name"] == pn]
        if len(sub) < 30:
            continue
        t1r = sub[sub["outcome"] == "tp1"]["_tp1_r"].mean()
        t2r = sub[sub["outcome"] == "tp2"]["_tp2_r"].mean()
        wr1 = (sub["outcome"] == "tp1").mean() * 100
        wr2 = (sub["outcome"] == "tp2").mean() * 100
        print(f"    {pn:<32}: TP1 {wr1:.1f}% @ {t1r:.2f}R  |  TP2 {wr2:.1f}% @ {t2r:.2f}R")
    print()


# ==============================================================================
# A5 — STOP LOSS DISTANCE (risk_pct)
# ==============================================================================
print(SEP)
print("  A5 — STOP LOSS DISTANCE (risk_pct = distanza stop in % del prezzo)")
print(SEP)

for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    rp = df_tf["risk_pct"].dropna()
    print(f"  -- {tf_label} --")
    print(f"  risk_pct: median={rp.median():.3f}%  mean={rp.mean():.3f}%  "
          f"p5={rp.quantile(0.05):.3f}%  p95={rp.quantile(0.95):.3f}%")

    bins   = [0, 0.5, 1.0, 1.5, 2.0, 3.0, 100]
    labels = ["0-0.5%", "0.5-1%", "1-1.5%", "1.5-2%", "2-3%", "3%+"]
    df_tf2 = df_tf.copy()
    df_tf2["_rp_bin"] = pd.cut(df_tf2["risk_pct"], bins=bins, labels=labels)
    g = df_tf2.groupby("_rp_bin", observed=True)["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    for k, row in g.iterrows():
        if row["n"] >= 20:
            flag = " <<" if row["avg_r"] < 0 else ""
            print(f"  {k:8s}: n={int(row['n']):>5}  "
                  f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")
    print()


# ==============================================================================
# B2 — PROFILO DEL GIORNO (prime 2h vs dopo)
# ==============================================================================
print(SEP)
print("  B2 — PROFILO DEL GIORNO: range-building vs trend-following")
print("  Definizione range (09:30-11:30 ET) vs trading post-range (11:30-16:00 ET)")
print(SEP)

for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    print(f"  -- {tf_label} --")
    # 1h: candle is 1h, "09:xx" = 09:00-09:59, "10:xx" = 10:00-10:59
    # Range-building: 09:xx and 10:xx ET (US stocks only)
    # Post-range: 11:xx+
    yf_mask = df_tf["provider"] == "yahoo_finance" if "provider" in df_tf.columns else pd.Series(True, index=df_tf.index)
    h = df_tf["_hour_et"]
    # US market only
    is_range = h.isin([9, 10])          # 09:00-10:59 ET
    is_post  = h.isin([11, 12, 13, 14, 15])  # 11:00-16:00 ET
    is_eu    = h.isin([3, 4, 5, 6, 7, 8])    # EU/pre-market

    for label_h, mask in [("Range-build (09-10 ET)", is_range),
                           ("Post-range  (11-15 ET)", is_post),
                           ("EU/pre-mkt  (03-08 ET)", is_eu)]:
        sub = df_tf[mask]
        if len(sub) >= 30:
            print(f"  {label_h}: n={len(sub):>5}  "
                  f"avg_r={sub['pnl_r'].mean():+.4f}R  "
                  f"WR={(sub['pnl_r']>0).mean()*100:.1f}%")
    print()


# ==============================================================================
# B4 — CORRELAZIONE TRA SIMBOLI (simultaneità e direzionalità)
# ==============================================================================
print(SEP)
print("  B4 — CORRELAZIONE TRA SIMBOLI (trade simultanei)")
print(SEP)

# Group by timestamp hour: how many symbols have a trade at the same time?
df1["_ts_h"] = df1["pattern_timestamp"].dt.floor("h")
sim = df1.groupby("_ts_h").agg(
    n_symbols=("symbol", "nunique"),
    n_trades=("symbol", "count"),
    n_bull=("direction", lambda x: (x == "bullish").sum()),
    n_bear=("direction", lambda x: (x == "bearish").sum()),
    avg_r_slot=("pnl_r", "mean"),
).reset_index()

print("  Distribuzione trade simultanei (per ora):")
sc = sim["n_trades"].value_counts().sort_index()
for k, v in sc.items():
    if k <= 10:
        print(f"  {k} trade/ora: {v:>5} ore ({v/len(sim)*100:.1f}%)")
print(f"  Max simultanei: {sim['n_trades'].max()}")
print()

# Direction alignment: when multiple trades, are they all same direction?
multi = sim[sim["n_trades"] >= 2].copy()
multi["_dir_alignment"] = (multi["n_bull"] == 0) | (multi["n_bear"] == 0)
all_same = multi["_dir_alignment"].mean() * 100
print(f"  Ore con 2+ trade: {len(multi)}")
print(f"  % ore dove TUTTI i trade stessa direzione: {all_same:.1f}%")
mixed = multi[~multi["_dir_alignment"]]
print(f"  Ore con direzioni miste: {len(mixed)} ({len(mixed)/len(multi)*100:.1f}%)")
print()

# Correlation risk: avg_r of slots with many simultaneous trades
print("  avg_r per n_trade simultanei:")
sim_g = sim.groupby("n_trades")["avg_r_slot"].agg(
    n="count", avg_r="mean", worst=lambda x: x.quantile(0.05)
)
for k, row in sim_g.iterrows():
    if row["n"] >= 5:
        print(f"  {k} sim.: n={int(row['n']):>4} ore  "
              f"avg slot_r={row['avg_r']:+.4f}R  worst5%={row['worst']:+.4f}R")


# ==============================================================================
# B5 — KELLY CRITERION
# ==============================================================================
print()
print(SEP)
print("  B5 — KELLY CRITERION")
print(SEP)

for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    wins  = df_tf[df_tf["pnl_r"] > 0]["pnl_r"]
    losses= df_tf[df_tf["pnl_r"] < 0]["pnl_r"].abs()
    wr    = len(wins) / len(df_tf)
    b     = wins.mean()   # avg win in R
    a     = losses.mean() # avg loss in R
    # Kelly fraction of 1R risk: f* = (WR * b/a - (1-WR)) / (b/a)
    odds  = b / a if a > 0 else 0
    kelly = (wr * odds - (1 - wr)) / odds if odds > 0 else 0
    kelly_pct = kelly * 100  # as % of capital

    print(f"  -- {tf_label} --")
    print(f"  WR={wr*100:.1f}%  avg_win={b:.3f}R  avg_loss={a:.3f}R  odds=W/L={odds:.3f}")
    print(f"  Kelly fraction: {kelly:.4f} = {kelly_pct:.2f}% of capital per trade")
    half_kelly = kelly_pct / 2
    print(f"  Half-Kelly (safer):   {half_kelly:.2f}%  vs sistema attuale: 1.00%")
    if kelly_pct > 1.0:
        print(f"  >>> Sistema SOTTO Kelly: potrebbe usare {kelly_pct:.1f}% anziché 1%")
    else:
        print(f"  >>> Sistema SOPRA Kelly: 1% è più rischioso dell'ottimale")
    print()


# ==============================================================================
# B6 — TRAILING STOP (MFE proxy via bars_to_exit e outcome)
# ==============================================================================
print(SEP)
print("  B6 — TRAILING STOP (analisi trade stopped con pnl alto)")
print(SEP)

for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    stopped = df_tf[df_tf["outcome"] == "stop"].copy()
    print(f"  -- {tf_label} — stopped trades: n={len(stopped):,} --")

    # Trades stopped after many bars: were probably in profit at some point
    # Long bar-to-exit = more time = higher chance of having been near TP
    print("  Stopped trades per bars_to_exit:")
    bte_bins = [0, 2, 4, 6, 10, 15, 20, 500]
    bte_lbls = ["1-2", "3-4", "5-6", "7-10", "11-15", "16-20", "21+"]
    stopped["_bte_bin"] = pd.cut(stopped["bars_to_exit"], bins=bte_bins, labels=bte_lbls)
    g = stopped.groupby("_bte_bin", observed=True)["pnl_r"].agg(
        n="count", avg_r="mean"
    )
    for k, row in g.iterrows():
        if row["n"] >= 10:
            print(f"  bars {k:>5}: n={int(row['n']):>5}  avg_loss={row['avg_r']:+.4f}R")
    print()

    # Profit factor of wins vs losses
    wins_r  = df_tf[df_tf["pnl_r"] > 0]["pnl_r"].sum()
    loss_r  = df_tf[df_tf["pnl_r"] < 0]["pnl_r"].abs().sum()
    pf = wins_r / loss_r if loss_r > 0 else float("inf")
    print(f"  Profit factor: {pf:.3f}  "
          f"(wins sum={wins_r:.1f}R, losses sum={loss_r:.1f}R)")

    # How many stops are at exactly -1.0 to -1.5R (clean stop)?
    clean = ((stopped["pnl_r"] >= -1.5) & (stopped["pnl_r"] <= -0.8)).mean() * 100
    print(f"  % stop 'puliti' (-0.8 a -1.5R): {clean:.1f}%")
    print()


# ==============================================================================
# C1 — PERCHE' SCORE BASSO = EDGE ALTO
# ==============================================================================
print(SEP)
print("  C1 — SCREENER SCORE: ANATOMIA DEL PARADOSSO")
print("  Formula: score = market_regime(0-3) + volatility(0-3)")
print("                 + candle_expansion(0-3) + direction_bonus(1-3)")
print("  Range: [1,12]  — score_basso=4-6, score_medio=7-9, score_alto=10-12")
print(SEP)

# Decompose score ranges
for tf_label, df_tf in [("1h", df1), ("5m", df5)]:
    print(f"  -- {tf_label} --")
    # Score already numeric — map to bands
    df_tf = df_tf.copy()
    df_tf["_score_band"] = pd.cut(
        df_tf["screener_score"],
        bins=[0, 6, 9, 12],
        labels=["basso(4-6)", "medio(7-9)", "alto(10-12)"]
    )

    g = df_tf.groupby("_score_band", observed=True)["pnl_r"].agg(
        n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100
    )
    g["pct"] = g["n"] / len(df_tf) * 100
    for k, row in g.iterrows():
        if row["n"] >= 20:
            print(f"  {str(k):<14}: n={int(row['n']):>5} ({row['pct']:>5.1f}%)  "
                  f"avg_r={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%")

    # Hypothesis: score basso = range/quiet market = più spazio per rimbalzo
    # score alto = trend forte = momentum già esaurito quando il pattern si forma
    print()
    print(f"  Analisi per componente score (per quanto inferibile dal score stesso):")
    # I pattern di divergenza funzionano meglio CONTRO il trend dominante
    # Se score alto = trend forte => il pattern contro-trend ha meno spazio
    df_tf["_score_above_median"] = df_tf["screener_score"] > df_tf["screener_score"].median()

    # Direction vs score
    for dir_val in ["bullish", "bearish"]:
        sub = df_tf[df_tf["direction"] == dir_val]
        low_r = sub[sub["screener_score"] < 10]["pnl_r"].mean()
        high_r = sub[sub["screener_score"] >= 10]["pnl_r"].mean()
        n_low = (sub["screener_score"] < 10).sum()
        n_high = (sub["screener_score"] >= 10).sum()
        print(f"  {dir_val:8s}: score<10 avg={low_r:+.4f}R (n={n_low})  |  "
              f"score>=10 avg={high_r:+.4f}R (n={n_high})")
    print()

    # Pattern breakdown by score band
    print(f"  Per pattern ({tf_label}): avg_r score<10 vs score>=10:")
    for pn in sorted(PATTERNS_1H if tf_label == "1h" else PATTERNS_5M):
        sub = df_tf[df_tf["pattern_name"] == pn]
        lo = sub[sub["screener_score"] < 10]["pnl_r"]
        hi = sub[sub["screener_score"] >= 10]["pnl_r"]
        if len(lo) >= 20 and len(hi) >= 20:
            print(f"  {pn:<32}: score<10={lo.mean():+.4f}R (n={len(lo)})  "
                  f"score>=10={hi.mean():+.4f}R (n={len(hi)})  "
                  f"gap={lo.mean()-hi.mean():+.4f}R")
    print()


# ==============================================================================
# PRIORITA' FINALE
# ==============================================================================
print(SEP)
print("  PRIORITA' — TOP CAMBIAMENTI PER IMPATTO × FACILITA'")
print(SEP)

# Compute deltas for key filters
base = df1["pnl_r"].mean()
n_base = len(df1)

rows = []

# Confluenza >= 2
m = df1["n_patterns_total"] >= 2
r = df1[m]["pnl_r"].mean()
rows.append(("Confluenza>=2 (già implementata)", m.sum(), r, r-base, "GIA LIVE", "alto"))

# Score < 10
m = df1["screener_score"] < 10
r = df1[m]["pnl_r"].mean()
rows.append(("Score < 10", m.sum(), r, r-base, "media", "critico"))

# Escludi 03+09 ET
m = ~df1["_hour_et"].isin([3, 9])
r = df1[m]["pnl_r"].mean()
rows.append(("Escludi 03:xx+09:xx ET (FIX7+8, implementato)", m.sum(), r, r-base, "GIA LIVE", "alto"))

# Strength < 0.60 (sotto-soglia)
m = df1["pattern_strength"] >= 0.60
r = df1[m]["pnl_r"].mean()
rows.append(("Min strength 0.60 (vs 0.70 attuale)", m.sum(), r, r-base, "bassa", "medio"))

# Stop stretto < 0.5%
m = df1["risk_pct"] >= 0.5
r = df1[m]["pnl_r"].mean()
rows.append(("Escludi stop < 0.5% (micro-stop)", m.sum(), r, r-base, "bassa", "basso"))

print(f"  Baseline: n={n_base:,}  avg_r={base:+.4f}R")
print()
print(f"  {'Filtro':<45} {'n':>6} {'avg_r':>8} {'delta':>8} {'Compless.':>10} {'Rischio OF':>12}")
print("  " + "-" * 95)
for name, n, avg, delta, compl, risk in sorted(rows, key=lambda x: -x[3]):
    print(f"  {name:<45} {n:>6,} {avg:>+8.4f} {delta:>+8.4f} {compl:>10} {risk:>12}")
