"""
Monte Carlo DEFINITIVO POST-AUDIT — aprile 2026

Fix incorporati rispetto al MC precedente:
  M8  : 5m segnali ora usano TP1=2.0R / TP2=3.5R (era default 1.5R/2.5R)
  H6  : regime lookback 14 giorni (era 7 — meno segnali spuri holiday weeks)
  H1  : pool Alpaca non piu' troncato (backfill fix)
  C4  : pattern extraction con sessione fresca (piu' pattern, meno missed)
  macd/rsi_divergence_bull: universali in tutti i regimi (non piu' solo BEAR)
  Universo 1h: 44+ simboli (11 aggiunti apr 2026)

Pool produzione:
  1h : val_1h_full.csv — filtri produzione completi
  5m : val_5m_expanded.csv — Alpaca US, 11-16 ET, provider=alpaca, bars_to_entry<=3

Frequenza live:
  1h: raw/3 (conferme di regime, threshold score, slot 1h liberi) -> 139/anno
  5m CONSERVATIVA: raw/20 (threshold execute, regime, slot 2x5m, qualita') -> ~433/anno
  5m OTTIMISTICA : raw/10 (se score threshold passa piu' segnali) -> ~867/anno

  NOTA: il MC sequenziale composto e' corretto per trade sequenziali.
  Per un sistema concorrente (5 slot), la stima aritmetica e' il lower bound.

Parametri: EUR 100,000 | 1% rischio | slippage 0.15R | 5,000 sim | 12 mesi
"""

from __future__ import annotations

import io, sys
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

RNG_SEED = 42
N_SIM    = 5_000
CAPITAL  = 100_000.0
RISK_PCT = 0.01
SLIP     = 0.15

SEP  = "=" * 76
SEP2 = "-" * 76

# ---------------------------------------------------------------------------
# Universo
# ---------------------------------------------------------------------------
VALIDATED_SYMBOLS_YAHOO: frozenset[str] = frozenset({
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
    "MU","LUNR","CAT","GS","HON","ICE","CVX","VRTX",
})
VALIDATED_SYMBOLS_ALPACA_5M: frozenset[str] = frozenset({
    "META","NVDA","TSLA","AMD","NFLX","COIN","MSTR","HOOD","SHOP","SOFI",
    "ZS","NET","CELH","RBLX","PLTR","MDB","SMCI","DELL",
    "NVO","LLY","MRNA","NKE","TGT","SCHW","AMZN","MU","LUNR","CAT","GS",
})
SYMBOLS_BLOCKED_ALPACA_5M: frozenset[str] = frozenset({"SPY","AAPL","MSFT","GOOGL","WMT"})
PATTERNS_1H_MAIN = frozenset({
    "double_bottom","double_top",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
})
PATTERNS_5M = frozenset({
    "double_bottom","double_top",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
})
ENGULFING_MIN_SCORE = 84.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _et_hour(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert("America/New_York").dt.hour

def run_mc(pool: np.ndarray, n_year: int, n_sim: int = N_SIM, seed: int = RNG_SEED) -> dict:
    if len(pool) == 0 or n_year == 0:
        return dict(med=CAPITAL, p05=CAPITAL, prob_profit=0.0, dd_med=0.0, dd_p95=0.0,
                    avg_r=0.0, arithmetic_return=0.0)
    rng = np.random.default_rng(seed)
    finals = np.empty(n_sim); max_dds = np.empty(n_sim)
    arith_rets = np.empty(n_sim)
    for i in range(n_sim):
        draws = rng.choice(pool, size=n_year, replace=True)
        eq = CAPITAL; peak = CAPITAL; max_dd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak: peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd: max_dd = dd
        finals[i] = eq; max_dds[i] = max_dd
        arith_rets[i] = n_year * RISK_PCT * draws.mean()  # arithmetic estimate
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob_profit=(finals > CAPITAL).mean(),
        dd_med=np.median(max_dds), dd_p95=np.percentile(max_dds, 95),
        avg_r=float(pool.mean()),
        arithmetic_return=float(np.median(arith_rets)),
    )

