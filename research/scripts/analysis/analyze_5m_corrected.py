"""
Analisi completa post-fix: 5m e 1h con regime filter, MIN_RISK_PCT, slippage, Monte Carlo.
Run: python /app/data/analyze_5m_corrected.py
"""
import warnings
warnings.filterwarnings("ignore")
import os, sys, math
import pandas as pd
import numpy as np
from datetime import date, timedelta

DATA_DIR = "/app/data"
F_5M = os.path.join(DATA_DIR, "val_5m_expanded.csv")
F_1H = os.path.join(DATA_DIR, "val_1h_production.csv")

# ─── Parametri ───────────────────────────────────────────────────────────────
MIN_RISK_5M  = 0.50   # %
MIN_RISK_1H  = 0.30   # %
SLIP_PCT     = 0.05   # % del prezzo per slippage stop (fixed)
ENTRY_SLIP_R = 0.03   # R extra sull'entry (0.03/risk_pct)
CAPITAL      = 100_000.0
RISK_TRADE   = 1.0    # % del capitale
RISK_DOLLAR  = CAPITAL * RISK_TRADE / 100   # = $1,000 per trade
SLOTS_1H     = 3
SLOTS_5M     = 2
TRADING_DAYS = 21     # per mese
N_SIM        = 5_000
N_MONTHS     = 12
SEED         = 42

VALIDATED_5M = {"double_top","double_bottom","macd_divergence_bear","macd_divergence_bull"}
VALIDATED_1H = {
    "double_top","double_bottom","macd_divergence_bear","macd_divergence_bull",
    "rsi_divergence_bear","rsi_divergence_bull","engulfing_bullish",
}

# ─── SPY regime ──────────────────────────────────────────────────────────────
def load_spy_regime() -> dict:
    """Restituisce dict {date → regime_label (usando close T-1)}."""
    try:
        import psycopg2
        conn = psycopg2.connect(host="postgres",port=5432,
            dbname="intraday_market_screener",user="postgres",password="postgres")
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
            spy[r["d"]] = prev           # regime del giorno = chiusura T-1
            prev = classify(r["pct"])
        print(f"  SPY regime: {len(spy)} giorni, ultimo={max(spy.keys())}")
        cnt = pd.Series(spy.values()).value_counts()
        print(f"  Dist: {cnt.to_dict()}")
        return spy
    except Exception as e:
        print(f"  WARN SPY DB failed: {e} → neutral fallback")
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
    return True   # neutral: entrambi


