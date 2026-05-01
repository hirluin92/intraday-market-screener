"""
Monte Carlo simulazione performance annuale -- dataset post-fix val_1h_large_post_fix.csv
Autonomo: usa solo pandas e numpy, nessun import dal progetto.
"""

import numpy as np
import pandas as pd

# --- CONFIG -------------------------------------------------------------------
CSV_PATH = "data/val_1h_large_post_fix.csv"
INITIAL_CAPITAL = 2500.0
RISK_PCT = 0.01          # 1% del capitale corrente per trade
N_SIMULATIONS = 5000
SEED = 42

STRADA_A_PATTERNS = {
    "compression_to_expansion_transition",
    "rsi_momentum_continuation",
    "double_bottom",
    "double_top",
    "rsi_divergence_bull",
    "rsi_divergence_bear",
    "macd_divergence_bull",
    "macd_divergence_bear",
    "engulfing_bullish",
}

SLIPPAGE_EXTRA = 0.15    # Scenario 3: riduzione pnl_r per slippage realistico


# --- HELPERS ------------------------------------------------------------------
def simulate_equity_paths(pnl_r_pool, n_trades, n_sims, seed):
    """Bootstrap con replacement. Restituisce (n_sims, n_trades+1) di equity."""
    rng = np.random.default_rng(seed)
    draws = rng.choice(pnl_r_pool, size=(n_sims, n_trades), replace=True)
    multipliers = 1.0 + RISK_PCT * draws
    equity = np.cumprod(multipliers, axis=1) * INITIAL_CAPITAL
    init_col = np.full((n_sims, 1), INITIAL_CAPITAL)
    return np.hstack([init_col, equity])


def compute_max_drawdown(equity_paths):
    """Max drawdown % per ogni simulazione."""
    running_max = np.maximum.accumulate(equity_paths, axis=1)
    dd = (equity_paths - running_max) / running_max
    return -dd.min(axis=1) * 100.0


def scenario_stats(label, pnl_r_pool, n_trades, n_sims, seed):
    paths = simulate_equity_paths(pnl_r_pool, n_trades, n_sims, seed)
    final_equity = paths[:, -1]
    max_dd = compute_max_drawdown(paths)
    return {
        "label":        label,
        "n_sample":     len(pnl_r_pool),
        "n_trades_12m": n_trades,
        "avg_r":        float(np.mean(pnl_r_pool)),
        "median_r":     float(np.median(pnl_r_pool)),
        "final_p5":     float(np.percentile(final_equity, 5)),
        "final_p50":    float(np.percentile(final_equity, 50)),
        "final_p95":    float(np.percentile(final_equity, 95)),
        "pct_profit":   float((final_equity > INITIAL_CAPITAL).mean() * 100.0),
        "pct_dd30":     float((max_dd > 30.0).mean() * 100.0),
        "median_maxdd": float(np.median(max_dd)),
    }


# --- LOAD & PREP --------------------------------------------------------------
df = pd.read_csv(CSV_PATH, parse_dates=["pattern_timestamp"])
df_filled = df[df["entry_filled"] == True].copy()

ts_sorted = df_filled["pattern_timestamp"].sort_values()
dt_start = ts_sorted.iloc[0]
dt_end   = ts_sorted.iloc[-1]
n_months = (dt_end.year - dt_start.year) * 12 + (dt_end.month - dt_start.month)
n_months += (dt_end.day - dt_start.day) / 30.0
trades_per_month = len(df_filled) / n_months
n_trades_12m = round(trades_per_month * 12)

strada_a_mask = (
    df_filled["pattern_name"].isin(STRADA_A_PATTERNS) &
    (df_filled["final_score"] >= 45)
)
df_s2 = df_filled[strada_a_mask].copy()
n_months_s2 = n_months  # stesso periodo
n_trades_12m_s2 = round((len(df_s2) / n_months_s2) * 12)

pnl_s1 = df_filled["pnl_r"].values
pnl_s2 = df_s2["pnl_r"].values
pnl_s3 = pnl_s2 - SLIPPAGE_EXTRA


