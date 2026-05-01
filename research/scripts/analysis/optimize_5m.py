"""
Ottimizzazione 5m: breakdown per pattern, simbolo, ora, risk_pct.
Applica TUTTI i fix: regime filter, MIN_RISK_PCT=0.50%, slippage model.
Run: python /app/data/optimize_5m.py
"""
import warnings
warnings.filterwarnings("ignore")
import os, math
import pandas as pd
import numpy as np
from datetime import timedelta
import psycopg2

DATA_DIR = "/app/data"
F_5M = os.path.join(DATA_DIR, "val_5m_expanded.csv")

MIN_RISK_5M   = 0.50
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

VALIDATED_5M = {"double_top","double_bottom","macd_divergence_bear","macd_divergence_bull"}


# ─── SPY regime ──────────────────────────────────────────────────────────────
def load_spy_regime() -> dict:
    try:
        conn = psycopg2.connect(host="postgres", port=5432,
            dbname="intraday_market_screener", user="postgres", password="postgres")
        q = """
            SELECT DATE(c.timestamp AT TIME ZONE 'UTC') AS d,
                   ci.price_vs_ema50_pct AS pct
            FROM candles c JOIN candle_indicators ci ON c.id=ci.candle_id
            WHERE c.symbol='SPY' AND c.timeframe='1d' AND c.provider='yahoo_finance'
            ORDER BY c.timestamp ASC
        """
        df = pd.read_sql(q, conn); conn.close()
        df["d"] = pd.to_datetime(df["d"]).dt.date
        df = df.sort_values("d")
        def classify(pct):
            if pct is None or (isinstance(pct, float) and math.isnan(pct)):
                return "neutral"
            return "bull" if pct > 2.0 else "bear" if pct < -2.0 else "neutral"
        spy = {}
        prev = "neutral"
        for _, r in df.iterrows():
            spy[r["d"]] = prev
            prev = classify(r["pct"])
        return spy
    except Exception as e:
        print(f"  WARN SPY failed: {e}")
        return {}


def get_regime(spy: dict, ts_utc) -> str:
    ts = pd.Timestamp(ts_utc)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    d = ts.date()
    for i in range(1, 15):
        check = d - timedelta(days=i)
        if check in spy:
            return spy[check]
    return "neutral"


def regime_ok(regime: str, direction: str) -> bool:
    if regime == "bull":  return direction == "bullish"
    if regime == "bear":  return direction == "bearish"
    return True


def add_slippage(df: pd.DataFrame) -> pd.Series:
    r = df["risk_pct"].clip(lower=0.01)
    entry_slip = ENTRY_SLIP_R / r
    stop_slip  = np.where(df["outcome"] == "stop", SLIP_PCT / r, 0.0)
    return df["pnl_r"] - entry_slip - stop_slip


def stats_row(df: pd.DataFrame, col="pnl_r_slip") -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "avg_r": np.nan, "wr": np.nan}
    wr = df["outcome"].isin(["tp1","tp2"]).mean() * 100
    avg = df[col].mean()
    return {"n": n, "avg_r": avg, "wr": wr}