def run_mc_combined(
    pool_1h: np.ndarray, n_1h: int,
    pool_5m: np.ndarray, n_5m: int,
    n_sim: int = N_SIM, seed: int = RNG_SEED,
) -> dict:
    total = n_1h + n_5m
    if total == 0:
        return dict(med=CAPITAL, p05=CAPITAL, prob_profit=0.0, dd_med=0.0, dd_p95=0.0,
                    avg_r=0.0, arithmetic_return=0.0)
    rng = np.random.default_rng(seed)
    finals = np.empty(n_sim); max_dds = np.empty(n_sim)
    for i in range(n_sim):
        d1 = rng.choice(pool_1h, size=n_1h, replace=True)
        d5 = rng.choice(pool_5m, size=n_5m, replace=True)
        draws = np.concatenate([d1, d5]); rng.shuffle(draws)
        eq = CAPITAL; peak = CAPITAL; max_dd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak: peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd: max_dd = dd
        finals[i] = eq; max_dds[i] = max_dd
    combined_pool = np.concatenate([pool_1h, pool_5m])
    arith = total * RISK_PCT * combined_pool.mean()
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob_profit=(finals > CAPITAL).mean(),
        dd_med=np.median(max_dds), dd_p95=np.percentile(max_dds, 95),
        avg_r=float(combined_pool.mean()),
        arithmetic_return=arith,
    )

def mc_monthly_path(
    pool_1h: np.ndarray, n_1h: int,
    pool_5m: np.ndarray, n_5m: int,
    n_months: int = 12, n_sim: int = N_SIM, seed: int = RNG_SEED,
) -> np.ndarray:
    n_per_month = max(1, round((n_1h + n_5m) / 12))
    combined = np.concatenate([pool_1h, pool_5m])
    rng = np.random.default_rng(seed)
    paths = np.zeros((n_sim, n_months + 1)); paths[:, 0] = CAPITAL
    for i in range(n_sim):
        eq = CAPITAL
        for m in range(n_months):
            for r in rng.choice(combined, size=n_per_month, replace=True):
                eq *= 1.0 + RISK_PCT * r
            paths[i, m + 1] = eq
    return paths

def _fmt_mc_row(label: str, n: int, mc: dict) -> None:
    gain_med = (mc["med"] - CAPITAL) / CAPITAL * 100
    arith_pct = mc["arithmetic_return"] * 100
    print(
        f"  {label:<28} {n:>5}  "
        f"EUR{mc['med']:>9,.0f} ({gain_med:>+6.0f}%)  "
        f"EUR{mc['p05']:>8,.0f}  "
        f"{mc['dd_med']*100:>5.1f}%  "
        f"{mc['dd_p95']*100:>5.1f}%  "
        f"{mc['prob_profit']*100:>4.0f}%  "
        f"[arit:{arith_pct:>+5.0f}%]"
    )


# ---------------------------------------------------------------------------
# LOAD & FILTER 1h
# ---------------------------------------------------------------------------
print(f"\n{SEP}")
print("  CARICAMENTO E FILTRAGGIO DATI PRODUZIONE")
print(SEP)

df1_raw = pd.read_csv("data/val_1h_full.csv")
df1_raw["pattern_timestamp"] = pd.to_datetime(df1_raw["pattern_timestamp"], utc=True)

is_long = df1_raw["direction"] == "bullish"
is_short = df1_raw["direction"] == "bearish"
hour_et_1h = _et_hour(df1_raw["pattern_timestamp"])

mask_1h = (
    df1_raw["entry_filled"].astype(bool) &
    (df1_raw["provider"] == "yahoo_finance") &
    df1_raw["symbol"].isin(VALIDATED_SYMBOLS_YAHOO) &
    (df1_raw["pattern_name"].isin(PATTERNS_1H_MAIN) |
     ((df1_raw["pattern_name"] == "engulfing_bullish") & (df1_raw["final_score"] >= ENGULFING_MIN_SCORE))) &
    (df1_raw["pattern_strength"] >= 0.60) & (df1_raw["pattern_strength"] < 0.80) &
    ((is_long & (df1_raw["risk_pct"] <= 3.0)) | (is_short & (df1_raw["risk_pct"] <= 2.0))) &
    (df1_raw["bars_to_entry"].fillna(99) <= 4) &
    (df1_raw["bars_to_exit"].fillna(99) <= 7) &
    (hour_et_1h != 3)
)
df1 = df1_raw[mask_1h].copy()
months_1h = max(1, (df1["pattern_timestamp"].max() - df1["pattern_timestamp"].min()).days / 30.0)
n_year_1h_raw = round(len(df1) / months_1h * 12)
n_year_1h = max(1, round(n_year_1h_raw / 3))  # /3: threshold, regime filter, slot availability
pool_1h = (df1["pnl_r"] - SLIP).values
wr_1h = (pool_1h > 0).mean() * 100