# ─── Slippage ─────────────────────────────────────────────────────────────────
def add_slippage(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    r = df["risk_pct"].clip(lower=0.01)
    entry_slip = ENTRY_SLIP_R / r
    stop_slip  = np.where(df["outcome"] == "stop", SLIP_PCT / r, 0.0)
    df["pnl_r_slip"] = df["pnl_r"] - entry_slip - stop_slip
    return df


# ─── Stats ────────────────────────────────────────────────────────────────────
def stats(label: str, df: pd.DataFrame, col="pnl_r"):
    n = len(df)
    if n == 0:
        print(f"  {label}: N=0"); return
    oc = df["outcome"]
    wr = oc.isin(["tp1","tp2"]).mean()*100
    avg = df[col].mean()
    med = df[col].median()
    s   = df[col].std()
    stops = (oc=="stop").sum(); tp1=(oc=="tp1").sum(); tp2=(oc=="tp2").sum(); tmo=(oc=="timeout").sum()
    regime_d = df["regime"].value_counts().to_dict() if "regime" in df else {}
    print(f"  {label}: N={n:,}  WR={wr:.1f}%  avg_r={avg:+.3f}  med={med:+.3f}  σ={s:.3f}  "
          f"[stop={stops} tp1={tp1} tp2={tp2} tmo={tmo}]"
          + (f"  reg={regime_d}" if regime_d else ""))


# ─── Monte Carlo fixed-dollar ─────────────────────────────────────────────────
def monte_carlo(r_dist: np.ndarray, trades_month_effective: float, label: str,
                n_sim=N_SIM, n_months=N_MONTHS, seed=SEED,
                evict_r=0.10) -> dict:
    """
    Fixed-dollar risk (NON compounding, conservativo).
    Ogni trade rischia RISK_DOLLAR = $1,000 (fisso, non % dell'equity crescente).
    Il risultato è P&L cumulato, non equity composta.
    """
    rng = np.random.default_rng(seed)
    # r già include slippage, togliere eviction_r per TIF=DAY
    r_adj = r_dist - evict_r

    final_pnl = np.zeros(n_sim)
    monthly_pnl = np.zeros((n_sim, n_months))

    for sim in range(n_sim):
        cum = 0.0
        for m in range(n_months):
            n_t = rng.poisson(trades_month_effective)
            if n_t > 0:
                rs = rng.choice(r_adj, size=n_t, replace=True)
                monthly_gain = rs.sum() * RISK_DOLLAR
                cum += monthly_gain
            monthly_pnl[sim, m] = cum
        final_pnl[sim] = cum

    median_pnl = np.median(final_pnl)
    pct5_pnl   = np.percentile(final_pnl, 5)
    prob_prof  = (final_pnl > 0).mean() * 100

    # Max drawdown mediano sul path mediano
    med_path = np.median(monthly_pnl, axis=0)
    peak = np.maximum.accumulate(np.concatenate([[0], med_path]))
    dd_abs = (med_path - peak[1:]).min()
    dd_pct = dd_abs / CAPITAL * 100

    median_pct = median_pnl / CAPITAL * 100
    worst5_pct = pct5_pnl  / CAPITAL * 100
    avg_r = float(r_adj.mean())

    print(f"  [{label}] avg_r={avg_r:+.3f}  trades/mese={trades_month_effective:.0f}  "
          f"mediana=€{CAPITAL+median_pnl:,.0f} ({median_pct:+.1f}%)  "
          f"worst5%={worst5_pct:+.1f}%  DD={dd_pct:.1f}%  ProbP={prob_prof:.0f}%")

    return {
        "label": label, "avg_r": avg_r,
        "trades_month": trades_month_effective,
        "median_eq": CAPITAL + median_pnl,
        "median_pct": median_pct,
        "worst5_pct": worst5_pct,
        "dd_pct": dd_pct,
        "prob_prof": prob_prof,
    }


# ─── Load & filter 5m ────────────────────────────────────────────────────────
def load_5m(spy: dict):
    print("\n" + "="*60)
    print("STEP 2 — 5m con tutti i fix")
    print("="*60)
    raw = pd.read_csv(F_5M)
    df  = raw[(raw["provider"]=="alpaca") & (raw["entry_filled"]==True)].copy()
    df["pts"] = pd.to_datetime(df["pattern_timestamp"], utc=True)
    df["hour_et"] = df["pts"].dt.tz_convert("America/New_York").dt.hour
    df = df[(df["hour_et"]>=11) & (df["hour_et"]<16)]
    df = df[df["pattern_name"].isin(VALIDATED_5M)]
    df = df[df["bars_to_entry"] <= 3]
    print(f"  Base 5m (pre-fix): {len(df):,} trade")

    # Regime
    df["regime"] = df["pts"].apply(lambda t: get_regime(spy, t))
    df["regime_ok"] = df.apply(lambda r: regime_ok(r["regime"], r["direction"]), axis=1)

    before = df.copy()
    before["pnl_r_slip"] = add_slippage(before)["pnl_r_slip"]

    df_r = df[df["regime_ok"]].copy()
    n_regime_cut = len(df) - len(df_r)
    df_f = df_r[df_r["risk_pct"] >= MIN_RISK_5M].copy()
    n_risk_cut = len(df_r) - len(df_f)

    print(f"  Rimossi regime filter: {n_regime_cut:,}")
    print(f"  Rimossi risk_pct < 0.50%: {n_risk_cut:,}")
    print(f"  Rimasti post-fix: {len(df_f):,}")

    after = add_slippage(df_f)

    print("\n  --- PRIMA dei fix ---")
    stats("5m PRIMA", before, "pnl_r")
    stats("5m PRIMA+slip", before, "pnl_r_slip")
    print("\n  --- DOPO i fix ---")
    stats("5m DOPO", after, "pnl_r")
    stats("5m DOPO+slip", after, "pnl_r_slip")

    # Breakdown per pattern
    print("\n  Breakdown post-fix per pattern:")
    grp = after.groupby(["pattern_name","direction"]).agg(
        n=("pnl_r","count"), avg_r=("pnl_r","mean"),
        avg_r_s=("pnl_r_slip","mean"),
        wr=("outcome", lambda x: x.isin(["tp1","tp2"]).mean()*100)
    ).round(3)
    print(grp.to_string())

    # Breakdown per regime (dopo fix)
    print("\n  Regime distribution post-fix:")
    print(after["regime"].value_counts().to_string())

    # Frequenza slot-constrained
    after["ym"] = after["pts"].dt.to_period("M")
    raw_freq = after.groupby("ym").size().mean()
    eff_freq = min(raw_freq, SLOTS_5M * TRADING_DAYS)
    print(f"\n  Frequenza raw: {raw_freq:.1f}/mese  slot-cap ({SLOTS_5M}×{TRADING_DAYS}): {eff_freq:.1f}/mese")

    return before, after, eff_freq


# ─── Load & filter 1h ────────────────────────────────────────────────────────
def load_1h(spy: dict):
    print("\n" + "="*60)
    print("STEP 3 — 1h verifica con fix")
    print("="*60)
    raw = pd.read_csv(F_1H)
    df  = raw[raw["entry_filled"]==True].copy()
    df["pts"] = pd.to_datetime(df["pattern_timestamp"], utc=True)
    df = df[df["pattern_name"].isin(VALIDATED_1H)]
    print(f"  Base 1h (pre-fix): {len(df):,} trade")

    df["regime"] = df["pts"].apply(lambda t: get_regime(spy, t))
    df["regime_ok"] = df.apply(lambda r: regime_ok(r["regime"], r["direction"]), axis=1)

    before = df.copy()
    before["pnl_r_slip"] = add_slippage(before)["pnl_r_slip"]

    df_r = df[df["regime_ok"]].copy()
    df_f = df_r[df_r["risk_pct"] >= MIN_RISK_1H].copy()
    after = add_slippage(df_f)

    n_regime_cut = len(df) - len(df_r)
    n_risk_cut   = len(df_r) - len(df_f)
    print(f"  Rimossi regime filter: {n_regime_cut:,}")
    print(f"  Rimossi risk_pct < 0.30%: {n_risk_cut:,}")
    print(f"  Rimasti post-fix: {len(df_f):,}")

    print("\n  --- PRIMA dei fix ---")
    stats("1h PRIMA", before, "pnl_r")
    stats("1h PRIMA+slip", before, "pnl_r_slip")
    print("\n  --- DOPO i fix ---")
    stats("1h DOPO", after, "pnl_r")
    stats("1h DOPO+slip", after, "pnl_r_slip")

    # Frequenza
    after["ym"] = after["pts"].dt.to_period("M")
    raw_freq = after.groupby("ym").size().mean()
    eff_freq = min(raw_freq, SLOTS_1H * TRADING_DAYS)
    print(f"\n  Frequenza raw: {raw_freq:.1f}/mese  slot-cap ({SLOTS_1H}×{TRADING_DAYS}): {eff_freq:.1f}/mese")

    return before, after, eff_freq


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("ANALISI COMPLETA POST-FIX  |  capital=€100K  risk=1%/trade")
    print("=" * 60)

    spy = load_spy_regime()

    before_5m, after_5m, freq_5m = load_5m(spy)
    before_1h, after_1h, freq_1h = load_1h(spy)

    # ── Tabella comparativa PRIMA/DOPO ───────────────────────────────────────
    print("\n" + "="*60)
    print("TABELLA STEP 2+3: PRIMA vs DOPO fix")
    print("="*60)
    print(f"  {'Metrica':<30} | {'5m PRIMA':>10} | {'5m DOPO':>10} | {'1h PRIMA':>10} | {'1h DOPO':>10}")
    print(f"  {'-'*30}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")

    def fmt(s, col): return f"{s[col].mean():+.3f}" if len(s)>0 else "N/A"
    def fmtwr(s): return f"{s['outcome'].isin(['tp1','tp2']).mean()*100:.1f}%"
    def fmtn(s): return f"{len(s):,}"

    before_5m_s = add_slippage(before_5m)
    before_1h_s = add_slippage(before_1h)

    rows = [
        ("n_trade", fmtn(before_5m), fmtn(after_5m), fmtn(before_1h), fmtn(after_1h)),
        ("avg_r (backtest)", fmt(before_5m,"pnl_r"), fmt(after_5m,"pnl_r"), fmt(before_1h,"pnl_r"), fmt(after_1h,"pnl_r")),
        ("avg_r + slippage", fmt(before_5m_s,"pnl_r_slip"), fmt(after_5m,"pnl_r_slip"), fmt(before_1h_s,"pnl_r_slip"), fmt(after_1h,"pnl_r_slip")),
        ("WR", fmtwr(before_5m), fmtwr(after_5m), fmtwr(before_1h), fmtwr(after_1h)),
    ]
    for label, b5, a5, b1, a1 in rows:
        print(f"  {label:<30} | {b5:>10} | {a5:>10} | {b1:>10} | {a1:>10}")

    # ── STEP 4: Monte Carlo ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("STEP 4 — MONTE CARLO DEFINITIVO POST-FIX")
    print(f"  {N_SIM} sim × {N_MONTHS} mesi  |  Fixed dollar risk=${RISK_DOLLAR:.0f}/trade")
    print(f"  Slot: {SLOTS_1H} 1h + {SLOTS_5M} 5m  |  Eviction TIF=DAY: -0.10R")
    print(f"  Frequenza effettiva: 1h={freq_1h:.0f}/mese  5m={freq_5m:.0f}/mese")
    print("="*60)

    r_1h  = after_1h["pnl_r_slip"].values
    r_5m  = after_5m["pnl_r_slip"].values

    print("\n  --- Solo 1h ---")
    res_1h = monte_carlo(r_1h, freq_1h, "Solo 1h")

    print("\n  --- Solo 5m CORRETTO ---")
    res_5m = monte_carlo(r_5m, freq_5m, "Solo 5m")

    # Combinato: pool pesato + frequenza sommata (capped)
    freq_combo = min(freq_1h + freq_5m, (SLOTS_1H + SLOTS_5M) * TRADING_DAYS)
    w1 = freq_1h / (freq_1h + freq_5m)
    w5 = freq_5m / (freq_1h + freq_5m)
    rng0 = np.random.default_rng(SEED)
    n_combo = 20_000
    r_combo = np.concatenate([
        rng0.choice(r_1h, size=int(n_combo*w1), replace=True),
        rng0.choice(r_5m, size=int(n_combo*w5), replace=True),
    ])
    print("\n  --- Combinato E+ (3+2 slot) ---")
    res_combo = monte_carlo(r_combo, freq_combo, "Combinato E+")

    # ── Edge degradation ─────────────────────────────────────────────────────
    print("\n  --- Edge degradation Combinato E+ ---")
    deg_res = []
    for edge in [1.0, 0.75, 0.50, 0.25]:
        avg_r = float(r_combo.mean())
        r_deg = r_combo - avg_r * (1 - edge)
        res = monte_carlo(r_deg, freq_combo, f"E+ {edge:.0%}", evict_r=0.0)
        res["edge"] = edge
        deg_res.append(res)

    # ── Tabella riassuntiva ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("TABELLA STEP 4: MONTE CARLO RIASSUNTO")
    print("="*60)
    hdr = f"  {'Scenario':<22}|{'Trade/anno':>11}|{'avg_r netto':>11}|{'Mediana 12m':>12}|{'Worst 5%':>9}|{'DD':>6}|{'ProbP':>6}"
    print(hdr)
    print("  " + "-"*22 + "+" + "-"*11 + "+" + "-"*11 + "+" + "-"*12 + "+" + "-"*9 + "+" + "-"*6 + "+" + "-"*6)
    for res in [res_1h, res_5m, res_combo]:
        print(f"  {res['label']:<22}|{res['trades_month']*12:>11.0f}|"
              f"{res['avg_r']:>+11.3f}|"
              f"  €{res['median_eq']:>8,.0f}|"
              f"{res['median_pct']:>+8.1f}%|"
              f"{res['dd_pct']:>+5.1f}%|"
              f"{res['prob_prof']:>5.0f}%")

    print(f"\n  {'Edge':<8}|{'avg_r':>11}|{'Mediana 12m':>12}|{'Worst 5%':>9}|{'ProbP':>6}")
    print("  " + "-"*8 + "+" + "-"*11 + "+" + "-"*12 + "+" + "-"*9 + "+" + "-"*6)
    for res in deg_res:
        print(f"  {res['edge']:<8.0%}|{res['avg_r']:>+11.3f}|"
              f"  €{res['median_eq']:>8,.0f}|"
              f"{res['median_pct']:>+8.1f}%|"
              f"{res['prob_prof']:>5.0f}%")

    # ── Confronto MC precedente ──────────────────────────────────────────────
    print("\n" + "="*60)
    print("CONFRONTO MC PRECEDENTE (INVALIDO) vs CORRETTO")
    print("="*60)
    print(f"  {'Metrica':<28}| {'MC invalido':>12} | {'MC corretto':>12} | {'Delta':>10}")
    print(f"  {'-'*28}+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    diffs = [
        ("5m avg_r (slippage incl.)",  "+0.510R",   f"{after_5m['pnl_r_slip'].mean():+.3f}R",  f"{after_5m['pnl_r_slip'].mean()-0.510:+.3f}R"),
        ("5m trade/anno",              "433",        f"{freq_5m*12:.0f}",                        f"{freq_5m*12-433:+.0f}"),
        ("1h avg_r (slippage incl.)",  "~+0.95R",   f"{after_1h['pnl_r_slip'].mean():+.3f}R",  "≈0"),
        ("Combo mediana 12m",          "€2,900K",    f"€{res_combo['median_eq']:,.0f}",          "─"),
        ("Combo ProbP",                "100%",       f"{res_combo['prob_prof']:.0f}%",            "─"),
    ]
    for label, old, new, delta in diffs:
        print(f"  {label:<28}| {old:>12} | {new:>12} | {delta:>10}")

    print("\n=== NOTE INTERPRETATIVE ===")
    print(f"  Slippage model: entry={ENTRY_SLIP_R}% / risk_pct  +  stop_miss={SLIP_PCT}% / risk_pct")
    print(f"  MC fixed-dollar: rischio fisso ${RISK_DOLLAR:.0f}/trade (non compounding).")
    print(f"  Slot constraint: max {SLOTS_1H}×{TRADING_DAYS}={SLOTS_1H*TRADING_DAYS} 1h-trade/mese, max {SLOTS_5M}×{TRADING_DAYS}={SLOTS_5M*TRADING_DAYS} 5m-trade/mese.")
    print(f"  Regime: bull→solo long, bear→solo short, neutral→entrambi (SPY 1d EMA50 ±2%).")
    print(f"  Eviction -0.10R: costo EOD close (TIF=DAY).")
    print(f"  Il 5m dataset non contiene regime col → regime calcolato da SPY 1d DB.")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
