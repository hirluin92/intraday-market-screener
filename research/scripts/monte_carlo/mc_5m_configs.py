"""
Monte Carlo per 3 config 5m post-fix + 1h combinato.
Config:
  Base      — ore 11,13,14,15 (no 12, no DELL, no risk>2%)
  PowerHours — ore 14,15
  LastHour   — ora 15 only
Run: python /app/data/mc_5m_configs.py
"""
import warnings; warnings.filterwarnings("ignore")
import os, math
import pandas as pd
import numpy as np
from datetime import timedelta
import psycopg2

DATA_DIR  = "/app/data"
F_5M      = os.path.join(DATA_DIR, "val_5m_expanded.csv")
F_1H      = os.path.join(DATA_DIR, "val_1h_production.csv")

MIN_RISK_5M   = 0.50
MAX_RISK_5M   = 2.0
SLIP_PCT      = 0.05
ENTRY_SLIP_R  = 0.03
CAPITAL       = 100_000.0
RISK_DOLLAR   = 1_000.0
SLOTS_5M      = 2
SLOTS_1H      = 3
TRADING_DAYS  = 21
N_SIM         = 5_000
N_MONTHS      = 12
SEED          = 42
EVICT_R       = 0.10

VALIDATED_5M    = {"double_top","double_bottom","macd_divergence_bear","macd_divergence_bull"}
BLOCKED_5M_SYMS = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL"}   # post-fix incl. DELL

# ─── Helpers ─────────────────────────────────────────────────────────────────
def load_spy() -> dict:
    try:
        conn = psycopg2.connect(host="postgres", port=5432,
            dbname="intraday_market_screener", user="postgres", password="postgres")
        df = pd.read_sql("""
            SELECT DATE(c.timestamp AT TIME ZONE 'UTC') AS d, ci.price_vs_ema50_pct AS pct
            FROM candles c JOIN candle_indicators ci ON c.id=ci.candle_id
            WHERE c.symbol='SPY' AND c.timeframe='1d' AND c.provider='yahoo_finance'
            ORDER BY c.timestamp ASC
        """, conn); conn.close()
        df["d"] = pd.to_datetime(df["d"]).dt.date
        spy, prev = {}, "neutral"
        for _, r in df.sort_values("d").iterrows():
            spy[r["d"]] = prev
            prev = ("bull" if r["pct"]>2 else "bear" if r["pct"]<-2 else "neutral") \
                   if r["pct"] is not None and not (isinstance(r["pct"],float) and math.isnan(r["pct"])) \
                   else "neutral"
        return spy
    except Exception as e:
        print(f"  WARN SPY: {e}"); return {}

def get_regime(spy, ts_utc) -> str:
    ts = pd.Timestamp(ts_utc)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    d = ts.date()
    for i in range(1,15):
        c = d - timedelta(days=i)
        if c in spy: return spy[c]
    return "neutral"

def regime_ok(regime, direction) -> bool:
    if regime=="bull": return direction=="bullish"
    if regime=="bear": return direction=="bearish"
    return True

def add_slip(df):
    r = df["risk_pct"].clip(lower=0.01)
    return df["pnl_r"] - ENTRY_SLIP_R/r - np.where(df["outcome"]=="stop", SLIP_PCT/r, 0.0)

def stats(df, col="pnl_r_slip"):
    n = len(df)
    if n == 0: return {"n":0,"avg_r":np.nan,"wr":np.nan,"freq":0.0}
    wr  = df["outcome"].isin(["tp1","tp2"]).mean()*100
    avg = df[col].mean()
    months = max(df["pts"].dt.to_period("M").nunique(), 1)
    return {"n":n, "avg_r":avg, "wr":wr, "freq":n/months}