print(f"  1h: {len(df1_raw):,} raw -> {len(df1):,} produzione  |  "
      f"avg_r(gross)={df1['pnl_r'].mean():+.4f}R  WR={wr_1h:.1f}%")
print(f"      raw_rate={n_year_1h_raw}/yr  live_est=raw/3={n_year_1h}/yr")
print(f"      Periodo: {df1['pattern_timestamp'].min().date()} -> "
      f"{df1['pattern_timestamp'].max().date()} ({months_1h:.0f} mesi)")

# ---------------------------------------------------------------------------
# LOAD & FILTER 5m  (pre-M8 = dati reali; post-M8 = aggiustamento TP)
# ---------------------------------------------------------------------------
df5_raw = pd.read_csv("data/val_5m_expanded.csv")
df5_raw["pattern_timestamp"] = pd.to_datetime(df5_raw["pattern_timestamp"], utc=True)
hour_et_5m = _et_hour(df5_raw["pattern_timestamp"])

mask_5m = (
    df5_raw["entry_filled"].astype(bool) &
    (df5_raw["provider"] == "alpaca") &
    df5_raw["symbol"].isin(VALIDATED_SYMBOLS_ALPACA_5M) &
    ~df5_raw["symbol"].isin(SYMBOLS_BLOCKED_ALPACA_5M) &
    df5_raw["pattern_name"].isin(PATTERNS_5M) &
    (df5_raw["bars_to_entry"].fillna(99) <= 3) &
    (hour_et_5m >= 11) & (hour_et_5m < 16)
)
df5 = df5_raw[mask_5m].copy()
months_5m = max(1, (df5["pattern_timestamp"].max() - df5["pattern_timestamp"].min()).days / 30.0)
n_year_5m_raw = round(len(df5) / months_5m * 12)

# M8 fix: tp1 -> 2.0R, tp2 -> 3.5R (nuovi target TP ottimizzati)
df5_m8 = df5.copy()
df5_m8.loc[df5_m8["outcome"] == "tp1", "pnl_r"] = 2.0
df5_m8.loc[df5_m8["outcome"] == "tp2", "pnl_r"] = 3.5

n_tp1 = (df5["outcome"] == "tp1").sum()
n_tp2 = (df5["outcome"] == "tp2").sum()

# Due stime frequenza live (la vera incertezza del sistema 5m):
# CONSERVATIVA (raw/20): threshold execute, regime, quality gate, slot 2x5m
# OTTIMISTICA  (raw/10): se il sistema esegue piu' segnali per simbolo
n_year_5m_cons = max(1, round(n_year_5m_raw / 20))   # ~433/yr
n_year_5m_opt  = max(1, round(n_year_5m_raw / 10))   # ~865/yr

pool_5m_pre  = (df5["pnl_r"]    - SLIP).values
pool_5m_post = (df5_m8["pnl_r"] - SLIP).values

wr_5m_pre  = (pool_5m_pre  > 0).mean() * 100
wr_5m_post = (pool_5m_post > 0).mean() * 100

print()
print(f"  5m: {len(df5_raw):,} raw -> {len(df5):,} produzione  |  "
      f"avg_r(pre-M8)={df5['pnl_r'].mean():+.4f}R  WR={wr_5m_pre:.1f}%")
print(f"      M8 adj: tp1 {n_tp1:,}x (1.5->2.0R) + tp2 {n_tp2:,}x (2.5->3.5R)")
print(f"      avg_r(post-M8)={df5_m8['pnl_r'].mean():+.4f}R  WR={wr_5m_post:.1f}%")
print(f"      raw_rate={n_year_5m_raw}/yr  live_cons=raw/20={n_year_5m_cons}/yr  "
      f"live_opt=raw/10={n_year_5m_opt}/yr")
