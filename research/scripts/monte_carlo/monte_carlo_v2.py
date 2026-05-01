"""
Monte Carlo simulazione performance annuale - 3 configurazioni reali.
Dataset: data/val_1h_large_post_fix.csv
Capitale: 2500 EUR, rischio 1% per trade, 5000 simulazioni, 12 mesi.
"""

import numpy as np
import pandas as pd

# --- CONFIG -------------------------------------------------------------------
CSV_PATH = "data/val_1h_large_post_fix.csv"
INITIAL_CAPITAL = 2500.0
RISK_PCT = 0.01
N_SIMULATIONS = 5000
SEED = 42
TRADING_DAYS_YEAR = 252

ACTIVE_1H_PATTERNS = {
    "double_bottom",
    "double_top",
    "macd_divergence_bull",
    "macd_divergence_bear",
    "rsi_divergence_bull",
    "rsi_divergence_bear",
}

# Slippage realistico applicato al pool 1h
SLIPPAGE_1H = 0.15

# Scenario 2: 1h + Alpaca 5m
N_1H        = 346
N_ALPACA_5M = 800
ALPACA_MEAN = 0.36   # +0.51R OOS - 0.15R slippage
ALPACA_STD  = 1.5

# Scenario 3: aggiungi Binance 5m
N_BINANCE_5M = 150
BINANCE_MEAN = 0.40  # +0.55R proxy - 0.15R slippage
BINANCE_STD  = 1.5


# --- SIMULAZIONE --------------------------------------------------------------
def simulate_equity_paths(components, n_sims, seed):
    """
    components: lista di dict con chiavi:
      - 'pool': np.array | None   (se None, campiona da normale)
      - 'n': int                  (numero trade/anno per questo componente)
      - 'mean': float             (usato solo se pool is None)
      - 'std': float              (usato solo se pool is None)
    Restituisce matrice (n_sims, n_total+1) di equity composta.
    """
    rng = np.random.default_rng(seed)
    n_total = sum(c["n"] for c in components)

    draws = np.empty((n_sims, n_total), dtype=np.float64)
    col = 0
    for c in components:
        n = c["n"]
        if c["pool"] is not None:
            draws[:, col:col+n] = rng.choice(c["pool"], size=(n_sims, n), replace=True)
        else:
            draws[:, col:col+n] = rng.normal(c["mean"], c["std"], size=(n_sims, n))
        col += n

    # Shuffle ogni riga (ordine casuale dei trade) - vettorizzato
    rand_order = rng.random((n_sims, n_total))
    idx = np.argsort(rand_order, axis=1)
    draws = draws[np.arange(n_sims)[:, None], idx]

    multipliers = 1.0 + RISK_PCT * draws
    equity = np.cumprod(multipliers, axis=1) * INITIAL_CAPITAL
    init_col = np.full((n_sims, 1), INITIAL_CAPITAL)
    return np.hstack([init_col, equity])


def compute_max_drawdown(equity_paths):
    running_max = np.maximum.accumulate(equity_paths, axis=1)
    dd = (equity_paths - running_max) / running_max
    return -dd.min(axis=1) * 100.0


def run_scenario(label, components, n_sims, seed):
    paths = simulate_equity_paths(components, n_sims, seed)
    final = paths[:, -1]
    max_dd = compute_max_drawdown(paths)
    n_total = sum(c["n"] for c in components)
    return {
        "label":         label,
        "n_total":       n_total,
        "n_month":       n_total / 12.0,
        "n_day":         n_total / TRADING_DAYS_YEAR,
        "p50":           float(np.percentile(final, 50)),
        "p5":            float(np.percentile(final, 5)),
        "p95":           float(np.percentile(final, 95)),
        "pct_profit":    float((final > INITIAL_CAPITAL).mean() * 100.0),
        "pct_dd30":      float((max_dd > 30.0).mean() * 100.0),
        "median_maxdd":  float(np.median(max_dd)),
    }