def mc(r_dist, trades_month, label, n_sim=N_SIM, n_months=N_MONTHS):
    rng = np.random.default_rng(SEED)
    r_adj = r_dist - EVICT_R
    final = np.zeros(n_sim)
    monthly = np.zeros((n_sim, n_months))
    for s in range(n_sim):
        cum = 0.0
        for m in range(n_months):
            nt = rng.poisson(trades_month)
            if nt > 0:
                cum += rng.choice(r_adj, size=nt, replace=True).sum() * RISK_DOLLAR
            monthly[s,m] = cum
        final[s] = cum
    med   = np.median(final)
    w5    = np.percentile(final, 5)
    prob  = (final>0).mean()*100
    path  = np.median(monthly, axis=0)
    peak  = np.maximum.accumulate(np.concatenate([[0],path]))
    dd    = (path - peak[1:]).min() / CAPITAL * 100
    return {
        "label":label, "avg_r":float(r_adj.mean()),
        "trades_anno": trades_month*12,
        "median_eq": CAPITAL+med, "median_pct": med/CAPITAL*100,
        "worst5_pct": w5/CAPITAL*100, "dd_pct":dd, "prob_prof":prob,
    }

def print_mc(r):
    print(f"  [{r['label']:30s}] "
          f"avg_r={r['avg_r']:+.3f}  trade/anno={r['trades_anno']:.0f}  "
          f"mediana=€{r['median_eq']:>10,.0f} ({r['median_pct']:+.1f}%)  "
          f"worst5%={r['worst5_pct']:+.1f}%  DD={r['dd_pct']:.1f}%  ProbP={r['prob_prof']:.0f}%")

# ─── Load & baseline filter ──────────────────────────────────────────────────
def load_5m(spy):
    raw = pd.read_csv(F_5M)
    df = raw[(raw["provider"]=="alpaca") & (raw["entry_filled"]==True)].copy()
    df["pts"] = pd.to_datetime(df["pattern_timestamp"], utc=True)
    df["hour_et"] = df["pts"].dt.tz_convert("America/New_York").dt.hour
    # Baseline: all hours 11-15, validated patterns, bars_to_entry≤3, not blocked symbols
    df = df[(df["hour_et"]>=11) & (df["hour_et"]<16)]
    df = df[df["pattern_name"].isin(VALIDATED_5M)]
    df = df[df["bars_to_entry"]<=3]
    df = df[~df["symbol"].isin(BLOCKED_5M_SYMS)]
    # Regime + MIN_RISK + MAX_RISK
    df["regime"]     = df["pts"].apply(lambda t: get_regime(spy, t))
    df["regime_ok"]  = df.apply(lambda r: regime_ok(r["regime"], r["direction"]), axis=1)
    df = df[df["regime_ok"] & (df["risk_pct"]>=MIN_RISK_5M) & (df["risk_pct"]<=MAX_RISK_5M)]
    df["pnl_r_slip"] = add_slip(df)
    return df

def load_1h(spy):
    df = pd.read_csv(F_1H)
    yf = df[df["provider"]=="yahoo_finance"].copy()
    yf["pts"] = pd.to_datetime(yf["pattern_timestamp"], utc=True)
    yf["regime"]    = yf["pts"].apply(lambda t: get_regime(spy, t))
    yf["regime_ok"] = yf.apply(lambda r: regime_ok(r["regime"],r["direction"]), axis=1)
    yf = yf[yf["regime_ok"] & (yf["risk_pct"]>=0.30)].copy()
    r  = yf["risk_pct"].clip(lower=0.01)
    yf["pnl_r_slip"] = yf["pnl_r"] - ENTRY_SLIP_R/r - np.where(yf["outcome"]=="stop", SLIP_PCT/r, 0.0)
    return yf

# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    print("="*75)
    print("MONTE CARLO 5m — 3 CONFIG + COMBO  |  5000 sim × 12 mesi  |  €100K 1%R")
    print("="*75)

    spy = load_spy()
    print(f"  SPY regime: {len(spy)} giorni")

    df_base = load_5m(spy)
    df_1h   = load_1h(spy)

    # 3 config 5m
    df_nooon   = df_base.copy()                                   # Base: 11,13,14,15 (no 12)
    df_power   = df_base[df_base["hour_et"].isin([14,15])].copy() # PowerHours: 14,15
    df_last    = df_base[df_base["hour_et"]==15].copy()           # LastHour: 15 only

    configs_5m = [
        ("Base (11,13,14,15 — no 12)", df_nooon),
        ("PowerHours (14,15)",          df_power),
        ("LastHour (15)",               df_last),
    ]

    # ── Tabella breakdown configs ────────────────────────────────────────────
    print("\n" + "─"*75)
    print(f"  {'Config 5m':<35} {'Filtro ore':<18} {'N':>6}  {'avg_r+slip':>10}  {'WR':>7}")
    print("─"*75)
    for label, df in configs_5m:
        s = stats(df)
        ore = ("11,13,14,15" if "Base" in label else
               "14,15"       if "Power" in label else "15")
        print(f"  {label:<35} {ore:<18} {s['n']:>6,}  {s['avg_r']:>+10.3f}  {s['wr']:>6.1f}%")

    # Per-pattern per config
    print("\n  Per-pattern breakdown:")
    for label, df in configs_5m:
        print(f"\n  [{label}]")
        for pat, grp in df.groupby("pattern_name"):
            s = stats(grp)
            print(f"    {pat:<28} n={s['n']:>4,}  avg_r={s['avg_r']:+.3f}  WR={s['wr']:.1f}%")

    # 1h stats
    s_1h = stats(df_1h)
    eff_1h = min(s_1h["freq"], SLOTS_1H * TRADING_DAYS)
    r_1h   = df_1h["pnl_r_slip"].values
    print(f"\n  [1h Yahoo]   n={s_1h['n']:,}  avg_r={s_1h['avg_r']:+.3f}  freq={s_1h['freq']:.0f}→{eff_1h:.0f}/mese")

    # ── Monte Carlo ──────────────────────────────────────────────────────────
    print("\n" + "="*75)
    print("MONTE CARLO — Solo 1h + Combo (3 slot 1h + 2 slot 5m)")
    print("="*75)
    print()

    mc_1h = mc(r_1h, eff_1h, "Solo 1h Yahoo")
    print_mc(mc_1h)

    print()
    results_combo = []
    for label, df in configs_5m:
        s = stats(df)
        eff_5m = min(s["freq"], SLOTS_5M * TRADING_DAYS)
        r_5m   = df["pnl_r_slip"].values

        # Per MC combo corretto: campionamento pesato per frequenza
        # Invece di concatenare naively, uso un approccio weighted:
        # disegno separatamente n_1h da dist_1h e n_5m da dist_5m per mese
        rng = np.random.default_rng(SEED)
        final_combo = np.zeros(N_SIM)
        monthly_combo = np.zeros((N_SIM, N_MONTHS))
        r_1h_adj = r_1h - EVICT_R
        r_5m_adj = r_5m - EVICT_R

        for sim_i in range(N_SIM):
            cum = 0.0
            for m in range(N_MONTHS):
                n1h = rng.poisson(eff_1h)
                n5m = rng.poisson(eff_5m)
                if n1h > 0:
                    cum += rng.choice(r_1h_adj, size=n1h, replace=True).sum() * RISK_DOLLAR
                if n5m > 0:
                    cum += rng.choice(r_5m_adj, size=n5m, replace=True).sum() * RISK_DOLLAR
                monthly_combo[sim_i, m] = cum
            final_combo[sim_i] = cum

        med   = np.median(final_combo)
        w5    = np.percentile(final_combo, 5)
        prob  = (final_combo>0).mean()*100
        path  = np.median(monthly_combo, axis=0)
        peak  = np.maximum.accumulate(np.concatenate([[0],path]))
        dd    = (path - peak[1:]).min() / CAPITAL * 100
        avg_r_combo = (eff_1h * float(r_1h_adj.mean()) + eff_5m * float(r_5m_adj.mean())) / (eff_1h + eff_5m)

        r = {
            "label": f"1h + 5m {label}",
            "avg_r": avg_r_combo,
            "trades_anno": (eff_1h+eff_5m)*12,
            "median_eq": CAPITAL+med, "median_pct": med/CAPITAL*100,
            "worst5_pct": w5/CAPITAL*100, "dd_pct":dd, "prob_prof":prob,
            "freq_5m": eff_5m,
        }
        results_combo.append(r)
        print_mc(r)

    # ── Tabella finale ───────────────────────────────────────────────────────
    print("\n" + "="*75)
    print("TABELLA RIASSUNTIVA")
    print("="*75)
    hdr = f"  {'Scenario':<35} {'Trade/anno':>10} {'avg_r':>7} {'Mediana 12m':>14} {'Worst 5%':>10} {'DD%':>6} {'ProbP':>7}"
    print(hdr)
    print("─"*75)

    def row(r):
        print(f"  {r['label']:<35} {r['trades_anno']:>10.0f} {r['avg_r']:>+7.3f} "
              f"  €{r['median_eq']:>10,.0f} ({r['median_pct']:>+5.1f}%) "
              f"{r['worst5_pct']:>+9.1f}% {r['dd_pct']:>5.1f}% {r['prob_prof']:>6.0f}%")

    row(mc_1h)
    for r in results_combo:
        row(r)

    # ── Edge degradation per la config migliore ──────────────────────────────
    print("\n" + "="*75)
    best_cfg_label, best_cfg_df = max(
        configs_5m,
        key=lambda x: stats(x[1])["avg_r"] if len(x[1])>0 else -999
    )
    best_s = stats(best_cfg_df)
    best_eff = min(best_s["freq"], SLOTS_5M*TRADING_DAYS)
    best_r   = best_cfg_df["pnl_r_slip"].values
    print(f"EDGE DEGRADATION — Combo 1h + 5m '{best_cfg_label}'")
    print("="*75)
    print(f"  {'Edge%':<10} {'avg_r combo':>12} {'Mediana 12m':>16} {'Worst 5%':>10} {'ProbP':>7}")
    print("─"*75)

    for edge_pct in [100, 75, 50, 25]:
        r_1h_deg = r_1h * (edge_pct/100)
        r_5m_deg = best_r * (edge_pct/100)
        r_1h_deg_adj = r_1h_deg - EVICT_R
        r_5m_deg_adj = r_5m_deg - EVICT_R

        rng2 = np.random.default_rng(SEED)
        final_deg = np.zeros(N_SIM)
        for sim_i in range(N_SIM):
            cum = 0.0
            for m in range(N_MONTHS):
                n1h = rng2.poisson(eff_1h)
                n5m = rng2.poisson(best_eff)
                if n1h>0: cum += rng2.choice(r_1h_deg_adj, size=n1h, replace=True).sum()*RISK_DOLLAR
                if n5m>0: cum += rng2.choice(r_5m_deg_adj, size=n5m, replace=True).sum()*RISK_DOLLAR
            final_deg[sim_i] = cum

        med_d = np.median(final_deg)
        w5_d  = np.percentile(final_deg, 5)
        prob_d = (final_deg>0).mean()*100
        avg_r_d = (eff_1h*float(r_1h_deg_adj.mean()) + best_eff*float(r_5m_deg_adj.mean())) / (eff_1h+best_eff)
        print(f"  {edge_pct:>4}%       {avg_r_d:>+12.3f}   €{CAPITAL+med_d:>10,.0f} ({med_d/CAPITAL*100:>+5.1f}%) "
              f"{w5_d/CAPITAL*100:>+9.1f}%  {prob_d:>6.0f}%")

    print("\n=== DONE ===")

if __name__ == "__main__":
    main()