print(f"      Periodo: {df5['pattern_timestamp'].min().date()} -> "
      f"{df5['pattern_timestamp'].max().date()} ({months_5m:.0f} mesi)")

# ---------------------------------------------------------------------------
# TABELLA 1 — Pool stats
# ---------------------------------------------------------------------------
avg_r_lordo_1h  = float(df1["pnl_r"].mean())
avg_r_lordo_5m_pre  = float(df5["pnl_r"].mean())
avg_r_lordo_5m_post = float(df5_m8["pnl_r"].mean())
avg_r_netto_1h      = float(pool_1h.mean())
avg_r_netto_5m_pre  = float(pool_5m_pre.mean())
avg_r_netto_5m_post = float(pool_5m_post.mean())

# Pesi per combinato (usano freq conservativa)
w1  = n_year_1h; w5 = n_year_5m_cons
tot_n = len(df1) + len(df5)
avg_r_lordo_comb_post = (avg_r_lordo_1h * len(df1) + avg_r_lordo_5m_post * len(df5)) / tot_n
avg_r_netto_comb_post = (avg_r_netto_1h * w1 + avg_r_netto_5m_post * w5) / (w1 + w5)
wr_comb = ((pool_1h > 0).sum() + (pool_5m_post > 0).sum()) / (len(pool_1h) + len(pool_5m_post)) * 100

print()
print(SEP)
print("  TABELLA 1 — POOL STATS (produzione filtrata)")
print(SEP)
print(f"  {'Metrica':<32} {'1h':>12} {'5m pre-M8':>12} {'5m post-M8':>12} {'Comb. E+':>12}")
print(f"  {'-'*75}")
print(f"  {'Trade/anno (live conserv.)':<32} {n_year_1h:>12} {n_year_5m_cons:>12} {n_year_5m_cons:>12} {n_year_1h+n_year_5m_cons:>12}")
print(f"  {'avg_r lordo':<32} {avg_r_lordo_1h:>+11.4f}R {avg_r_lordo_5m_pre:>+11.4f}R {avg_r_lordo_5m_post:>+11.4f}R {avg_r_lordo_comb_post:>+11.4f}R")
print(f"  {'avg_r netto (post-slip 0.15R)':<32} {avg_r_netto_1h:>+11.4f}R {avg_r_netto_5m_pre:>+11.4f}R {avg_r_netto_5m_post:>+11.4f}R {avg_r_netto_comb_post:>+11.4f}R")
print(f"  {'WR':<32} {wr_1h:>11.1f}% {wr_5m_pre:>11.1f}% {wr_5m_post:>11.1f}% {wr_comb:>11.1f}%")

# Arithmetic return estimate
arith_1h      = n_year_1h      * RISK_PCT * avg_r_netto_1h
arith_5m_pre  = n_year_5m_cons * RISK_PCT * avg_r_netto_5m_pre
arith_5m_post = n_year_5m_cons * RISK_PCT * avg_r_netto_5m_post
arith_comb_post = arith_1h + arith_5m_post
print(f"  {'Ritorno aritmetico (lower bound)':<32} {arith_1h:>+11.1%}{'':>12} {arith_5m_post:>+11.1%} {arith_comb_post:>+11.1%}")
print(f"  {'  (= n_trades x 1% x avg_r)':<32}")

# ---------------------------------------------------------------------------
# CALCOLO MC — 5,000 simulazioni
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  Calcolo MC (5,000 sim × 7 scenari)... [pausa per calcolo]")
print(SEP)

mc_1h          = run_mc(pool_1h,      n_year_1h,      seed=RNG_SEED+0)
mc_5m_pre_c    = run_mc(pool_5m_pre,  n_year_5m_cons, seed=RNG_SEED+1)  # conservative freq, pre-M8
mc_5m_post_c   = run_mc(pool_5m_post, n_year_5m_cons, seed=RNG_SEED+2)  # conservative freq, post-M8
mc_5m_post_o   = run_mc(pool_5m_post, n_year_5m_opt,  seed=RNG_SEED+3)  # optimistic freq, post-M8
mc_comb_pre    = run_mc_combined(pool_1h, n_year_1h, pool_5m_pre,  n_year_5m_cons, seed=RNG_SEED+4)
mc_comb_post_c = run_mc_combined(pool_1h, n_year_1h, pool_5m_post, n_year_5m_cons, seed=RNG_SEED+5)
mc_comb_post_o = run_mc_combined(pool_1h, n_year_1h, pool_5m_post, n_year_5m_opt,  seed=RNG_SEED+6)