# --- SCENARI ------------------------------------------------------------------
print("Calcolo 3 scenari x 5000 simulazioni...")
s1 = scenario_stats("SC1 -- Tutti i trade post-fix",    pnl_s1, n_trades_12m,    N_SIMULATIONS, SEED)
s2 = scenario_stats("SC2 -- Solo Strada A (score>=45)", pnl_s2, n_trades_12m_s2, N_SIMULATIONS, SEED + 1)
s3 = scenario_stats("SC3 -- Strada A + slippage -0.15", pnl_s3, n_trades_12m_s2, N_SIMULATIONS, SEED + 2)


# --- OUTPUT -------------------------------------------------------------------
SEP = "-" * 72
W1, W2 = 37, 11

def row(label, key, fmt="{:.0f}", suffix=""):
    vals = [s[key] for s in (s1, s2, s3)]
    cells = [(fmt.format(v) + suffix) for v in vals]
    print("  {:<{w1}} {:>{w2}} {:>{w2}} {:>{w2}}".format(
        label, cells[0], cells[1], cells[2], w1=W1, w2=W2))

print()
print(SEP)
print("  MONTE CARLO -- PERFORMANCE ANNUALE (12 mesi, cap. 2500 EUR, 1% rischio)")
print(SEP)
print("  Dataset   : {}".format(CSV_PATH))
print("  Periodo   : {} -> {} ({:.1f} mesi)".format(dt_start.date(), dt_end.date(), n_months))
print("  Filled    : {:,}  |  Trade/mese: {:.1f}  |  Proiettati 12m: {}".format(
    len(df_filled), trades_per_month, n_trades_12m))
print(SEP)

header = "  {:<{w1}} {:>{w2}} {:>{w2}} {:>{w2}}".format(
    "Metrica", "SC1", "SC2", "SC3", w1=W1, w2=W2)
print(header)
print(SEP)

row("N trade nel campione",    "n_sample",    "{:.0f}")
row("N trade proiettati 12m",  "n_trades_12m","{:.0f}")
row("Avg R per trade",         "avg_r",        "{:.4f}", " R")
row("Median R per trade",      "median_r",     "{:.4f}", " R")

print(SEP)
print("  -- EQUITY FINALE (inizio: 2500 EUR) --")
row("  Mediana (50 pct)",      "final_p50",   "{:.0f}", " EUR")
row("  Worst   (5 pct)",       "final_p5",    "{:.0f}", " EUR")
row("  Best    (95 pct)",      "final_p95",   "{:.0f}", " EUR")

print(SEP)
print("  -- RISCHIO --")
row("  % simulazioni in profitto",   "pct_profit",   "{:.1f}", "%")
row("  % simulazioni con DD > 30%",  "pct_dd30",     "{:.1f}", "%")
row("  Max drawdown mediano",         "median_maxdd", "{:.1f}", "%")

print(SEP)

print()
print("  NOTE SCENARI:")
pct_same = len(df_s2) / len(df_filled) * 100
print("  SC1 vs SC2: il {:.0f}% dei filled trade e' gia' Strada A con score>=45,".format(pct_same))
print("  quindi il pool di SC2 e' identico a SC1 -- differenza e' solo nel seed.")
print("  SC3 sottrae 0.15R per trade come proxy di commissioni + slippage extra.")

# --- VERDETTO -----------------------------------------------------------------
med = s2["final_p50"]
p5  = s2["final_p5"]
p95 = s2["final_p95"]
prob = s2["pct_profit"]
dd   = s2["median_maxdd"]
gain_med = (med - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
gain_p5  = (p5  - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
gain_p95 = (p95 - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

print()
print(SEP)
print("  VERDETTO (Scenario 2 -- baseline operativo):")
print()
print("  Con 2500 EUR e 1% rischio per trade, dopo 12 mesi il risultato")
print("  piu' probabile e' un capitale di {:.0f} EUR ({:+.1f}%), con".format(med, gain_med))
print("  {:.0f}% di probabilita' di chiudere in profitto.".format(prob))
print("  Nel caso peggiore (5 pct) si scende a {:.0f} EUR ({:+.1f}%);".format(p5, gain_p5))
print("  nel caso migliore (95 pct) si sale a {:.0f} EUR ({:+.1f}%).".format(p95, gain_p95))
print("  Il drawdown massimo mediano atteso e' del {:.1f}%.".format(dd))
print(SEP)
