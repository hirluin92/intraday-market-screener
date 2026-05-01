"""
Analisi esaustiva — 10 leve per aumentare i profitti.
Dataset: val_1h_large_post_fix.csv + val_5m_fixed.csv (Alpaca 4 pattern validati).
Baseline: tutti i trade entry_filled=True con pattern validati.
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

try:
    from zoneinfo import ZoneInfo
    TZ_ET = ZoneInfo("America/New_York")
except Exception:
    TZ_ET = None

# ─── Costanti ─────────────────────────────────────────────────────────────────
VALIDATED_1H = {
    "double_bottom", "double_top", "engulfing_bullish",
    "macd_divergence_bull", "rsi_divergence_bull",
    "rsi_divergence_bear", "macd_divergence_bear",
}
VALIDATED_5M_ALPACA = {
    "double_bottom", "double_top",
    "macd_divergence_bear", "macd_divergence_bull",
}

BASELINE_AVG_R_1H = None   # calcolato sotto
BASELINE_AVG_R_5M = None
CAPITAL = 2500.0
RISK_PCT = 0.01
MONTHS_PER_YEAR = 12

SECTION = "=" * 72


# ─── Helpers ──────────────────────────────────────────────────────────────────

def stats_row(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0:
        return dict(label=label, n=0, avg_r=float("nan"), wr=float("nan"), p=float("nan"))
    avg = df["pnl_r"].mean()
    wr = (df["pnl_r"] > 0).mean() * 100
    _, p = stats.ttest_1samp(df["pnl_r"], 0) if n >= 5 else (None, float("nan"))
    return dict(label=label, n=n, avg_r=avg, wr=wr, p=p)


def equity_final(avg_r: float, n_per_year: float, capital: float = CAPITAL) -> float:
    """Equity finale composta dopo 12 mesi."""
    if n_per_year == 0 or np.isnan(avg_r):
        return capital
    eq = capital
    for _ in range(int(n_per_year)):
        eq *= 1 + RISK_PCT * avg_r
    return eq


def improvement_table(rows: list[dict]) -> str:
    header = f"{'Filtro':<35} {'n_rmv':>6} {'r_rmv':>7} {'n_rest':>7} {'r_new':>7} {'eq_new':>9}"
    sep = "-" * len(header)
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"{r['label']:<35} {r['n_removed']:>6} {r['avg_r_removed']:>+7.3f} "
            f"{r['n_remaining']:>7} {r['avg_r_new']:>+7.3f} {r['equity_new']:>9,.0f}"
        )
    return "\n".join(lines)


def ttest_str(p: float) -> str:
    if np.isnan(p):
        return ""
    if p < 0.01:
        return "***"
    if p < 0.05:
        return "**"
    if p < 0.10:
        return "*"
    return ""


# ─── Carica dati ──────────────────────────────────────────────────────────────

df1_raw = pd.read_csv("data/val_1h_large_post_fix.csv")
df1_raw["pattern_timestamp"] = pd.to_datetime(df1_raw["pattern_timestamp"], utc=True)

df5_raw = pd.read_csv("data/val_5m_fixed.csv")
df5_raw["pattern_timestamp"] = pd.to_datetime(df5_raw["pattern_timestamp"], utc=True)

# Baseline: entry_filled + pattern validato
df1 = df1_raw[
    df1_raw["entry_filled"].astype(bool) &
    df1_raw["pattern_name"].isin(VALIDATED_1H)
].copy()

df5 = df5_raw[
    df5_raw["entry_filled"].astype(bool) &
    df5_raw["provider"].eq("alpaca") &
    df5_raw["pattern_name"].isin(VALIDATED_5M_ALPACA)
].copy()

BASELINE_AVG_R_1H = df1["pnl_r"].mean()
BASELINE_AVG_R_5M = df5["pnl_r"].mean()

# Trade per mese baseline
months_span_1h = max(1, (df1["pattern_timestamp"].max() - df1["pattern_timestamp"].min()).days / 30)
months_span_5m = max(1, (df5["pattern_timestamp"].max() - df5["pattern_timestamp"].min()).days / 30)

N_MONTH_1H = len(df1) / months_span_1h
N_MONTH_5M = len(df5) / months_span_5m
N_YEAR_1H  = N_MONTH_1H * 12
N_YEAR_5M  = N_MONTH_5M * 12

BASELINE_EQ_1H = equity_final(BASELINE_AVG_R_1H, N_YEAR_1H)
BASELINE_EQ_5M = equity_final(BASELINE_AVG_R_5M, N_YEAR_5M)
BASELINE_EQ_COMBINED = equity_final(
    (BASELINE_AVG_R_1H * N_YEAR_1H + BASELINE_AVG_R_5M * N_YEAR_5M) /
    max(1, N_YEAR_1H + N_YEAR_5M),
    N_YEAR_1H + N_YEAR_5M,
)

summary_rows: list[dict] = []

print(SECTION)
print(f"  BASELINE")
print(SECTION)
print(f"  1h : n={len(df1):,}  avg_r={BASELINE_AVG_R_1H:+.4f}  {N_YEAR_1H:.0f} t/a  eq={BASELINE_EQ_1H:,.0f} EUR")
print(f"  5m : n={len(df5):,}  avg_r={BASELINE_AVG_R_5M:+.4f}  {N_YEAR_5M:.0f} t/a  eq={BASELINE_EQ_5M:,.0f} EUR")
print(f"  Combined equity (MC mediana attesa): ~12,063 EUR")
print()


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 1 — GIORNO DELLA SETTIMANA
# ═══════════════════════════════════════════════════════════════════════════════
print(SECTION)
print("  ANALISI 1 — GIORNO DELLA SETTIMANA")
print(SECTION)

day_names = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì"]

for label, df, tag in [("1h", df1, "1h"), ("5m Alpaca", df5, "5m")]:
    df = df.copy()
    df["dow"] = df["pattern_timestamp"].dt.dayofweek
    print(f"\n  {label}  (baseline avg_r={df['pnl_r'].mean():+.4f})")
    print(f"  {'Giorno':<12} {'n':>5} {'avg_r':>7} {'WR%':>6} {'sig':>4}")
    print(f"  {'-'*40}")
    for d in range(5):
        sub = df[df["dow"] == d]
        r = stats_row(sub, day_names[d])
        print(f"  {r['label']:<12} {r['n']:>5} {r['avg_r']:>+7.4f} {r['wr']:>6.1f}% {ttest_str(r['p']):>4}")

# Filtro: rimuovi giorni con avg_r < -0.10 E n >= 20
print()
for label, df_orig, tag, base_avg, n_yr in [
    ("1h", df1, "1h", BASELINE_AVG_R_1H, N_YEAR_1H),
    ("5m", df5, "5m", BASELINE_AVG_R_5M, N_YEAR_5M),
]:
    df = df_orig.copy()
    df["dow"] = df["pattern_timestamp"].dt.dayofweek
    day_stats = df.groupby("dow")["pnl_r"].agg(["mean", "count"])
    bad_days = day_stats[(day_stats["mean"] < -0.10) & (day_stats["count"] >= 20)].index.tolist()
    removed = df[df["dow"].isin(bad_days)]
    kept    = df[~df["dow"].isin(bad_days)]
    if len(bad_days) > 0:
        bad_names = [day_names[d] for d in bad_days]
        print(f"  {label} — Giorni da rimuovere: {bad_names}")
        print(f"    rimossi: n={len(removed)} avg_r={removed['pnl_r'].mean():+.4f}")
        print(f"    restanti: n={len(kept)} avg_r={kept['pnl_r'].mean():+.4f}")
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        summary_rows.append(dict(
            label=f"A1 rimuovi giorni neg ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean() if len(removed) else float("nan"),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))
    else:
        print(f"  {label} — nessun giorno sistematicamente negativo (soglia avg_r < -0.10, n >= 20)")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 2 — STAGIONALITÀ MENSILE
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 2 — STAGIONALITÀ MENSILE")
print(SECTION)

month_names = ["Gen","Feb","Mar","Apr","Mag","Giu","Lug","Ago","Set","Ott","Nov","Dic"]

for label, df_orig in [("1h", df1), ("5m Alpaca", df5)]:
    df = df_orig.copy()
    df["month"] = df["pattern_timestamp"].dt.month
    print(f"\n  {label}  baseline avg_r={df['pnl_r'].mean():+.4f}")
    print(f"  {'Mese':<6} {'n':>5} {'avg_r':>7} {'WR%':>6}")
    print(f"  {'-'*32}")
    for m in range(1, 13):
        sub = df[df["month"] == m]
        if len(sub) == 0:
            continue
        r = stats_row(sub, month_names[m-1])
        flag = " !" if r["avg_r"] < -0.05 and r["n"] >= 10 else ""
        print(f"  {r['label']:<6} {r['n']:>5} {r['avg_r']:>+7.4f} {r['wr']:>6.1f}%{flag}")

print()
for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H), ("5m", df5, N_YEAR_5M)]:
    df = df_orig.copy()
    df["month"] = df["pattern_timestamp"].dt.month
    ms = df.groupby("month")["pnl_r"].agg(["mean","count"])
    bad = ms[(ms["mean"] < -0.05) & (ms["count"] >= 10)].index.tolist()
    removed = df[df["month"].isin(bad)]
    kept    = df[~df["month"].isin(bad)]
    if bad:
        bnames = [month_names[m-1] for m in bad]
        print(f"  {label} — Mesi da rimuovere: {bnames}")
        print(f"    rimossi: n={len(removed)} avg_r={removed['pnl_r'].mean():+.4f}")
        print(f"    restanti: n={len(kept)} avg_r={kept['pnl_r'].mean():+.4f}")
        n_yr_new = n_yr * (10/12)
        summary_rows.append(dict(
            label=f"A2 rimuovi mesi neg ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean() if len(removed) else float("nan"),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))
    else:
        print(f"  {label} — nessun mese sistematicamente negativo (soglia avg_r < -0.05, n >= 10)")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 3 — SCREENER_SCORE COME PROXY VOLATILITÀ/QUALITÀ
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 3 — SCREENER_SCORE COME FILTRO QUALITÀ")
print(SECTION)

for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H), ("5m", df5, N_YEAR_5M)]:
    df = df_orig.copy()
    print(f"\n  {label}  screener_score range: [{df['screener_score'].min()},{df['screener_score'].max()}]")
    print(f"  {'Score':>12} {'n':>5} {'avg_r':>7} {'WR%':>6}")
    print(f"  {'-'*38}")
    # Bucketa per decili del score
    buckets = list(range(0, 101, 10))
    for lo, hi in zip(buckets[:-1], buckets[1:]):
        sub = df[(df["screener_score"] >= lo) & (df["screener_score"] < hi)]
        if len(sub) == 0:
            continue
        r = stats_row(sub, f"[{lo},{hi})")
        print(f"  {r['label']:>12} {r['n']:>5} {r['avg_r']:>+7.4f} {r['wr']:>6.1f}%")

    # Trova soglia ottima
    thresholds = range(20, 75, 5)
    best_thr, best_avg = None, -999
    for t in thresholds:
        sub = df[df["screener_score"] >= t]
        if len(sub) >= 30:
            a = sub["pnl_r"].mean()
            if a > best_avg:
                best_avg, best_thr = a, t
    if best_thr is not None:
        kept    = df[df["screener_score"] >= best_thr]
        removed = df[df["screener_score"] < best_thr]
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        print(f"\n  Soglia ottima >= {best_thr}: restanti={len(kept)} avg_r={kept['pnl_r'].mean():+.4f} "
              f"(rimossi {len(removed)}, avg_r rimossi={removed['pnl_r'].mean():+.4f})")
        summary_rows.append(dict(
            label=f"A3 screener_score>={best_thr} ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean(),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 4 — DIREZIONE TRADE (bullish vs bearish)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 4 — DIREZIONE DEL TRADE")
print(SECTION)

for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H), ("5m", df5, N_YEAR_5M)]:
    df = df_orig.copy()
    print(f"\n  {label}  baseline avg_r={df['pnl_r'].mean():+.4f}")
    print(f"  {'Direzione':<12} {'n':>5} {'avg_r':>7} {'WR%':>6} {'sig':>4}")
    print(f"  {'-'*38}")
    for d in ["bullish", "bearish"]:
        sub = df[df["direction"] == d]
        r = stats_row(sub, d)
        print(f"  {r['label']:<12} {r['n']:>5} {r['avg_r']:>+7.4f} {r['wr']:>6.1f}% {ttest_str(r['p']):>4}")

    # Analisi per pattern+direzione
    print(f"\n  {label}  avg_r per pattern+direzione:")
    print(f"  {'Pattern':<28} {'dir':<9} {'n':>5} {'avg_r':>7}")
    print(f"  {'-'*54}")
    combo = df.groupby(["pattern_name","direction"])["pnl_r"].agg(["mean","count"]).reset_index()
    combo = combo.sort_values("mean", ascending=False)
    for _, row in combo.iterrows():
        print(f"  {row['pattern_name']:<28} {row['direction']:<9} {int(row['count']):>5} {row['mean']:>+7.4f}")

    # Filtro: rimuovi direzione con avg_r < -0.05 e n >= 20
    dir_stats = df.groupby("direction")["pnl_r"].agg(["mean","count"])
    bad_dirs = dir_stats[(dir_stats["mean"] < -0.05) & (dir_stats["count"] >= 20)].index.tolist()
    if bad_dirs:
        removed = df[df["direction"].isin(bad_dirs)]
        kept    = df[~df["direction"].isin(bad_dirs)]
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        print(f"\n  Direzioni da rimuovere: {bad_dirs}")
        print(f"  rimossi={len(removed)} avg_r={removed['pnl_r'].mean():+.4f} | restanti={len(kept)} avg_r={kept['pnl_r'].mean():+.4f}")
        summary_rows.append(dict(
            label=f"A4 rimuovi dir negativa ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean(),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))
    else:
        print(f"  Nessuna direzione sistematicamente negativa.")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 5 — PATTERN_STRENGTH COME FILTRO CONTINUO
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 5 — PATTERN_STRENGTH COME FILTRO CONTINUO")
print(SECTION)

for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H), ("5m", df5, N_YEAR_5M)]:
    df = df_orig.copy()
    print(f"\n  {label}  baseline avg_r={df['pnl_r'].mean():+.4f}  "
          f"strength range [{df['pattern_strength'].min():.2f},{df['pattern_strength'].max():.2f}]")
    print(f"  {'Strength':>12} {'n':>5} {'avg_r':>7} {'WR%':>6}")
    print(f"  {'-'*38}")
    for lo in np.arange(0, 1.0, 0.1):
        hi = lo + 0.1
        sub = df[(df["pattern_strength"] >= lo) & (df["pattern_strength"] < hi)]
        if len(sub) == 0:
            continue
        r = stats_row(sub, f"[{lo:.1f},{hi:.1f})")
        print(f"  {r['label']:>12} {r['n']:>5} {r['avg_r']:>+7.4f} {r['wr']:>6.1f}%")

    # Soglia ottima
    best_thr, best_avg = None, -999
    for t in np.arange(0.50, 0.90, 0.05):
        sub = df[df["pattern_strength"] >= t]
        if len(sub) >= 30:
            a = sub["pnl_r"].mean()
            if a > best_avg:
                best_avg, best_thr = a, t
    if best_thr is not None:
        kept    = df[df["pattern_strength"] >= best_thr]
        removed = df[df["pattern_strength"] < best_thr]
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        print(f"\n  Soglia ottima strength >= {best_thr:.2f}: n_rest={len(kept)} avg_r={kept['pnl_r'].mean():+.4f} "
              f"(rimossi={len(removed)} avg_r_rmv={removed['pnl_r'].mean():+.4f})")
        summary_rows.append(dict(
            label=f"A5 strength>={best_thr:.2f} ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean(),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 6 — DISTRIBUZIONE PNL_R SUI PERDENTI (stop slippage)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 6 — DISTRIBUZIONE PNL_R SUI PERDENTI (stop discipline)")
print(SECTION)

for label, df_orig in [("1h", df1), ("5m", df5)]:
    df = df_orig.copy()
    losers = df[df["pnl_r"] < 0]
    print(f"\n  {label}  n_losers={len(losers)}/{len(df)}")
    print(f"  Distribuzione perdenti:")
    print(f"    > -0.50R (uscita anticipata):  {(losers['pnl_r'] > -0.5).sum():>5}  ({(losers['pnl_r'] > -0.5).mean()*100:.1f}%)")
    print(f"    -0.50 a -0.99R:                {((losers['pnl_r'] >= -1.0) & (losers['pnl_r'] <= -0.5)).sum():>5}")
    print(f"    Esattamente -1.0R (±0.01):     {((losers['pnl_r'] >= -1.01) & (losers['pnl_r'] <= -0.99)).sum():>5}  (stop esatto)")
    print(f"    -1.0 a -1.5R:                  {((losers['pnl_r'] < -1.0) & (losers['pnl_r'] >= -1.5)).sum():>5}")
    print(f"    < -1.5R (stop slippage grave): {(losers['pnl_r'] < -1.5).sum():>5}  ({(losers['pnl_r'] < -1.5).mean()*100:.1f}%)")
    print(f"  avg perdita: {losers['pnl_r'].mean():+.4f}R  |  percentile 5%: {losers['pnl_r'].quantile(0.05):+.4f}R")

    # R:R effettivo
    winners = df[df["pnl_r"] > 0]
    rr = abs(winners["pnl_r"].mean() / losers["pnl_r"].mean()) if len(losers) else float("nan")
    print(f"  R:R effettivo: avg_win={winners['pnl_r'].mean():+.4f}R / avg_loss={losers['pnl_r'].mean():+.4f}R = {rr:.3f}")

    # Quanti trade hanno pnl_r < -1.05 (stop violato)
    overshoot = df[df["pnl_r"] < -1.05]
    if len(overshoot) > 0:
        print(f"  ATTENZIONE: {len(overshoot)} trade con pnl_r < -1.05R "
              f"(avg={overshoot['pnl_r'].mean():+.4f}R) — lo stop viene violato")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 7 — CORRELAZIONE TRA TRADE CONSECUTIVI (serial correlation)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 7 — CORRELAZIONE TRADE CONSECUTIVI (serial correlation)")
print(SECTION)

for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H), ("5m", df5, N_YEAR_5M)]:
    df = df_orig.sort_values("pattern_timestamp").reset_index(drop=True)
    df["prev_win"] = (df["pnl_r"].shift(1) > 0)
    df["prev_loss"] = (df["pnl_r"].shift(1) < 0)
    df2 = df.iloc[1:]  # primo trade non ha precedente

    after_win  = df2[df2["prev_win"]]
    after_loss = df2[df2["prev_loss"]]

    print(f"\n  {label}  baseline avg_r={df['pnl_r'].mean():+.4f}")
    print(f"  Dopo WIN  (n={len(after_win)}):  avg_r={after_win['pnl_r'].mean():+.4f}  WR={( after_win['pnl_r']>0).mean()*100:.1f}%")
    print(f"  Dopo LOSS (n={len(after_loss)}): avg_r={after_loss['pnl_r'].mean():+.4f}  WR={(after_loss['pnl_r']>0).mean()*100:.1f}%")

    # Test correlazione seriale
    if len(df) >= 20:
        autocorr = df["pnl_r"].autocorr(lag=1)
        print(f"  Autocorrelazione lag-1: {autocorr:+.4f}")
        if abs(autocorr) > 0.10:
            print(f"  SEGNALE: autocorrelazione non trascurabile — considerare filtro dopo loss")

    # Se dopo_loss è significativamente peggiore: quantifica impatto
    if len(after_loss) >= 20 and after_loss["pnl_r"].mean() < -0.10:
        kept    = df.iloc[1:][~df2["prev_loss"]]
        removed = after_loss
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        print(f"  FILTRO: skip trade dopo loss → rimossi={len(removed)} avg_r_rmv={removed['pnl_r'].mean():+.4f} "
              f"restanti={len(kept)} avg_r={kept['pnl_r'].mean():+.4f}")
        summary_rows.append(dict(
            label=f"A7 skip dopo loss ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean(),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))
    else:
        print(f"  Nessuna correlazione seriale significativa.")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 8 — SIMBOLI BEST/WORST
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 8 — SIMBOLI BEST / WORST")
print(SECTION)

for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H), ("5m", df5, N_YEAR_5M)]:
    df = df_orig.copy()
    sym_stats = (
        df.groupby("symbol")["pnl_r"]
        .agg(n="count", avg_r="mean", wr=lambda x: (x > 0).mean() * 100)
        .reset_index()
    )
    sym_stats = sym_stats[sym_stats["n"] >= 10].sort_values("avg_r", ascending=False)

    print(f"\n  {label}  (n_simboli con n>=10: {len(sym_stats)})")
    print(f"\n  TOP 10 simboli:")
    print(f"  {'Simbolo':<12} {'n':>5} {'avg_r':>7} {'WR%':>6}")
    print(f"  {'-'*35}")
    for _, row in sym_stats.head(10).iterrows():
        print(f"  {row['symbol']:<12} {int(row['n']):>5} {row['avg_r']:>+7.4f} {row['wr']:>6.1f}%")

    print(f"\n  BOTTOM 10 simboli:")
    print(f"  {'Simbolo':<12} {'n':>5} {'avg_r':>7} {'WR%':>6}")
    print(f"  {'-'*35}")
    for _, row in sym_stats.tail(10).iterrows():
        print(f"  {row['symbol']:<12} {int(row['n']):>5} {row['avg_r']:>+7.4f} {row['wr']:>6.1f}%")

    # Filtro: rimuovi simboli con avg_r < -0.15 e n >= 15
    bad_syms = sym_stats[(sym_stats["avg_r"] < -0.15) & (sym_stats["n"] >= 15)]["symbol"].tolist()
    if bad_syms:
        removed = df[df["symbol"].isin(bad_syms)]
        kept    = df[~df["symbol"].isin(bad_syms)]
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        print(f"\n  Simboli da rimuovere: {bad_syms}")
        print(f"  rimossi={len(removed)} avg_r={removed['pnl_r'].mean():+.4f} | restanti={len(kept)} avg_r={kept['pnl_r'].mean():+.4f}")
        summary_rows.append(dict(
            label=f"A8 rimuovi simboli neg ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean(),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))
    else:
        print(f"\n  Nessun simbolo sistematicamente negativo (soglia avg_r < -0.15, n >= 15)")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 9 — CONFLUENZA PATTERN (coppie sulla stessa barra)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 9 — CONFLUENZA PATTERN (coppie sulla stessa barra)")
print(SECTION)

for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H)]:
    df = df_orig.copy()
    grp = df.groupby(["symbol","pattern_timestamp"])

    confluence_rows = []
    single_rows = []
    for (sym, ts), group in grp:
        pnl_vals = group["pnl_r"].values
        pnames   = sorted(group["pattern_name"].tolist())
        n_pat    = len(group)
        if n_pat >= 2:
            pair_key = " + ".join(pnames[:2])
            for pnl in pnl_vals:
                confluence_rows.append({"pair": pair_key, "pnl_r": pnl, "n_patterns": n_pat})
        else:
            single_rows.append({"pnl_r": pnl_vals[0]})

    df_conf = pd.DataFrame(confluence_rows)
    df_sing = pd.DataFrame(single_rows)

    n_conf = len(df_conf)
    n_sing = len(df_sing)
    avg_conf = df_conf["pnl_r"].mean() if len(df_conf) else float("nan")
    avg_sing = df_sing["pnl_r"].mean() if len(df_sing) else float("nan")

    print(f"\n  {label}: confluenza (n>=2 pattern) n={n_conf} avg_r={avg_conf:+.4f}")
    print(f"  {label}: singolo pattern         n={n_sing} avg_r={avg_sing:+.4f}")

    if len(df_conf) >= 5:
        pair_stats = df_conf.groupby("pair")["pnl_r"].agg(n="count", avg_r="mean").sort_values("avg_r", ascending=False)
        print(f"\n  Top coppie di pattern:")
        print(f"  {'Coppia':<45} {'n':>4} {'avg_r':>7}")
        print(f"  {'-'*60}")
        for _, row in pair_stats.iterrows():
            print(f"  {row.name:<45} {int(row['n']):>4} {row['avg_r']:>+7.4f}")
    else:
        print(f"  Campione di confluenza troppo piccolo per analisi coppie (n={n_conf})")
        print(f"  Nota: con min_confluence=1 (attuale) quasi tutti i trade sono singoli.")
        print(f"  Con min_confluence=2 il campione 1h si ridurrebbe drasticamente.")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI 10 — DURATA DEL TRADE (bars_to_exit)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI 10 — DURATA DEL TRADE (bars_to_exit)")
print(SECTION)

for label, df_orig, n_yr, tf_hours in [("1h", df1, N_YEAR_1H, 1), ("5m", df5, N_YEAR_5M, 1/12)]:
    df = df_orig.copy()
    df["bte"] = df["bars_to_exit"].fillna(0).astype(int)
    print(f"\n  {label}  (1 barra = {tf_hours*60:.0f} min  |  bars_to_exit max={df['bte'].max()})")

    buckets = [(1, 3), (4, 6), (7, 12), (13, 24), (25, 48), (49, 9999)]
    labels_b = ["1-3 barre", "4-6", "7-12", "13-24", "25-48", ">48"]

    print(f"  {'Durata':<14} {'n':>5} {'avg_r':>7} {'WR%':>6} {'outcome TP2%':>12}")
    print(f"  {'-'*48}")
    for (lo, hi), lbl in zip(buckets, labels_b):
        sub = df[(df["bte"] >= lo) & (df["bte"] <= hi)]
        if len(sub) == 0:
            continue
        r = stats_row(sub, lbl)
        tp2_pct = (sub["outcome"] == "tp2").mean() * 100
        print(f"  {r['label']:<14} {r['n']:>5} {r['avg_r']:>+7.4f} {r['wr']:>6.1f}% {tp2_pct:>12.1f}%")

    # Analisi timeout: i trade che scadono sono costosi?
    timeouts = df[df["outcome"] == "timeout"]
    non_to   = df[df["outcome"] != "timeout"]
    if len(timeouts) > 0:
        print(f"\n  Timeout: n={len(timeouts)} avg_r={timeouts['pnl_r'].mean():+.4f}R  vs  "
              f"No-timeout: n={len(non_to)} avg_r={non_to['pnl_r'].mean():+.4f}R")

    # Timeout come costo opportunità: rimuoverli (ridurre MAX_BARS_AFTER_ENTRY)
    if len(timeouts) >= 20 and timeouts["pnl_r"].mean() < -0.05:
        # Stima: tagliare a 24 barre elimina i timeout oltre 24
        threshold_bar = 24
        kept    = df[df["bte"] <= threshold_bar]
        removed = df[df["bte"] > threshold_bar]
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        print(f"  FILTRO MAX_BARS<=24: rimossi={len(removed)} avg_r_rmv={removed['pnl_r'].mean():+.4f} "
              f"restanti={len(kept)} avg_r={kept['pnl_r'].mean():+.4f}")
        summary_rows.append(dict(
            label=f"A10 max_bars<=24 ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean(),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI BONUS — final_score come filtro (se colonna presente)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  ANALISI BONUS — FINAL_SCORE COME FILTRO")
print(SECTION)

for label, df_orig, n_yr in [("1h", df1, N_YEAR_1H), ("5m", df5, N_YEAR_5M)]:
    df = df_orig.dropna(subset=["final_score"]).copy()
    print(f"\n  {label}  final_score range: [{df['final_score'].min():.1f},{df['final_score'].max():.1f}]")
    print(f"  {'Score':>12} {'n':>5} {'avg_r':>7} {'WR%':>6}")
    print(f"  {'-'*38}")
    buckets = list(range(0, 101, 10))
    for lo, hi in zip(buckets[:-1], buckets[1:]):
        sub = df[(df["final_score"] >= lo) & (df["final_score"] < hi)]
        if len(sub) == 0:
            continue
        r = stats_row(sub, f"[{lo},{hi})")
        print(f"  {r['label']:>12} {r['n']:>5} {r['avg_r']:>+7.4f} {r['wr']:>6.1f}%")

    best_thr, best_avg = None, -999
    for t in range(30, 80, 5):
        sub = df[df["final_score"] >= t]
        if len(sub) >= 30:
            a = sub["pnl_r"].mean()
            if a > best_avg:
                best_avg, best_thr = a, t
    if best_thr is not None:
        kept    = df[df["final_score"] >= best_thr]
        removed = df[df["final_score"] < best_thr]
        n_yr_new = n_yr * len(kept) / max(1, len(df))
        print(f"\n  Soglia ottima final_score >= {best_thr}: n={len(kept)} avg_r={kept['pnl_r'].mean():+.4f} "
              f"(rimossi={len(removed)} avg_r_rmv={removed['pnl_r'].mean():+.4f})")
        summary_rows.append(dict(
            label=f"AB final_score>={best_thr} ({label})",
            n_removed=len(removed), avg_r_removed=removed["pnl_r"].mean(),
            n_remaining=len(kept), avg_r_new=kept["pnl_r"].mean(),
            equity_new=equity_final(kept["pnl_r"].mean(), n_yr_new),
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# TABELLA FINALE
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SECTION)
print("  TABELLA RIEPILOGATIVA — TUTTI I FILTRI CANDIDATI")
print(SECTION)

# Aggiungi baseline
print(f"\n  Baseline 1h: n={len(df1)} avg_r={BASELINE_AVG_R_1H:+.4f} eq={BASELINE_EQ_1H:,.0f} EUR  ({N_YEAR_1H:.0f} t/a)")
print(f"  Baseline 5m: n={len(df5)} avg_r={BASELINE_AVG_R_5M:+.4f} eq={BASELINE_EQ_5M:,.0f} EUR  ({N_YEAR_5M:.0f} t/a)")
print()

# Header tabella
header = f"{'Filtro':<38} {'n_rmv':>6} {'r_rmv':>7} {'n_rest':>7} {'r_new':>7} {'eq_new':>9} {'delta_eq':>9}"
print(f"  {header}")
print(f"  {'-' * len(header)}")

for r in summary_rows:
    tag_1h = "1h" in r["label"]
    base_eq = BASELINE_EQ_1H if tag_1h else BASELINE_EQ_5M
    delta = r["equity_new"] - base_eq
    print(
        f"  {r['label']:<38} {r['n_removed']:>6} {r['avg_r_removed']:>+7.3f} "
        f"{r['n_remaining']:>7} {r['avg_r_new']:>+7.3f} {r['equity_new']:>9,.0f} {delta:>+9,.0f}"
    )

print()
print(SECTION)
print("  INTERPRETAZIONE E PRIORITÀ")
print(SECTION)
print("""
  Priorità di implementazione (impatto/rischio):
  1. ALTA — Filtri con delta_eq > +2,000 EUR e n_restanti > 200
  2. MEDIA — Filtri con delta_eq > +500 EUR e n_restanti > 100
  3. BASSA — Filtri che riducono n < 100 (rischio overfitting)

  REGOLA: un filtro è implementabile solo se:
    a) avg_r rimossi < 0 (i trade rimossi sono negativi, non neutri)
    b) n rimossi >= 20 (segnale statistico non rumore)
    c) n restanti >= 100 (sistema ancora liquido)
    d) p-value < 0.10 sul t-test avg_r rimossi vs 0
""")