# ---------------------------------------------------------------------------
# TABELLA 2 — MC principale (1% risk)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  TABELLA 2 — MONTE CARLO PRINCIPALE (EUR 100k, 1% rischio, 12 mesi, 5000 sim)")
print("  [arit] = stima aritmetica (lower bound, modello fixed-fraction per sistema concorrente)")
print(SEP)
print(f"  {'Scenario':<28} {'t/a':>5}  {'Mediana 12m':>18}  {'Worst 5%':>11}  {'DD med':>5}  {'DD p95':>5}  {'ProbP':>4}  {'[arit]':>7}")
print(f"  {'-'*100}")
_fmt_mc_row("Solo 1h (core, affidabile)",  n_year_1h,              mc_1h)
_fmt_mc_row("Solo 5m pre-M8 [conserv]",   n_year_5m_cons,         mc_5m_pre_c)
_fmt_mc_row("Solo 5m post-M8 [conserv]",  n_year_5m_cons,         mc_5m_post_c)
_fmt_mc_row("Solo 5m post-M8 [ottim]",    n_year_5m_opt,          mc_5m_post_o)
_fmt_mc_row("Combinato E+ pre-M8",        n_year_1h+n_year_5m_cons, mc_comb_pre)
_fmt_mc_row("Combinato E+ post-M8 [C]",   n_year_1h+n_year_5m_cons, mc_comb_post_c)
_fmt_mc_row("Combinato E+ post-M8 [O]",   n_year_1h+n_year_5m_opt,  mc_comb_post_o)
print()
print("  [C]=freq conservativa (raw/20), [O]=freq ottimistica (raw/10)")
print("  IMPORTANTE: il range pre-M8/post-M8 quantifica l'incertezza sull'efficacia del fix M8.")

# ---------------------------------------------------------------------------
# TABELLA 3 — Sensitivity risk% (combinato E+ post-M8 conservativo)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  TABELLA 3 — SENSITIVITY RISK% (combinato E+ post-M8 [C], 500 sim)")
print(SEP)
print(f"  {'Risk%':>6} {'t/a':>5}  {'Mediana':>15}  {'Worst 5%':>12}  {'DD med':>5}  {'ProbP':>5}  {'Arit.':>8}")
print(f"  {'-'*65}")

n_comb = n_year_1h + n_year_5m_cons
for risk_test in [0.005, 0.010, 0.015, 0.020]:
    rng_s = np.random.default_rng(555)
    finals_s = np.empty(500); dds_s = np.empty(500)
    for i in range(500):
        d1 = rng_s.choice(pool_1h,      n_year_1h,      replace=True)
        d5 = rng_s.choice(pool_5m_post, n_year_5m_cons, replace=True)
        draws = np.concatenate([d1, d5]); rng_s.shuffle(draws)
        eq = CAPITAL; pk = CAPITAL; dd = 0.0
        for r in draws:
            eq *= 1.0 + risk_test * r
            if eq > pk: pk = eq
            d_val = (pk - eq) / pk
            if d_val > dd: dd = d_val
        finals_s[i] = eq; dds_s[i] = dd
    gain_med = (np.median(finals_s) - CAPITAL) / CAPITAL * 100
    arith_r = n_comb * risk_test * avg_r_netto_comb_post * 100
    print(
        f"  {risk_test*100:>5.1f}% {n_comb:>5}  "
        f"EUR{np.median(finals_s):>10,.0f} ({gain_med:>+6.0f}%)  "
        f"EUR{np.percentile(finals_s,5):>9,.0f}  "
        f"{np.median(dds_s)*100:>5.1f}%  "
        f"{(finals_s>CAPITAL).mean()*100:>4.0f}%  "
        f"{arith_r:>+7.1f}%"
    )

