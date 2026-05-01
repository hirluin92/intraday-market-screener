"""
validate_full_dataset.py
========================
Analisi completa su val_1h_full.csv e val_5m_full.csv (dataset deterministici, timestamp.asc).

Verifica:
  1. Statistiche per pattern (n, avg_r, WR, PF)
  2. Statistiche per simbolo — conferma rimozioni FIX3
  3. compression_to_expansion_transition (1h e 5m)
  4. engulfing_bullish per regime
  5. Simboli rimossi: sono ancora negativi?
  6. Monte Carlo finale combinato
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEP = "=" * 72
SEP2 = "-" * 72

# ---------------------------------------------------------------------------
# Carica dataset
# ---------------------------------------------------------------------------
df1_raw = pd.read_csv("data/val_1h_full.csv")
df5_raw = pd.read_csv("data/val_5m_full.csv")

df1_raw["pattern_timestamp"] = pd.to_datetime(df1_raw["pattern_timestamp"], utc=True)
df5_raw["pattern_timestamp"] = pd.to_datetime(df5_raw["pattern_timestamp"], utc=True)

# Solo trade entrati
df1 = df1_raw[df1_raw["entry_filled"].astype(bool)].copy()
df5 = df5_raw[df5_raw["entry_filled"].astype(bool)].copy()

print(SEP)
print("  DATASET FULL (timestamp.asc, deterministico)")
print(SEP)
print(f"  1h total rows: {len(df1_raw):,}  entry_filled: {len(df1):,}")
print(f"  5m total rows: {len(df5_raw):,}  entry_filled: {len(df5):,}")
date_range_1h = f"{df1['pattern_timestamp'].min().date()} to {df1['pattern_timestamp'].max().date()}" if len(df1) else "n/a"
date_range_5m = f"{df5['pattern_timestamp'].min().date()} to {df5['pattern_timestamp'].max().date()}" if len(df5) else "n/a"
print(f"  Range 1h: {date_range_1h}")
print(f"  Range 5m: {date_range_5m}")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def stats(df: pd.DataFrame, label: str = "") -> None:
    if df.empty:
        print(f"  {label:40s}: n=0 — nessun dato")
        return
    n = len(df)
    avg = df["pnl_r"].mean()
    wr = (df["pnl_r"] > 0).mean() * 100
    wins = (df["pnl_r"] > 0).sum()
    losses = (df["pnl_r"] <= 0).sum()
    gross_profit = df.loc[df["pnl_r"] > 0, "pnl_r"].sum()
    gross_loss = abs(df.loc[df["pnl_r"] <= 0, "pnl_r"].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    std = df["pnl_r"].std()
    print(f"  {label:40s}: n={n:>5}  avg={avg:+.4f}R  WR={wr:>5.1f}%  PF={pf:>5.2f}  std={std:.3f}")


def stats_table(df: pd.DataFrame, groupby: str) -> None:
    for key, grp in df.groupby(groupby):
        stats(grp, str(key))


# ---------------------------------------------------------------------------
# 1. Statistiche per pattern — 1h
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  PATTERN STATS — 1h (entry_filled)")
print(SEP)
print(f"  {'Pattern':40s}  {'n':>5}  {'avg_r':>8}  {'WR%':>6}  {'PF':>5}  {'std':>5}")
print("  " + SEP2)

VALIDATED_1H = {
    "double_bottom", "double_top", "engulfing_bullish",
    "macd_divergence_bull", "rsi_divergence_bull",
    "rsi_divergence_bear", "macd_divergence_bear",
    "compression_to_expansion_transition",
}

for pn in sorted(VALIDATED_1H):
    sub = df1[df1["pattern_name"] == pn]
    stats(sub, pn)

print()
print("  Altri pattern presenti nel dataset 1h:")
other_1h = df1[~df1["pattern_name"].isin(VALIDATED_1H)]
if other_1h.empty:
    print("  (nessuno)")
else:
    stats_table(other_1h, "pattern_name")


# ---------------------------------------------------------------------------
# 2. Statistiche per pattern — 5m
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  PATTERN STATS — 5m Alpaca (entry_filled)")
print(SEP)

VALIDATED_5M_ALPACA = {
    "double_bottom", "double_top",
    "macd_divergence_bear", "macd_divergence_bull",
    "engulfing_bullish",
    "rsi_divergence_bear", "rsi_divergence_bull",
    "compression_to_expansion_transition",
}

df5_alp = df5[df5["provider"] == "alpaca"]
df5_bin = df5[df5["provider"] == "binance"]

print(f"  5m Alpaca n={len(df5_alp):,}  |  5m Binance n={len(df5_bin):,}")
print()
print("  -- Alpaca 5m --")
for pn in sorted(VALIDATED_5M_ALPACA):
    sub = df5_alp[df5_alp["pattern_name"] == pn]
    stats(sub, pn)

print()
print("  -- Binance 5m --")
for pn in sorted(VALIDATED_5M_ALPACA):
    sub = df5_bin[df5_bin["pattern_name"] == pn]
    stats(sub, pn)


# ---------------------------------------------------------------------------
# 3. Conferma simboli rimossi (FIX3) — ancora negativi?
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  VERIFICA SIMBOLI RIMOSSI — FIX3 (ancora negativi sul full dataset?)")
print(SEP)

REMOVED_1H = ["TSCO", "JPM", "LLOY", "IWM", "VOD"]
REMOVED_5M = ["SPY", "META", "AAPL", "MSFT", "NVDA", "GOOGL"]

print("  1h simboli rimossi (dovrebbero avere avg_r < 0):")
for sym in REMOVED_1H:
    sub = df1_raw[df1_raw["symbol"] == sym]
    sub_filled = sub[sub["entry_filled"].astype(bool)]
    if sub_filled.empty:
        print(f"    {sym:10s}: 0 trade nel dataset (già escluso da build)")
    else:
        avg = sub_filled["pnl_r"].mean()
        wr = (sub_filled["pnl_r"] > 0).mean() * 100
        print(f"    {sym:10s}: n={len(sub_filled):>4}  avg={avg:+.4f}R  WR={wr:.1f}%  "
              f"  {'CONFERMATO NEGATIVO' if avg < 0 else '*** ATTENZIONE: ORA POSITIVO ***'}")

print()
print("  5m Alpaca simboli rimossi (dovrebbero avere avg_r < 0):")
for sym in REMOVED_5M:
    sub = df5_raw[(df5_raw["symbol"] == sym) & (df5_raw["provider"] == "alpaca")]
    sub_filled = sub[sub["entry_filled"].astype(bool)]
    if sub_filled.empty:
        print(f"    {sym:10s}: 0 trade nel dataset (già escluso da build)")
    else:
        avg = sub_filled["pnl_r"].mean()
        wr = (sub_filled["pnl_r"] > 0).mean() * 100
        print(f"    {sym:10s}: n={len(sub_filled):>4}  avg={avg:+.4f}R  WR={wr:.1f}%  "
              f"  {'CONFERMATO NEGATIVO' if avg < 0 else '*** ATTENZIONE: ORA POSITIVO ***'}")


# ---------------------------------------------------------------------------
# 4. Statistiche per simbolo — 1h top/bottom
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  STATISTICHE PER SIMBOLO — 1h (top 15 per n)")
print(SEP)
sym_stats_1h = (
    df1.groupby("symbol")["pnl_r"]
    .agg(n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100)
    .sort_values("n", ascending=False)
    .head(20)
)
for sym, row in sym_stats_1h.iterrows():
    print(f"  {sym:10s}: n={int(row['n']):>5}  avg={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%")

print()
print("  Bottom 10 per avg_r (1h):")
sym_bottom_1h = (
    df1.groupby("symbol")["pnl_r"]
    .agg(n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100)
    .query("n >= 10")
    .sort_values("avg_r")
    .head(10)
)
for sym, row in sym_bottom_1h.iterrows():
    print(f"  {sym:10s}: n={int(row['n']):>5}  avg={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%")


# ---------------------------------------------------------------------------
# 5. Statistiche per simbolo — 5m Alpaca top/bottom
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  STATISTICHE PER SIMBOLO — 5m Alpaca")
print(SEP)
sym_stats_5m = (
    df5_alp.groupby("symbol")["pnl_r"]
    .agg(n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100)
    .sort_values("avg_r", ascending=False)
)
for sym, row in sym_stats_5m.iterrows():
    flag = "  ***RIMOSSO***" if sym in REMOVED_5M else ""
    print(f"  {sym:10s}: n={int(row['n']):>5}  avg={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")


# ---------------------------------------------------------------------------
# 6. compression_to_expansion_transition — analisi separata
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  compression_to_expansion_transition — ANALISI SEPARATA")
print(SEP)
cet_1h = df1[df1["pattern_name"] == "compression_to_expansion_transition"]
cet_5m_alp = df5_alp[df5_alp["pattern_name"] == "compression_to_expansion_transition"]

print("  1h:")
if cet_1h.empty:
    print("    nessun trade")
else:
    stats(cet_1h, "  all directions")
    for d in ["bullish", "bearish"]:
        stats(cet_1h[cet_1h["direction"] == d], f"  {d}")

print()
print("  5m Alpaca:")
if cet_5m_alp.empty:
    print("    nessun trade")
else:
    stats(cet_5m_alp, "  all directions")
    for d in ["bullish", "bearish"]:
        stats(cet_5m_alp[cet_5m_alp["direction"] == d], f"  {d}")


# ---------------------------------------------------------------------------
# 7. engulfing_bullish — analisi separata
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  engulfing_bullish — ANALISI SEPARATA")
print(SEP)
eng_1h = df1[df1["pattern_name"] == "engulfing_bullish"]
eng_5m = df5_alp[df5_alp["pattern_name"] == "engulfing_bullish"]
print(f"  1h: ", end=""); stats(eng_1h, "engulfing_bullish 1h")
print(f"  5m: ", end=""); stats(eng_5m, "engulfing_bullish 5m")


# ---------------------------------------------------------------------------
# 8. Divergenze — bear vs bull regime
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  DIVERGENZE — avg_r per pattern (1h, tutti i trade)")
print(SEP)
for pn in ["rsi_divergence_bull", "rsi_divergence_bear", "macd_divergence_bull", "macd_divergence_bear"]:
    stats(df1[df1["pattern_name"] == pn], f"1h {pn}")

print()
for pn in ["rsi_divergence_bull", "rsi_divergence_bear", "macd_divergence_bull", "macd_divergence_bear"]:
    stats(df5_alp[df5_alp["pattern_name"] == pn], f"5m {pn}")


# ---------------------------------------------------------------------------
# 9. Monte Carlo sul full dataset (combinato 1h + 5m Alpaca)
# ---------------------------------------------------------------------------
# MC pool: NO engulfing_bullish.
# Motivo: engulfing ha edge confermato SOLO in regime bear (avg bear=+0.16R, bull=-0.13R).
# Includere tutti i trade engulfing (senza separazione regime) produce avg_r≈-0.03R su 1h
# e -0.49R su 5m — pool non rappresentativo dell'operatività live che applica il filtro.
VALIDATED_1H_MC = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "rsi_divergence_bull",
    "rsi_divergence_bear", "macd_divergence_bear",
}
VALIDATED_5M_MC_ALPACA = {
    "double_bottom", "double_top",
    "macd_divergence_bear", "macd_divergence_bull",
}

SLIP = 0.15
N_SIM = 5_000
CAPITAL = 2_500.0
RISK_PCT = 0.01

df1_mc = df1[df1["pattern_name"].isin(VALIDATED_1H_MC)].copy()
df5_mc = df5_alp[df5_alp["pattern_name"].isin(VALIDATED_5M_MC_ALPACA)].copy()

months_1h = max(1, (df1_mc["pattern_timestamp"].max() - df1_mc["pattern_timestamp"].min()).days / 30)
months_5m = max(1, (df5_mc["pattern_timestamp"].max() - df5_mc["pattern_timestamp"].min()).days / 30)

n_month_1h = len(df1_mc) / months_1h
n_month_5m = len(df5_mc) / months_5m
n_year_1h = round(n_month_1h * 12)
n_year_5m = round(n_month_5m * 12)

avg_r_1h = df1_mc["pnl_r"].mean()
avg_r_5m = df5_mc["pnl_r"].mean()
pool_1h = (df1_mc["pnl_r"] - SLIP).values
pool_5m = (df5_mc["pnl_r"] - SLIP).values

# ---------------------------------------------------------------------------
# 5b. Statistiche per simbolo 5m — filtrate ai 4 pattern validati (no engulfing)
# ---------------------------------------------------------------------------
print()
print(SEP)
print("  5m SIMBOLI — solo 4 pattern validati (no engulfing_bullish)")
print(SEP)
sym_stats_5m_mc = (
    df5_mc.groupby("symbol")["pnl_r"]
    .agg(n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100)
    .sort_values("avg_r", ascending=False)
)
for sym, row in sym_stats_5m_mc.iterrows():
    flag = "  ***RIMOSSO***" if sym in REMOVED_5M else ""
    print(f"  {sym:10s}: n={int(row['n']):>5}  avg={row['avg_r']:+.4f}R  WR={row['wr']:>5.1f}%{flag}")


print()
print(SEP)
print("  POOL MC — full dataset deterministico (NO engulfing_bullish)")
print(SEP)
# Il n_year_raw e' la frequenza STORICA di tutte le occorrenze nel DB.
# Il sistema live filtra via: confluenza (min 2, -70%), strength, regime.
# Frequenza live stimata ~ raw / 4. Il MC usa la stima conservativa.
n_year_1h_raw = n_year_1h
n_year_5m_raw = n_year_5m
n_year_1h_live = max(1, round(n_year_1h_raw / 4))
n_year_5m_live = max(1, round(n_year_5m_raw / 4))
print(f"  1h : n={len(df1_mc):,}  avg_r={avg_r_1h:+.4f}R  post-slip={pool_1h.mean():+.4f}R  "
      f"WR={(pool_1h>0).mean()*100:.1f}%  raw={n_year_1h_raw} t/a  live~{n_year_1h_live} t/a")
print(f"  5m : n={len(df5_mc):,}  avg_r={avg_r_5m:+.4f}R  post-slip={pool_5m.mean():+.4f}R  "
      f"WR={(pool_5m>0).mean()*100:.1f}%  raw={n_year_5m_raw} t/a  live~{n_year_5m_live} t/a")
print()
print("  NOTA 5m: dataset copre 2023-07 -> 2024-09 (14 mesi). Per dati recenti: build --limit 200000.")


def run_mc(pool: np.ndarray, n_trades_year: int, n_sim: int = N_SIM, seed: int = 42) -> dict:
    if len(pool) == 0 or n_trades_year == 0:
        return dict(med=CAPITAL, p05=CAPITAL, prob_profit=0.0, dd_med=0.0, dd_p95=0.0)
    rng = np.random.default_rng(seed)
    finals = np.empty(n_sim)
    max_dds = np.empty(n_sim)
    for i in range(n_sim):
        draws = rng.choice(pool, size=n_trades_year, replace=True)
        eq = CAPITAL; peak = CAPITAL; max_dd = 0.0
        for r in draws:
            eq *= 1.0 + RISK_PCT * r
            if eq > peak: peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd: max_dd = dd
        finals[i] = eq; max_dds[i] = max_dd
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob_profit=(finals > CAPITAL).mean(),
        dd_med=np.median(max_dds), dd_p95=np.percentile(max_dds, 95),
    )


def run_mc_combined(pool_1h, n_1h, pool_5m, n_5m, n_sim=N_SIM, seed=42) -> dict:
    total = n_1h + n_5m
    if total == 0:
        return dict(med=CAPITAL, p05=CAPITAL, prob_profit=0.0, dd_med=0.0, dd_p95=0.0)
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
    return dict(
        med=np.median(finals), p05=np.percentile(finals, 5),
        prob_profit=(finals > CAPITAL).mean(),
        dd_med=np.median(max_dds), dd_p95=np.percentile(max_dds, 95),
    )


print("\n  Calcolo MC (freq live stimata ~raw/4)...")
mc1h = run_mc(pool_1h, n_year_1h_live)
mc5m = run_mc(pool_5m, n_year_5m_live)
mc_comb = run_mc_combined(pool_1h, n_year_1h_live, pool_5m, n_year_5m_live)

print()
print(SEP)
print("  MONTE CARLO (5,000 sim, 12 mesi, slip=0.15R, capitale EUR 2,500)")
print("  Pool: double/top/bottom + divergenze (no engulfing) | freq live = raw/4")
print(SEP)
header = f"  {'Scenario':<30} {'t/a':>5} {'Mediana':>9} {'Worst5%':>9} {'ProbP':>7} {'DD med':>7} {'DD p95':>7}"
print(header)
print("  " + SEP2)
mc_rows = [
    ("Solo 1h",          n_year_1h_live,                    mc1h),
    ("Solo 5m Alpaca",   n_year_5m_live,                    mc5m),
    ("Combinato 1h+5m",  n_year_1h_live + n_year_5m_live,   mc_comb),
]
for label, n_yr, mc in mc_rows:
    print(
        f"  {label:<30} {n_yr:>5} "
        f"{mc['med']:>8,.0f}  "
        f"{mc['p05']:>8,.0f}  "
        f"{mc['prob_profit']*100:>6.1f}%  "
        f"{mc['dd_med']*100:>6.1f}%  "
        f"{mc['dd_p95']*100:>6.1f}%"
    )

print()
print(SEP)
print("  BREAK-EVEN SLIPPAGE (full dataset, no engulfing)")
print(SEP)
print(f"  1h: {avg_r_1h:+.4f}R  (sopravvive fino a {avg_r_1h:.3f}R slip/trade)")
print(f"  5m: {avg_r_5m:+.4f}R  (sopravvive fino a {avg_r_5m:.3f}R slip/trade)")
print()