def print_scenario(s):
    p50, p5, p95 = s["p50"], s["p5"], s["p95"]
    g50 = (p50 - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    g5  = (p5  - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    g95 = (p95 - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    profit_mese  = (p50 - INITIAL_CAPITAL) / 12.0
    profit_giorno = (p50 - INITIAL_CAPITAL) / TRADING_DAYS_YEAR

    SEP = "-" * 64
    print()
    print(SEP)
    print("  {}".format(s["label"]))
    print(SEP)
    print("  Trade/anno:    {:>6.0f}".format(s["n_total"]))
    print("  Trade/mese:    {:>6.1f}".format(s["n_month"]))
    print("  Trade/giorno:  {:>6.1f}".format(s["n_day"]))
    print()
    print("  Dopo 12 mesi (partenza EUR 2,500):")
    print("    Mediana:        EUR {:>7,.0f}  ({:+.1f}%)".format(p50, g50))
    print("    Worst case 5%:  EUR {:>7,.0f}  ({:+.1f}%)".format(p5,  g5))
    print("    Best case 95%:  EUR {:>7,.0f}  ({:+.1f}%)".format(p95, g95))
    print()
    print("  Profitto mediano MENSILE:     EUR {:>6,.0f}".format(profit_mese))
    print("  Profitto mediano GIORNALIERO: EUR {:>6,.0f}".format(profit_giorno))
    print()
    print("  Rischio:")
    print("    Probabilita' profitto:  {:>5.1f}%".format(s["pct_profit"]))
    print("    Probabilita' DD > 30%:  {:>5.1f}%".format(s["pct_dd30"]))
    print("    Max drawdown mediano:   {:>5.1f}%".format(s["median_maxdd"]))
    print(SEP)
    sign = "+" if g50 >= 0 else ""
    print("  Con EUR 2,500 nello {}, dopo 12 mesi il".format(s["label"]))
    print("  risultato piu' probabile e' EUR {:,.0f} ({}{:.1f}%).".format(p50, sign, g50))
    print(SEP)


# --- LOAD & PREP --------------------------------------------------------------
df = pd.read_csv(CSV_PATH, parse_dates=["pattern_timestamp"])
df_filled = df[df["entry_filled"] == True].copy()
df_1h = df_filled[df_filled["pattern_name"].isin(ACTIVE_1H_PATTERNS)].copy()

# Pool 1h con slippage applicato
pnl_1h_raw    = df_1h["pnl_r"].values
pnl_1h_adj    = pnl_1h_raw - SLIPPAGE_1H

SEP = "-" * 64
print()
print(SEP)
print("  MONTE CARLO v2 -- 3 CONFIGURAZIONI REALI")
print("  Capitale: EUR 2,500 | Rischio: 1%/trade | Sim: 5,000 | Seed: 42")
print(SEP)
print("  Dataset: {}".format(CSV_PATH))
print("  Filled totali:          {:,}".format(len(df_filled)))
print("  Pattern 1h attivi (6):  {:,}  (esclusi compression + engulfing)".format(len(df_1h)))
print("  Pool 1h pre-slippage:   avg_r = {:.4f}R  std = {:.4f}R".format(
    pnl_1h_raw.mean(), pnl_1h_raw.std()))
print("  Pool 1h post-slippage:  avg_r = {:.4f}R  std = {:.4f}R  (-0.15R/trade)".format(
    pnl_1h_adj.mean(), pnl_1h_adj.std()))
print(SEP)
print()
print("  Componenti sintetiche 5m:")
print("  Alpaca 5m: media={:.2f}R  std={:.1f}R  ({:d} trade/anno)".format(
    ALPACA_MEAN, ALPACA_STD, N_ALPACA_5M))
print("  Binance 5m: media={:.2f}R  std={:.1f}R  ({:d} trade/anno)".format(
    BINANCE_MEAN, BINANCE_STD, N_BINANCE_5M))
print()
print("  Calcolo 3 scenari x {:,} simulazioni...".format(N_SIMULATIONS))

# --- SCENARI ------------------------------------------------------------------

# Scenario 1: Solo 1h (346 trade/anno, slippage -0.15R)
s1_components = [
    {"pool": pnl_1h_adj, "n": N_1H, "mean": None, "std": None},
]

# Scenario 2: 1h + Alpaca 5m (346 + 800 = 1146 trade/anno)
s2_components = [
    {"pool": pnl_1h_adj, "n": N_1H,        "mean": None,        "std": None},
    {"pool": None,        "n": N_ALPACA_5M, "mean": ALPACA_MEAN, "std": ALPACA_STD},
]

# Scenario 3: 1h + Alpaca 5m + Binance 5m (346 + 800 + 150 = 1296 trade/anno)
s3_components = [
    {"pool": pnl_1h_adj, "n": N_1H,         "mean": None,         "std": None},
    {"pool": None,        "n": N_ALPACA_5M,  "mean": ALPACA_MEAN,  "std": ALPACA_STD},
    {"pool": None,        "n": N_BINANCE_5M, "mean": BINANCE_MEAN, "std": BINANCE_STD},
]

s1 = run_scenario("SCENARIO 1 -- Solo 1h attuale (baseline)", s1_components, N_SIMULATIONS, SEED)
s2 = run_scenario("SCENARIO 2 -- 1h + Alpaca 5m (slot condivisi)", s2_components, N_SIMULATIONS, SEED + 1)
s3 = run_scenario("SCENARIO 3 -- 1h + Alpaca 5m + Binance 5m", s3_components, N_SIMULATIONS, SEED + 2)

print_scenario(s1)
print_scenario(s2)
print_scenario(s3)

# --- CONFRONTO RAPIDO --------------------------------------------------------
print()
print(SEP)
print("  CONFRONTO RAPIDO (mediana 12 mesi)")
print(SEP)
print("  {:<40} {:>10} {:>10} {:>10}".format("Metrica", "SC1", "SC2", "SC3"))
print(SEP)

def row3(label, key, fmt="{:.0f}", suffix=""):
    vals = [s1[key], s2[key], s3[key]]
    cells = [fmt.format(v) + suffix for v in vals]
    print("  {:<40} {:>10} {:>10} {:>10}".format(label, *cells))

row3("Trade/anno",              "n_total",      "{:.0f}")
row3("Mediana finale (EUR)",    "p50",          "{:,.0f}")
row3("Worst 5% (EUR)",          "p5",           "{:,.0f}")
row3("Best 95% (EUR)",          "p95",          "{:,.0f}")
row3("Prob. profitto",          "pct_profit",   "{:.1f}", "%")
row3("Prob. DD > 30%",          "pct_dd30",     "{:.1f}", "%")
row3("Max DD mediano",          "median_maxdd", "{:.1f}", "%")
print(SEP)