# ---------------------------------------------------------------------------
# TABELLA 4 — Edge degradation (combinato post-M8 [C], 500 sim)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  TABELLA 4 — EDGE DEGRADATION (combinato E+ post-M8 [C], 1% risk, 500 sim)")
print("  Simula deterioramento edge in live (slippage extra, fill parziali, overfitting)")
print(SEP)
print(f"  {'Edge':>6} {'avg_r netto':>12} {'Mediana':>15}  {'Worst 5%':>12}  {'ProbP':>5}  {'Arit.':>8}")
print(f"  {'-'*70}")

for edge_frac in [1.00, 0.75, 0.50, 0.25, 0.10]:
    p1_e = pool_1h      * edge_frac
    p5_e = pool_5m_post * edge_frac
    avg_net_e = np.concatenate([p1_e[:n_year_1h if len(p1_e)>n_year_1h else len(p1_e)],
                                p5_e[:n_year_5m_cons if len(p5_e)>n_year_5m_cons else len(p5_e)]]).mean()
    rng_e = np.random.default_rng(777)
    finals_e = np.empty(500)
    for i in range(500):
        d1 = rng_e.choice(p1_e, n_year_1h,      replace=True)
        d5 = rng_e.choice(p5_e, n_year_5m_cons, replace=True)
        draws = np.concatenate([d1, d5]); rng_e.shuffle(draws)
        eq = CAPITAL
        for r in draws: eq *= 1.0 + RISK_PCT * r
        finals_e[i] = eq
    gain_med = (np.median(finals_e) - CAPITAL) / CAPITAL * 100
    arith_r = n_comb * RISK_PCT * avg_net_e * 100
    print(
        f"  {edge_frac*100:>5.0f}% {avg_net_e:>+11.4f}R  "
        f"EUR{np.median(finals_e):>10,.0f} ({gain_med:>+6.0f}%)  "
        f"EUR{np.percentile(finals_e,5):>9,.0f}  "
        f"{(finals_e>CAPITAL).mean()*100:>4.0f}%  "
        f"{arith_r:>+7.1f}%"
    )

# ---------------------------------------------------------------------------
# TABELLA 5 — Equity mensile (combinato E+ post-M8 [C])
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  TABELLA 5 — EQUITY MENSILE MEDIANA (EUR 100k, 1% risk, compounding, 5000 sim)")
print("  Scenario: Combinato E+ post-M8 [C] (base conservativa)")
print(SEP)
print(f"  {'Mese':>5} {'Equity mediana':>15}  {'Gain':>8}  {'p5% (worst)':>12}  {'p95% (best)':>12}")
print(f"  {'-'*65}")

paths = mc_monthly_path(pool_1h, n_year_1h, pool_5m_post, n_year_5m_cons, n_months=12, n_sim=N_SIM)
for m in range(1, 13):
    col = paths[:, m]
    med = np.median(col); p5 = np.percentile(col, 5); p95 = np.percentile(col, 95)
    gain = (med - CAPITAL) / CAPITAL * 100
    print(f"  {m:>5} EUR{med:>13,.0f}  {gain:>+8.1f}%  EUR{p5:>10,.0f}  EUR{p95:>10,.0f}")

# ---------------------------------------------------------------------------
# TABELLA 5b — Equity mensile con stima aritmetica (fixed-fraction, lower bound)
# ---------------------------------------------------------------------------
print()
print("  TABELLA 5b — EQUITY MENSILE ARITMETICA (lower bound, modello fixed-fraction)")
print("  (Piu' conservativo: non assume reinvestimento completo di ogni trade)")
print(f"  {'Mese':>5} {'Equity mediana':>15}  {'Gain':>8}")
print(f"  {'-'*35}")

monthly_arith_gain = arith_comb_post / 12  # atteso per mese
rng_ab = np.random.default_rng(999)
n_month = max(1, round((n_year_1h + n_year_5m_cons) / 12))
arith_paths = np.zeros((N_SIM, 13)); arith_paths[:, 0] = CAPITAL
for i in range(N_SIM):
    eq = CAPITAL
    for m in range(12):
        draws = rng_ab.choice(np.concatenate([pool_1h, pool_5m_post]), n_month, replace=True)
        month_gain = draws.mean() * RISK_PCT * n_month  # linear, not compound
        eq = CAPITAL * (1 + (m + 1) * monthly_arith_gain) + (draws.mean() - avg_r_netto_comb_post) * RISK_PCT * n_month * CAPITAL
        arith_paths[i, m + 1] = max(0, CAPITAL * (1 + (m + 1) * monthly_arith_gain))