def monte_carlo(r_dist: np.ndarray, trades_month: float, label: str,
                n_sim=N_SIM, n_months=N_MONTHS) -> dict:
    rng = np.random.default_rng(SEED)
    r_adj = r_dist - EVICT_R
    final_pnl = np.zeros(n_sim)
    monthly_pnl = np.zeros((n_sim, n_months))
    for sim in range(n_sim):
        cum = 0.0
        for m in range(n_months):
            n_t = rng.poisson(trades_month)
            if n_t > 0:
                cum += rng.choice(r_adj, size=n_t, replace=True).sum() * RISK_DOLLAR
            monthly_pnl[sim, m] = cum
        final_pnl[sim] = cum
    median_pnl = np.median(final_pnl)
    pct5_pnl   = np.percentile(final_pnl, 5)
    prob_prof  = (final_pnl > 0).mean() * 100
    med_path   = np.median(monthly_pnl, axis=0)
    peak = np.maximum.accumulate(np.concatenate([[0], med_path]))
    dd_abs = (med_path - peak[1:]).min()
    dd_pct = dd_abs / CAPITAL * 100
    return {
        "label": label,
        "avg_r": float(r_adj.mean()),
        "trades_month": trades_month,
        "median_eq": CAPITAL + median_pnl,
        "median_pct": median_pnl / CAPITAL * 100,
        "worst5_pct": pct5_pnl / CAPITAL * 100,
        "dd_pct": dd_pct,
        "prob_prof": prob_prof,
    }


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("="*70)
    print("OTTIMIZZAZIONE 5m — Breakdowns completi post-fix")
    print("="*70)

    spy = load_spy_regime()
    print(f"  SPY regime: {len(spy)} giorni")

    raw = pd.read_csv(F_5M)
    df = raw[(raw["provider"]=="alpaca") & (raw["entry_filled"]==True)].copy()
    df["pts"] = pd.to_datetime(df["pattern_timestamp"], utc=True)
    df["hour_et"] = df["pts"].dt.tz_convert("America/New_York").dt.hour
    df = df[(df["hour_et"]>=11) & (df["hour_et"]<16)]
    df = df[df["pattern_name"].isin(VALIDATED_5M)]
    df = df[df["bars_to_entry"] <= 3]

    df["regime"] = df["pts"].apply(lambda t: get_regime(spy, t))
    df["regime_ok"] = df.apply(lambda r: regime_ok(r["regime"], r["direction"]), axis=1)

    df_post = df[df["regime_ok"] & (df["risk_pct"] >= MIN_RISK_5M)].copy()
    df_post["pnl_r_slip"] = add_slippage(df_post)

    print(f"\n  Base 5m post-fix: {len(df_post):,} trade")

    # ── 1. Breakdown per pattern ──────────────────────────────────────────────
    print("\n" + "="*70)
    print("1. BREAKDOWN PER PATTERN")
    print("="*70)
    pat_rows = []
    for pat, grp in df_post.groupby("pattern_name"):
        s = stats_row(grp)
        # check per direzione
        bull_g = grp[grp["direction"]=="bullish"]
        bear_g = grp[grp["direction"]=="bearish"]
        bs = stats_row(bull_g); bes = stats_row(bear_g)
        pat_rows.append({
            "Pattern": pat,
            "N": s["n"],
            "avg_r+slip": s["avg_r"],
            "WR%": s["wr"],
            "Bull_N": bs["n"], "Bull_avg": bs["avg_r"],
            "Bear_N": bes["n"], "Bear_avg": bes["avg_r"],
            "Keep?": "SI" if s["avg_r"] > 0.05 else "MARGINAL" if s["avg_r"] > 0 else "NO",
        })
    pat_df = pd.DataFrame(pat_rows).sort_values("avg_r+slip", ascending=False)
    print(pat_df.to_string(index=False, float_format=lambda x: f"{x:+.3f}"))

    # ── 2. Breakdown per simbolo ──────────────────────────────────────────────
    print("\n" + "="*70)
    print("2. BREAKDOWN PER SIMBOLO (top 15 e bottom 15)")
    print("="*70)
    sym_rows = []
    for sym, grp in df_post.groupby("symbol"):
        if len(grp) < 5:
            continue
        s = stats_row(grp)
        sym_rows.append({"Simbolo": sym, "N": s["n"], "avg_r+slip": s["avg_r"], "WR%": s["wr"]})
    sym_df = pd.DataFrame(sym_rows).sort_values("avg_r+slip", ascending=False)

    print("\nTop 15:")
    print(sym_df.head(15).to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    print("\nBottom 15:")
    print(sym_df.tail(15).to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    print(f"\n  (Totale simboli con n>=5: {len(sym_df)})")
    print(f"  Simboli positivi (avg_r>0): {(sym_df['avg_r+slip']>0).sum()} / {len(sym_df)}")
    print(f"  Simboli forti (avg_r>0.20): {(sym_df['avg_r+slip']>0.20).sum()}")

    # ── 3. Breakdown per ora ET ───────────────────────────────────────────────
    print("\n" + "="*70)
    print("3. BREAKDOWN PER ORA (ET)")
    print("="*70)
    hour_rows = []
    for hr, grp in df_post.groupby("hour_et"):
        s = stats_row(grp)
        hour_rows.append({"Ora_ET": hr, "N": s["n"], "avg_r+slip": s["avg_r"], "WR%": s["wr"]})
    hr_df = pd.DataFrame(hour_rows).sort_values("Ora_ET")
    print(hr_df.to_string(index=False, float_format=lambda x: f"{x:+.3f}"))

    # ── 4. Breakdown per risk_pct ─────────────────────────────────────────────
    print("\n" + "="*70)
    print("4. BREAKDOWN PER FASCIA RISK_PCT")
    print("="*70)
    bins   = [0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 3.00, 99.0]
    labels = ["0.50-0.75","0.75-1.00","1.00-1.25","1.25-1.50","1.50-2.00","2.00-3.00","3.00+"]
    df_post["risk_bin"] = pd.cut(df_post["risk_pct"], bins=bins, labels=labels, right=False)
    risk_rows = []
    for rb, grp in df_post.groupby("risk_bin", observed=True):
        s = stats_row(grp)
        risk_rows.append({"Fascia": str(rb), "N": s["n"], "avg_r+slip": s["avg_r"], "WR%": s["wr"]})
    risk_df = pd.DataFrame(risk_rows)
    print(risk_df.to_string(index=False, float_format=lambda x: f"{x:+.3f}"))

    # ── 5. Config ottimale e Monte Carlo ─────────────────────────────────────
    print("\n" + "="*70)
    print("5. CONFIG OTTIMALE + MONTE CARLO COMBO FINALE")
    print("="*70)

    # Simboli positivi (avg_r_slip > 0.10)
    strong_syms = sym_df[sym_df["avg_r+slip"] > 0.10]["Simbolo"].tolist()
    df_opt = df_post[df_post["symbol"].isin(strong_syms)].copy()
    print(f"\n  [Config A — Solo simboli forti (avg_r>+0.10): {len(strong_syms)} sym]")
    s_opt = stats_row(df_opt)
    print(f"  N={s_opt['n']:,}  avg_r_slip={s_opt['avg_r']:+.3f}  WR={s_opt['wr']:.1f}%")

    # Config B: regime bear only per simboli short-friendly
    df_bear_ok = df_post[
        (df_post["direction"]=="bearish") &
        (df_post["regime"].isin(["neutral","bear"]))
    ]
    df_bull_ok = df_post[
        (df_post["direction"]=="bullish") &
        (df_post["regime"].isin(["neutral","bull"]))
    ]
    print(f"\n  [Regime breakdown post-fix]")
    sb = stats_row(df_bull_ok); sbear = stats_row(df_bear_ok)
    print(f"  Bullish in bull/neutral: N={sb['n']:,} avg_r={sb['avg_r']:+.3f} WR={sb['wr']:.1f}%")
    print(f"  Bearish in bear/neutral: N={sbear['n']:,} avg_r={sbear['avg_r']:+.3f} WR={sbear['wr']:.1f}%")

    # Ore migliori
    best_hours = hr_df[hr_df["avg_r+slip"] > 0]["Ora_ET"].tolist()
    df_best_hr = df_post[df_post["hour_et"].isin(best_hours)].copy()
    print(f"\n  [Ore positive: {best_hours}]")
    sb_hr = stats_row(df_best_hr)
    print(f"  N={sb_hr['n']:,}  avg_r_slip={sb_hr['avg_r']:+.3f}  WR={sb_hr['wr']:.1f}%")

    # Risk_pct >= 0.75 (filtro più stretto)
    df_risk75 = df_post[df_post["risk_pct"] >= 0.75].copy()
    print(f"\n  [risk_pct >= 0.75%: {len(df_risk75):,} trade]")
    s75 = stats_row(df_risk75)
    print(f"  avg_r_slip={s75['avg_r']:+.3f}  WR={s75['wr']:.1f}%")

    # ── Monte Carlo 5m ottimizzato ────────────────────────────────────────────
    # Usa la distribuzione post-fix di tutti i trade (la base più conservativa)
    r_dist_5m    = df_post["pnl_r_slip"].values
    raw_freq_5m  = len(df_post) / (df_post["pts"].dt.to_period("M").nunique())
    eff_freq_5m  = min(raw_freq_5m, SLOTS_5M * TRADING_DAYS)
    print(f"\n  Frequenza 5m: raw={raw_freq_5m:.0f}/mese → slot-cap={eff_freq_5m:.0f}/mese")

    # Carica 1h per combo
    try:
        df_1h = pd.read_csv(os.path.join(DATA_DIR, "val_1h_production.csv"))
        yf_1h = df_1h[df_1h["provider"]=="yahoo_finance"].copy()
        yf_1h["pnl_r_slip"] = yf_1h["pnl_r"] - ENTRY_SLIP_R / yf_1h["risk_pct"].clip(lower=0.01)
        yf_1h["pnl_r_slip"] -= np.where(yf_1h["outcome"]=="stop", SLIP_PCT / yf_1h["risk_pct"].clip(lower=0.01), 0.0)
        pts_1h = pd.to_datetime(yf_1h["pattern_timestamp"], utc=True)
        yf_1h["regime"] = pts_1h.apply(lambda t: get_regime(spy, t))
        yf_1h["regime_ok"] = yf_1h.apply(lambda r: regime_ok(r["regime"], r["direction"]), axis=1)
        yf_1h_f = yf_1h[yf_1h["regime_ok"] & (yf_1h["risk_pct"] >= 0.30)].copy()
        r_dist_1h = yf_1h_f["pnl_r_slip"].values
        raw_freq_1h = len(yf_1h_f) / (pts_1h.dt.to_period("M").nunique())
        eff_freq_1h = min(raw_freq_1h, SLOTS_1H * TRADING_DAYS)
        print(f"  Frequenza 1h: raw={raw_freq_1h:.0f}/mese → slot-cap={eff_freq_1h:.0f}/mese")
        has_1h = True
    except Exception as e:
        print(f"  WARN 1h non caricato: {e}")
        has_1h = False

    print()
    mc_5m = monte_carlo(r_dist_5m, eff_freq_5m, "5m base")
    print(f"  [5m base]  avg_r={mc_5m['avg_r']:+.3f} freq={eff_freq_5m:.0f}/mese  "
          f"mediana=€{mc_5m['median_eq']:,.0f} ({mc_5m['median_pct']:+.1f}%)  "
          f"worst5%={mc_5m['worst5_pct']:+.1f}%  ProbP={mc_5m['prob_prof']:.0f}%")

    # 5m con risk_pct >= 0.75
    r_dist_75 = df_risk75["pnl_r_slip"].values
    raw_75 = len(df_risk75) / (df_post["pts"].dt.to_period("M").nunique())
    eff_75 = min(raw_75, SLOTS_5M * TRADING_DAYS)
    mc_75 = monte_carlo(r_dist_75, eff_75, "5m risk>=0.75")
    print(f"  [5m r>=0.75] avg_r={mc_75['avg_r']:+.3f} freq={eff_75:.0f}/mese  "
          f"mediana=€{mc_75['median_eq']:,.0f} ({mc_75['median_pct']:+.1f}%)  "
          f"worst5%={mc_75['worst5_pct']:+.1f}%  ProbP={mc_75['prob_prof']:.0f}%")

    if has_1h:
        mc_1h = monte_carlo(r_dist_1h, eff_freq_1h, "1h")
        print(f"  [1h]       avg_r={mc_1h['avg_r']:+.3f} freq={eff_freq_1h:.0f}/mese  "
              f"mediana=€{mc_1h['median_eq']:,.0f} ({mc_1h['median_pct']:+.1f}%)  "
              f"worst5%={mc_1h['worst5_pct']:+.1f}%  ProbP={mc_1h['prob_prof']:.0f}%")

        # Combo 3+2 slots
        r_combo = np.concatenate([r_dist_1h, r_dist_5m])
        eff_combo = eff_freq_1h + eff_freq_5m
        mc_combo = monte_carlo(r_combo, eff_combo, "combo 3+2")
        print(f"  [combo 3+2] avg_r={mc_combo['avg_r']:+.3f} freq={eff_combo:.0f}/mese  "
              f"mediana=€{mc_combo['median_eq']:,.0f} ({mc_combo['median_pct']:+.1f}%)  "
              f"worst5%={mc_combo['worst5_pct']:+.1f}%  ProbP={mc_combo['prob_prof']:.0f}%")

        # Combo con 5m risk>=0.75
        r_combo75 = np.concatenate([r_dist_1h, r_dist_75])
        eff_combo75 = eff_freq_1h + eff_75
        mc_combo75 = monte_carlo(r_combo75, eff_combo75, "combo 1h+5m_r>=0.75")
        print(f"  [combo r>=0.75] avg_r={mc_combo75['avg_r']:+.3f} freq={eff_combo75:.0f}/mese  "
              f"mediana=€{mc_combo75['median_eq']:,.0f} ({mc_combo75['median_pct']:+.1f}%)  "
              f"worst5%={mc_combo75['worst5_pct']:+.1f}%  ProbP={mc_combo75['prob_prof']:.0f}%")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