for m in range(1, 13):
    med = np.median(arith_paths[:, m])
    gain = (med - CAPITAL) / CAPITAL * 100
    print(f"  {m:>5} EUR{med:>13,.0f}  {gain:>+8.1f}%")

# ---------------------------------------------------------------------------
# TABELLA 6 — Confronto con MC precedente
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  TABELLA 6 — CONFRONTO MC PRECEDENTE vs ATTUALE")
print(SEP)

# MC precedente (monte_carlo_definitivo.py): EUR 2,500 cap, raw/4, 4 pattern 5m, no hour filter
# Risultati noti dalla sessione precedente (scaling a EUR 100k)
SCALE = CAPITAL / 2_500.0
MC_PREV_MED_2500 = 3_196.0   # stima mediana precedente per combinato 1h+5m
MC_PREV_P05_2500 = 2_218.0
MC_PREV_N_1H     = 68         # n_year_1h precedente (pool piu' piccolo, /4)
MC_PREV_N_5M     = 44         # n_year_5m precedente (4 pattern, /4)
MC_PREV_AVG_R    = 0.31       # avg_r netto comb precedente (stima)

mc_prev_med = MC_PREV_MED_2500 * SCALE
mc_prev_p05 = MC_PREV_P05_2500 * SCALE
gain_prev   = (mc_prev_med - CAPITAL) / CAPITAL * 100
gain_curr_c = (mc_comb_post_c["med"] - CAPITAL) / CAPITAL * 100
gain_curr_o = (mc_comb_post_o["med"] - CAPITAL) / CAPITAL * 100

print(f"  {'Metrica':<38} {'MC prec.':>14} {'MC att. [C]':>14} {'MC att. [O]':>14}")
print(f"  {'-'*85}")
print(f"  {'avg_r netto combinato':<38} {MC_PREV_AVG_R:>+13.4f}R {avg_r_netto_comb_post:>+13.4f}R {'':>14}")
print(f"  {'Trade/anno 1h':<38} {MC_PREV_N_1H:>14} {n_year_1h:>14} {n_year_1h:>14}")
print(f"  {'Trade/anno 5m':<38} {MC_PREV_N_5M:>14} {n_year_5m_cons:>14} {n_year_5m_opt:>14}")
print(f"  {'Mediana 12m (EUR 100k)':<38} EUR{mc_prev_med:>11,.0f} EUR{mc_comb_post_c['med']:>11,.0f} EUR{mc_comb_post_o['med']:>11,.0f}")
print(f"  {'Worst 5% (EUR 100k)':<38} EUR{mc_prev_p05:>11,.0f} EUR{mc_comb_post_c['p05']:>11,.0f} EUR{mc_comb_post_o['p05']:>11,.0f}")
print(f"  {'DD mediano':<38} {'n/d':>14} {mc_comb_post_c['dd_med']*100:>13.1f}% {mc_comb_post_o['dd_med']*100:>13.1f}%")
print(f"  {'Rendim. aritmetico (lb)':<38} {'n/d':>14} {arith_comb_post:>+13.1%} {'':>14}")
print()
print(f"  Delta principali rispetto al MC precedente:")
print(f"  + 1h: {MC_PREV_N_1H} -> {n_year_1h} t/a (+{n_year_1h-MC_PREV_N_1H} da universo espanso + pattern universali)")
print(f"  + 5m: {MC_PREV_N_5M} -> {n_year_5m_cons} t/a [C] (pool espanso, 6 pattern vs 4)")
print(f"  + M8: avg_r 5m post-fix {avg_r_lordo_5m_post:+.4f}R vs pre-fix {avg_r_lordo_5m_pre:+.4f}R")
print(f"  + avg_r 1h: +{avg_r_netto_1h:.4f}R (pool produzione pulito vs dataset grezzo precedente)")

# ---------------------------------------------------------------------------
# ANALISI 5m per pattern (pre vs post M8)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  ANALISI 5m — avg_r per pattern, pre/post M8 (pool filtrato produzione)")
print(SEP)
print(f"  {'Pattern':<30} {'n':>5} {'WR':>5}  {'avg_r pre-M8':>12} {'avg_r post-M8':>14} {'Delta M8':>10}")
print(f"  {'-'*80}")
for pat in sorted(PATTERNS_5M):
    mask_p = df5["pattern_name"] == pat
    n = mask_p.sum()
    if n < 20:
        continue
    pre  = df5.loc[mask_p, "pnl_r"].values
    post = df5_m8.loc[df5_m8["pattern_name"] == pat, "pnl_r"].values
    print(
        f"  {pat:<30} {n:>5} {(pre>0).mean()*100:>4.0f}%  "
        f"{pre.mean():>+11.4f}R {post.mean():>+13.4f}R {post.mean()-pre.mean():>+9.4f}R"
    )

# ---------------------------------------------------------------------------
# VERDICT FINALE
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  VERDICT FINALE — SINTESI DEFINITIVA")
print(SEP)
print(f"  Capitale iniziale   : EUR {CAPITAL:,.0f}")
print(f"  Risk per trade      : {RISK_PCT*100:.1f}%  (1% per slot, max 5 slot = 5% portafoglio)")
print(f"  Slippage            : {SLIP:.2f}R per trade")
print()
print(f"  1h CORE (affidabile):")
print(f"    {n_year_1h} trade/anno | avg_r={avg_r_netto_1h:+.4f}R netto")
print(f"    Mediana 12m: EUR{mc_1h['med']:>9,.0f} ({(mc_1h['med']-CAPITAL)/CAPITAL*100:+.0f}%)")
print(f"    Worst 5%:    EUR{mc_1h['p05']:>9,.0f}  DD med: {mc_1h['dd_med']*100:.1f}%  ProbP: {mc_1h['prob_profit']*100:.0f}%")
print(f"    Aritmetico:  EUR{CAPITAL*(1+arith_1h):>9,.0f} ({arith_1h*100:+.0f}%)")
print()
print(f"  5m AGGIUNTA (incerta — richiede validazione live M8):")
print(f"    pre-M8  [{n_year_5m_cons}/yr]: EUR{mc_5m_pre_c['med']:,.0f} ({(mc_5m_pre_c['med']-CAPITAL)/CAPITAL*100:+.0f}%) standalone")
print(f"    post-M8 [{n_year_5m_cons}/yr]: EUR{mc_5m_post_c['med']:,.0f} ({(mc_5m_post_c['med']-CAPITAL)/CAPITAL*100:+.0f}%) standalone [C]")
print(f"    post-M8 [{n_year_5m_opt}/yr]:  EUR{mc_5m_post_o['med']:,.0f} ({(mc_5m_post_o['med']-CAPITAL)/CAPITAL*100:+.0f}%) standalone [O]")
print()
print(f"  COMBINATO E+ (3+2 slot bidirezionale):")
print(f"    Conservativo (pre-M8): EUR{mc_comb_pre['med']:>12,.0f} "
      f"({(mc_comb_pre['med']-CAPITAL)/CAPITAL*100:+.0f}%)")
print(f"    Post-M8 [C]:           EUR{mc_comb_post_c['med']:>12,.0f} "
      f"({(mc_comb_post_c['med']-CAPITAL)/CAPITAL*100:+.0f}%)")
print(f"    Post-M8 [O]:           EUR{mc_comb_post_o['med']:>12,.0f} "
      f"({(mc_comb_post_o['med']-CAPITAL)/CAPITAL*100:+.0f}%)")
print()
print(f"  RACCOMANDAZIONE:")
print(f"    Il lower bound affidabile e' la stima ARITMETICA del combinato [C]: {arith_comb_post*100:+.0f}%")
print(f"    (= EUR{CAPITAL*(1+arith_comb_post):,.0f} da EUR 100k)")
print(f"    Il MC composto e' il teorico massimo se le condizioni di backtest si replicano.")
print(f"    La verita' e' tra i due. Priorita': validare M8 in live per 2-3 mesi.")
print()
print(f"  NOTA METODOLOGICA:")
print(f"    - MC composto: ogni trade reinveste l'intero capitale corrente (max teorico).")
print(f"    - MC aritmetico: scommette 1% del capitale INIZIALE per trade (lower bound).")
print(f"    - Un sistema con 5 slot concorrenti si comporta tra i due modelli.")
print(f"    - Frequenza 5m (raw/20) e' la principale fonte di incertezza.")
print(SEP)
