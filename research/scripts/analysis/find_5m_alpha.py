"""
find_5m_alpha.py
Profit-improvement opportunity hunter for the 5m strategy.

Reads val_5m_v2.csv, applies MC filters, computes eff_r-slip, and runs 19 analyses
to surface concrete, testable recommendations.
"""

from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.float_format", lambda x: f"{x:0.4f}")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_PATH = Path(r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv")
SLIP = 0.15
NY = ZoneInfo("America/New_York")

VALID_PATTERNS = {
    "double_bottom",
    "double_top",
    "macd_divergence_bull",
    "macd_divergence_bear",
    "rsi_divergence_bull",
    "rsi_divergence_bear",
}
ENTRY_FILLED_TRUE = {"true", "1", "True", "TRUE"}
HOURS_ET = {11, 12, 13, 14, 15}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def header(title: str) -> None:
    print()
    print("=" * 92)
    print(title)
    print("=" * 92)


def cr(e: float, s: float, t: float) -> float:
    if any(pd.isna(v) for v in (e, s, t)):
        return 0.0
    d = abs(e - s)
    return 0.0 if d < 1e-10 else abs(t - e) / d


def eff_r_row(row: pd.Series) -> float:
    o = str(row["outcome"]).lower()
    pr = float(row["pnl_r"]) if not pd.isna(row["pnl_r"]) else 0.0
    r1 = cr(row["entry_price"], row["stop_price"], row["tp1_price"])
    r2 = cr(row["entry_price"], row["stop_price"], row["tp2_price"])
    if o == "tp2":
        return 0.5 * r1 + 0.5 * r2
    if o == "tp1":
        rn = 0.5 if r1 >= 1.0 else (0.0 if r1 >= 0.5 else -1.0)
        return 0.5 * r1 + 0.5 * rn
    if o in ("stop", "stopped", "sl"):
        return -1.0
    return pr


def wilson_p(wins: int, n: int, base_p: float = 0.5) -> float:
    """Two-sided p-value vs H0: WR == base_p (normal approx)."""
    if n < 5:
        return float("nan")
    p = wins / n
    se = math.sqrt(base_p * (1 - base_p) / n)
    if se == 0:
        return float("nan")
    z = (p - base_p) / se
    # two-sided
    return float(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))))


def agg(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(group_cols, dropna=False)
    out = g.agg(
        n=("eff_r", "size"),
        wins=("is_win", "sum"),
        avg_r=("pnl_r", "mean"),
        avg_eff_r=("eff_r", "mean"),
        avg_eff_r_slip=("eff_r_slip", "mean"),
        sum_eff_r_slip=("eff_r_slip", "sum"),
    ).reset_index()
    out["WR"] = out["wins"] / out["n"]
    out["p"] = [wilson_p(int(w), int(n)) for w, n in zip(out["wins"], out["n"])]
    cols = group_cols + ["n", "WR", "avg_r", "avg_eff_r_slip", "sum_eff_r_slip", "p"]
    return out[cols].sort_values("avg_eff_r_slip", ascending=False)


def show(df: pd.DataFrame, top: int | None = None) -> None:
    if df.empty:
        print("(empty)")
        return
    if top:
        print(df.head(top).to_string(index=False))
    else:
        print(df.to_string(index=False))


def annotate(df: pd.DataFrame, group_cols: list[str], min_n: int = 50) -> None:
    if df.empty:
        return
    winners = df[(df["n"] >= min_n) & (df["avg_eff_r_slip"] > 0.30)]
    drags = df[(df["n"] >= min_n) & (df["avg_eff_r_slip"] < 0.10)]
    if not winners.empty:
        print(f"\n  WINNERS (n>={min_n}, eff_r-slip>0.30):")
        for _, r in winners.iterrows():
            label = " | ".join(f"{c}={r[c]}" for c in group_cols)
            print(f"    + {label}  n={int(r['n'])}  WR={r['WR']:.3f}  eff_r-slip={r['avg_eff_r_slip']:+.3f}")
    if not drags.empty:
        print(f"\n  DRAGS (n>={min_n}, eff_r-slip<0.10):")
        for _, r in drags.iterrows():
            label = " | ".join(f"{c}={r[c]}" for c in group_cols)
            print(f"    - {label}  n={int(r['n'])}  WR={r['WR']:.3f}  eff_r-slip={r['avg_eff_r_slip']:+.3f}")


# ---------------------------------------------------------------------------
# Load & filter
# ---------------------------------------------------------------------------
def load() -> pd.DataFrame:
    print(f"Loading {DATA_PATH} ...")
    df = pd.read_csv(DATA_PATH, low_memory=False)
    print(f"raw rows: {len(df):,}")

    # entry_filled
    df["entry_filled_str"] = df["entry_filled"].astype(str).str.strip()
    df = df[df["entry_filled_str"].isin(ENTRY_FILLED_TRUE)]

    df = df[df["pattern_name"].isin(VALID_PATTERNS)]
    df = df[df["provider"].astype(str).str.lower() == "alpaca"]
    df["pattern_strength"] = pd.to_numeric(df["pattern_strength"], errors="coerce")
    df = df[df["pattern_strength"] >= 0.60]

    # timestamp -> NY hour
    ts = pd.to_datetime(df["pattern_timestamp"], utc=True, errors="coerce")
    df = df.assign(_ts_utc=ts).dropna(subset=["_ts_utc"])
    df["_ts_ny"] = df["_ts_utc"].dt.tz_convert(NY)
    df["hour_et"] = df["_ts_ny"].dt.hour
    df["dow"] = df["_ts_ny"].dt.day_name()
    df["month"] = df["_ts_ny"].dt.month
    df["year"] = df["_ts_ny"].dt.year
    df = df[df["hour_et"].isin(HOURS_ET)]

    # numeric coercions
    for c in [
        "entry_price", "stop_price", "tp1_price", "tp2_price",
        "risk_pct", "pattern_quality_score", "screener_score", "final_score",
        "pnl_r", "bars_to_entry", "bars_to_exit", "volume_relative",
        "mfe_r", "mae_r", "bars_to_mfe", "pattern_candle_volume", "volume_sma20",
    ]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["outcome_l"] = df["outcome"].astype(str).str.lower()
    df["is_win"] = df["outcome_l"].isin(["tp1", "tp2"]).astype(int)

    # eff_r vectorised
    r1 = (df["tp1_price"] - df["entry_price"]).abs() / (df["entry_price"] - df["stop_price"]).abs().replace(0, np.nan)
    r2 = (df["tp2_price"] - df["entry_price"]).abs() / (df["entry_price"] - df["stop_price"]).abs().replace(0, np.nan)
    r1 = r1.fillna(0.0)
    r2 = r2.fillna(0.0)

    eff = pd.Series(0.0, index=df.index)
    is_tp2 = df["outcome_l"] == "tp2"
    is_tp1 = df["outcome_l"] == "tp1"
    is_stop = df["outcome_l"].isin(["stop", "stopped", "sl"])
    is_other = ~(is_tp2 | is_tp1 | is_stop)

    eff.loc[is_tp2] = 0.5 * r1.loc[is_tp2] + 0.5 * r2.loc[is_tp2]

    rn = pd.Series(-1.0, index=df.index)
    rn.loc[r1 >= 0.5] = 0.0
    rn.loc[r1 >= 1.0] = 0.5
    eff.loc[is_tp1] = 0.5 * r1.loc[is_tp1] + 0.5 * rn.loc[is_tp1]

    eff.loc[is_stop] = -1.0
    eff.loc[is_other] = df.loc[is_other, "pnl_r"].fillna(0.0)

    df["eff_r"] = eff
    df["eff_r_slip"] = df["eff_r"] - SLIP
    df["r1"] = r1
    df["r2"] = r2

    print(f"post-filter rows: {len(df):,}")
    print(
        f"date range: {df['_ts_ny'].min()} -> {df['_ts_ny'].max()}\n"
        f"unique symbols: {df['symbol'].nunique()}\n"
        f"unique patterns: {df['pattern_name'].nunique()}"
    )
    return df


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------
def a1_pattern(df: pd.DataFrame) -> pd.DataFrame:
    header("1) PATTERN_NAME — WR, eff_r-slip, n")
    out = agg(df, ["pattern_name"])
    show(out)
    annotate(out, ["pattern_name"])
    return out


def a2_hour(df: pd.DataFrame) -> pd.DataFrame:
    header("2) HOUR_ET (11..15) — edge per hour")
    out = agg(df, ["hour_et"])
    show(out)
    annotate(out, ["hour_et"])
    return out


def a3_pattern_hour(df: pd.DataFrame) -> pd.DataFrame:
    header("3) PATTERN x HOUR_ET — winning combos")
    out = agg(df, ["pattern_name", "hour_et"])
    show(out)
    annotate(out, ["pattern_name", "hour_et"], min_n=50)
    return out


def a4_direction(df: pd.DataFrame) -> pd.DataFrame:
    header("4) DIRECTION — bullish vs bearish asymmetry")
    out = agg(df, ["direction"])
    show(out)
    annotate(out, ["direction"], min_n=50)
    return out


def a5_symbol(df: pd.DataFrame) -> pd.DataFrame:
    header("5) SYMBOL — top/bottom 10 (n>=50)")
    out = agg(df, ["symbol"])
    out_n = out[out["n"] >= 50].copy()
    print("\nTOP 10 by eff_r-slip (n>=50):")
    show(out_n.sort_values("avg_eff_r_slip", ascending=False).head(10))
    print("\nBOTTOM 10 by eff_r-slip (n>=50):")
    show(out_n.sort_values("avg_eff_r_slip", ascending=True).head(10))

    print("\nALWAYS-POSITIVE symbols (every outcome with pnl_r>0 OR avg_eff_r_slip>0.5, n>=50):")
    if not out_n.empty:
        always = out_n[out_n["avg_eff_r_slip"] > 0.50].sort_values("avg_eff_r_slip", ascending=False)
        show(always.head(15))
    return out


def a6_strength(df: pd.DataFrame) -> pd.DataFrame:
    header("6) PATTERN_STRENGTH bucket")
    bins = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 1.01]
    labels = ["[0.60,0.65)", "[0.65,0.70)", "[0.70,0.75)", "[0.75,0.80)", "[0.80,0.85)", ">=0.85"]
    df = df.copy()
    df["strength_bucket"] = pd.cut(df["pattern_strength"], bins=bins, labels=labels, right=False, include_lowest=True)
    out = agg(df, ["strength_bucket"])
    show(out)
    annotate(out, ["strength_bucket"], min_n=50)
    return out


def a7_volrel(df: pd.DataFrame) -> pd.DataFrame:
    header("7) VOLUME_RELATIVE bucket")
    bins = [-1, 0.5, 1.0, 1.5, 2.0, 3.0, 1e9]
    labels = ["<0.5", "0.5-1", "1-1.5", "1.5-2", "2-3", ">3"]
    df = df.copy()
    df["volrel_bucket"] = pd.cut(df["volume_relative"], bins=bins, labels=labels)
    out = agg(df, ["volrel_bucket"])
    show(out)
    annotate(out, ["volrel_bucket"], min_n=50)
    return out


def a8_riskpct(df: pd.DataFrame) -> pd.DataFrame:
    header("8) RISK_PCT bucket")
    bins = [-1, 0.3, 0.5, 1.0, 1.5, 1e9]
    labels = ["<0.3", "0.3-0.5", "0.5-1", "1-1.5", ">1.5"]
    df = df.copy()
    df["risk_bucket"] = pd.cut(df["risk_pct"], bins=bins, labels=labels)
    out = agg(df, ["risk_bucket"])
    show(out)
    annotate(out, ["risk_bucket"], min_n=50)
    return out


def a9_bars_to_entry(df: pd.DataFrame) -> pd.DataFrame:
    header("9) BARS_TO_ENTRY (1, 2, 3+)")
    df = df.copy()
    df["bte"] = df["bars_to_entry"].clip(lower=1, upper=10).fillna(0).astype(int)
    out = agg(df, ["bte"])
    show(out.sort_values("bte"))
    annotate(out, ["bte"], min_n=50)
    return out


def a10_runner_left_table(df: pd.DataFrame) -> pd.DataFrame:
    header("10) MFE leftovers — TP1 outcomes that ran beyond")
    df_tp1 = df[df["outcome_l"] == "tp1"].copy()
    if df_tp1.empty:
        print("(no tp1 rows)")
        return pd.DataFrame()
    df_tp1["mfe_r"] = pd.to_numeric(df_tp1["mfe_r"], errors="coerce")
    n = len(df_tp1)
    over_2 = (df_tp1["mfe_r"] >= 2.0).sum()
    over_25 = (df_tp1["mfe_r"] >= 2.5).sum()
    over_3 = (df_tp1["mfe_r"] >= 3.0).sum()
    print(f"TP1 rows: {n}")
    print(f"  mfe_r >= 2.0: {over_2} ({over_2/n*100:.1f}%)")
    print(f"  mfe_r >= 2.5: {over_25} ({over_25/n*100:.1f}%)")
    print(f"  mfe_r >= 3.0: {over_3} ({over_3/n*100:.1f}%)")
    print(f"  mfe_r mean/median/p75/p90: {df_tp1['mfe_r'].mean():.3f} / "
          f"{df_tp1['mfe_r'].median():.3f} / {df_tp1['mfe_r'].quantile(0.75):.3f} / "
          f"{df_tp1['mfe_r'].quantile(0.90):.3f}")

    print("\nmfe_r distribution by outcome:")
    by_o = df.groupby("outcome_l")["mfe_r"].describe()[["count", "mean", "50%", "75%", "max"]]
    show(by_o.reset_index())
    return by_o


def a11_trailing(df: pd.DataFrame) -> None:
    header("11) TRAILING / ALT EXIT simulations vs current eff_r")

    have_mfe = df["mfe_r"].notna()
    base_eff = df["eff_r"].mean()
    base_eff_slip = df["eff_r_slip"].mean()
    print(f"baseline (current rules):  eff_r={base_eff:+.4f}  eff_r-slip={base_eff_slip:+.4f}  n={len(df)}")

    # alt 1: full close at TP1 (no runner)
    full_tp1 = pd.Series(0.0, index=df.index)
    is_tp1 = df["outcome_l"] == "tp1"
    is_tp2 = df["outcome_l"] == "tp2"
    is_stop = df["outcome_l"].isin(["stop", "stopped", "sl"])
    is_other = ~(is_tp1 | is_tp2 | is_stop)
    full_tp1.loc[is_tp1] = df.loc[is_tp1, "r1"]
    full_tp1.loc[is_tp2] = df.loc[is_tp2, "r1"]  # tp1 was hit en-route -> we close there
    full_tp1.loc[is_stop] = -1.0
    full_tp1.loc[is_other] = df.loc[is_other, "pnl_r"].fillna(0.0)
    print(f"alt full-close-at-TP1:     eff_r={full_tp1.mean():+.4f}  eff_r-slip={full_tp1.mean()-SLIP:+.4f}")

    # alt 2: BE after +1R (uses mfe_r, mae_r)
    # Logic: if mfe_r >= 1.0 -> stop moved to BE; from there: if final outcome was tp1/tp2 -> we collect r1/r2;
    # if outcome was stop after BE moved (mae_r vs mfe_r), runner = 0 instead of -1 for the runner half.
    # Approximation: half closed at TP1 (r1) when mfe>=1 (we assume r1>=1 typical), half:
    # - if outcome tp2: +r2
    # - else: 0 (BE)
    # If mfe_r < 1: same as baseline rule.
    be_eff = df["eff_r"].copy()
    mask_mfe1 = have_mfe & (df["mfe_r"] >= 1.0)
    # for rows where mfe>=1 and outcome is tp1: half=r1, half=0 (BE) instead of half=rn
    fix_tp1 = mask_mfe1 & is_tp1
    be_eff.loc[fix_tp1] = 0.5 * df.loc[fix_tp1, "r1"] + 0.5 * 0.0
    # tp2 unchanged (got both); stop with mfe>=1 -> half closed at r1 (assumed reachable since mfe>=1) + half BE = 0
    fix_stop_runup = mask_mfe1 & is_stop & (df["r1"] <= df["mfe_r"])
    be_eff.loc[fix_stop_runup] = 0.5 * df.loc[fix_stop_runup, "r1"] + 0.5 * 0.0
    print(f"alt BE-after-+1R:          eff_r={be_eff.mean():+.4f}  eff_r-slip={be_eff.mean()-SLIP:+.4f}")

    # alt 3: ATR-style trailing — proxy: take half mfe_r capped at 2R for the runner instead of fixed 0.5R
    atr_eff = df["eff_r"].copy()
    atr_runner = (df["mfe_r"].clip(lower=0.0, upper=3.0) * 0.6).fillna(0.0)  # captures ~60% of mfe up to 3R
    # only adjust tp1 and tp2 rows (entry happened, not stopped immediately)
    fix_tp1_atr = is_tp1 & have_mfe
    atr_eff.loc[fix_tp1_atr] = 0.5 * df.loc[fix_tp1_atr, "r1"] + 0.5 * atr_runner.loc[fix_tp1_atr].clip(lower=0.0)
    fix_tp2_atr = is_tp2 & have_mfe
    atr_eff.loc[fix_tp2_atr] = 0.5 * df.loc[fix_tp2_atr, "r1"] + 0.5 * atr_runner.loc[fix_tp2_atr]
    print(f"alt ATR-trail (60% mfe):   eff_r={atr_eff.mean():+.4f}  eff_r-slip={atr_eff.mean()-SLIP:+.4f}")


def a12_mae(df: pd.DataFrame) -> None:
    header("12) MAE — can the stop be tighter without losing winners?")
    wins = df[df["is_win"] == 1].copy()
    if wins.empty:
        print("(no winners)")
        return
    wins["mae_r"] = pd.to_numeric(wins["mae_r"], errors="coerce")
    desc = wins["mae_r"].describe(percentiles=[0.5, 0.75, 0.9, 0.95])
    print("MAE_R distribution among winners (tp1+tp2):")
    print(desc.to_string())
    for thr in [0.3, 0.5, 0.6, 0.7, 0.8]:
        survive = (wins["mae_r"].abs() <= thr).mean() * 100
        print(f"  stop @ -{thr:.2f}R would still keep {survive:.1f}% of winners")


def a13_tp_target(df: pd.DataFrame) -> None:
    header("13) Optimal TP target — fixed TP at 1.5R / 2R / 2.5R / 3R simulation")
    tp_targets = [1.5, 2.0, 2.5, 3.0]
    for t in tp_targets:
        # if mfe_r >= t -> +t else if mae_r <= -1 -> -1 else pnl_r
        if "mfe_r" not in df.columns:
            continue
        mfe = df["mfe_r"]
        mae = df["mae_r"]
        sim = pd.Series(np.nan, index=df.index)
        # outcome stop -> -1
        is_stop = df["outcome_l"].isin(["stop", "stopped", "sl"])
        sim.loc[is_stop] = -1.0
        # rest: if mfe>=t before being stopped, collect t; else if mae<=-1 collect -1; else pnl_r
        rest = ~is_stop
        cond_hit = rest & (mfe >= t)
        sim.loc[cond_hit] = t
        cond_stop = rest & ~cond_hit & (mae <= -1.0)
        sim.loc[cond_stop] = -1.0
        cond_other = rest & sim.isna()
        sim.loc[cond_other] = df.loc[cond_other, "pnl_r"].fillna(0.0)

        n = sim.notna().sum()
        eff_mean = sim.mean()
        wr = (sim > 0).mean()
        print(f"  fixed TP {t}R:  n={n}  mean_r={eff_mean:+.4f}  mean-slip={eff_mean-SLIP:+.4f}  WR={wr:.3f}")


def a14_quality(df: pd.DataFrame) -> pd.DataFrame:
    header("14) PATTERN_QUALITY_SCORE bucket")
    df = df.copy()
    df["q_bucket"] = pd.cut(df["pattern_quality_score"], bins=[-1, 30, 45, 55, 65, 75, 200], labels=["<30", "30-45", "45-55", "55-65", "65-75", ">=75"])
    out = agg(df, ["q_bucket"])
    show(out)
    annotate(out, ["q_bucket"], min_n=50)
    return out


def a15_finalscore(df: pd.DataFrame) -> pd.DataFrame:
    header("15) FINAL_SCORE bucket")
    df = df.copy()
    df["fs_bucket"] = pd.cut(df["final_score"], bins=[-1, 60, 70, 75, 80, 85, 200], labels=["<60", "60-70", "70-75", "75-80", "80-85", ">=85"])
    out = agg(df, ["fs_bucket"])
    show(out)
    annotate(out, ["fs_bucket"], min_n=50)
    return out


def a16_degradation(df: pd.DataFrame, top_patterns: list[str], top_symbols: list[str]) -> None:
    header("16) EDGE STABILITY by year (top 3 patterns + top 5 symbols)")
    df = df.copy()
    print("\nBy pattern x year (top 3 patterns):")
    sub = df[df["pattern_name"].isin(top_patterns)]
    out = agg(sub, ["pattern_name", "year"])
    show(out.sort_values(["pattern_name", "year"]))
    print("\nBy symbol x year (top 5 symbols):")
    sub = df[df["symbol"].isin(top_symbols)]
    out2 = agg(sub, ["symbol", "year"])
    show(out2.sort_values(["symbol", "year"]))


def a17_dow(df: pd.DataFrame) -> pd.DataFrame:
    header("17) DAY OF WEEK")
    out = agg(df, ["dow"])
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    out["__o"] = out["dow"].map({d: i for i, d in enumerate(order)}).fillna(99)
    out = out.sort_values("__o").drop(columns="__o")
    show(out)
    annotate(out, ["dow"], min_n=50)
    return out


def a18_month(df: pd.DataFrame) -> pd.DataFrame:
    header("18) MONTH (seasonality)")
    out = agg(df, ["month"])
    show(out.sort_values("month"))
    annotate(out, ["month"], min_n=50)
    return out


def a19_oos(df: pd.DataFrame) -> None:
    header("19) OOS 2026 — does the edge of top combos hold?")
    df_old = df[df["year"] < 2026]
    df_oos = df[df["year"] == 2026]
    print(f"  older n={len(df_old)}, OOS 2026 n={len(df_oos)}")

    # top combos by sample (n>=50) on the old set
    combo_old = df_old.groupby(["pattern_name", "hour_et", "symbol"]).agg(
        n=("eff_r_slip", "size"),
        eff_r_slip=("eff_r_slip", "mean"),
        wr=("is_win", "mean"),
    ).reset_index()
    combo_old = combo_old[(combo_old["n"] >= 50) & (combo_old["eff_r_slip"] > 0.30)].sort_values("eff_r_slip", ascending=False).head(20)

    if combo_old.empty:
        print("  no qualifying combos pre-2026 (n>=50, eff_r-slip>0.30).")
        # relax
        combo_old = df_old.groupby(["pattern_name", "hour_et", "symbol"]).agg(
            n=("eff_r_slip", "size"),
            eff_r_slip=("eff_r_slip", "mean"),
            wr=("is_win", "mean"),
        ).reset_index()
        combo_old = combo_old[combo_old["n"] >= 30].sort_values("eff_r_slip", ascending=False).head(20)
        print("  relaxed to n>=30:")

    rows = []
    for _, c in combo_old.iterrows():
        oos = df_oos[(df_oos["pattern_name"] == c["pattern_name"]) & (df_oos["hour_et"] == c["hour_et"]) & (df_oos["symbol"] == c["symbol"])]
        rows.append({
            "pattern": c["pattern_name"], "hour": int(c["hour_et"]), "symbol": c["symbol"],
            "n_old": int(c["n"]), "eff_r_slip_old": c["eff_r_slip"],
            "n_oos": len(oos),
            "eff_r_slip_oos": oos["eff_r_slip"].mean() if len(oos) else float("nan"),
            "wr_oos": oos["is_win"].mean() if len(oos) else float("nan"),
        })
    if rows:
        out = pd.DataFrame(rows)
        show(out)
        kept = out[out["eff_r_slip_oos"] > 0.20].dropna(subset=["eff_r_slip_oos"])
        broken = out[out["eff_r_slip_oos"] <= 0.0].dropna(subset=["eff_r_slip_oos"])
        print(f"\n  combos that held OOS (eff_r-slip>0.20 in 2026): {len(kept)}")
        print(f"  combos broken OOS (eff_r-slip<=0): {len(broken)}")


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------
def recommendations(df: pd.DataFrame, pattern_tab: pd.DataFrame, hour_tab: pd.DataFrame,
                    sym_tab: pd.DataFrame, dir_tab: pd.DataFrame,
                    strength_tab: pd.DataFrame, q_tab: pd.DataFrame,
                    fs_tab: pd.DataFrame, volrel_tab: pd.DataFrame,
                    risk_tab: pd.DataFrame) -> None:
    header("RACCOMANDAZIONI CONCRETE — impact estimates on the pool")

    base = df["eff_r_slip"].mean()
    print(f"baseline pool eff_r-slip = {base:+.4f}  (n={len(df)})")
    recs: list[str] = []

    # Drag patterns
    if not pattern_tab.empty:
        bad = pattern_tab[(pattern_tab["n"] >= 50) & (pattern_tab["avg_eff_r_slip"] < 0.10)]
        for _, r in bad.iterrows():
            new_pool = df[df["pattern_name"] != r["pattern_name"]]
            delta = new_pool["eff_r_slip"].mean() - base
            recs.append(
                f"DROP pattern '{r['pattern_name']}' (n={int(r['n'])}, eff_r-slip={r['avg_eff_r_slip']:+.3f}) "
                f"-> pool delta {delta:+.4f}"
            )

    # Drag hours
    if not hour_tab.empty:
        bad_hours = hour_tab[(hour_tab["n"] >= 50) & (hour_tab["avg_eff_r_slip"] < 0.10)]
        for _, r in bad_hours.iterrows():
            new_pool = df[df["hour_et"] != r["hour_et"]]
            delta = new_pool["eff_r_slip"].mean() - base
            recs.append(
                f"DROP hour_et={int(r['hour_et'])} (n={int(r['n'])}, eff_r-slip={r['avg_eff_r_slip']:+.3f}) "
                f"-> pool delta {delta:+.4f}"
            )

    # Drag symbols (the worst 5 with n>=50)
    if not sym_tab.empty:
        sym_bad = sym_tab[(sym_tab["n"] >= 50) & (sym_tab["avg_eff_r_slip"] < 0.05)].sort_values("avg_eff_r_slip").head(8)
        if not sym_bad.empty:
            symbols = sym_bad["symbol"].tolist()
            new_pool = df[~df["symbol"].isin(symbols)]
            delta = new_pool["eff_r_slip"].mean() - base
            recs.append(
                f"BLACKLIST symbols {symbols} -> pool delta {delta:+.4f}  "
                f"(removes {len(df)-len(new_pool)} trades)"
            )

    # Direction
    if not dir_tab.empty:
        worst_dir = dir_tab.sort_values("avg_eff_r_slip").head(1)
        if not worst_dir.empty and worst_dir.iloc[0]["avg_eff_r_slip"] < 0.10 and worst_dir.iloc[0]["n"] >= 50:
            d = worst_dir.iloc[0]["direction"]
            new_pool = df[df["direction"] != d]
            delta = new_pool["eff_r_slip"].mean() - base
            recs.append(f"DOWNWEIGHT direction='{d}' (eff_r-slip={worst_dir.iloc[0]['avg_eff_r_slip']:+.3f}) -> pool delta {delta:+.4f}")

    # Strength threshold
    if not strength_tab.empty:
        # find smallest strength bucket that exceeds 0.20
        good = strength_tab[strength_tab["avg_eff_r_slip"] > 0.20].sort_values("avg_eff_r_slip", ascending=False)
        if not good.empty:
            # raise threshold: keep only buckets >= best one's lower bound
            best_bucket = strength_tab.sort_values("avg_eff_r_slip", ascending=False).iloc[0]["strength_bucket"]
            recs.append(f"CHECK pattern_strength: best bucket={best_bucket}; consider raising min_strength.")

    # Quality
    if not q_tab.empty:
        worst_q = q_tab[(q_tab["n"] >= 50) & (q_tab["avg_eff_r_slip"] < 0.05)]
        for _, r in worst_q.iterrows():
            recs.append(f"FILTER pattern_quality_score in '{r['q_bucket']}' (n={int(r['n'])}, eff_r-slip={r['avg_eff_r_slip']:+.3f}) -> drop these")

    # Final score
    if not fs_tab.empty:
        worst_fs = fs_tab[(fs_tab["n"] >= 50) & (fs_tab["avg_eff_r_slip"] < 0.05)]
        for _, r in worst_fs.iterrows():
            new_pool = df[df["final_score"].fillna(0) >= 70]  # naive raise to 70
            delta = new_pool["eff_r_slip"].mean() - base
            recs.append(f"RAISE final_score floor: bucket '{r['fs_bucket']}' is a drag (eff_r-slip={r['avg_eff_r_slip']:+.3f}). Try min_final_score=70 -> pool delta {delta:+.4f}")
            break

    # Volume
    if not volrel_tab.empty:
        bad_vol = volrel_tab[(volrel_tab["n"] >= 50) & (volrel_tab["avg_eff_r_slip"] < 0.05)]
        for _, r in bad_vol.iterrows():
            recs.append(f"FILTER volume_relative bucket '{r['volrel_bucket']}' (n={int(r['n'])}, eff_r-slip={r['avg_eff_r_slip']:+.3f}) -> exclude")

    # Risk pct
    if not risk_tab.empty:
        bad_r = risk_tab[(risk_tab["n"] >= 50) & (risk_tab["avg_eff_r_slip"] < 0.05)]
        for _, r in bad_r.iterrows():
            recs.append(f"FILTER risk_pct bucket '{r['risk_bucket']}' (n={int(r['n'])}, eff_r-slip={r['avg_eff_r_slip']:+.3f}) -> exclude")

    if not recs:
        print("(no clear-cut drags; system already well-tuned vs filters analyzed)")
    else:
        for i, r in enumerate(recs, 1):
            print(f"{i:>2}. {r}")

    # Combined: drop worst pattern + worst symbols + worst hour
    print("\nCOMBINED 'easy wins' simulation:")
    keep = df.copy()
    kept_actions = []
    if not pattern_tab.empty:
        bad_pat = pattern_tab[(pattern_tab["n"] >= 50) & (pattern_tab["avg_eff_r_slip"] < 0.10)]["pattern_name"].tolist()
        if bad_pat:
            keep = keep[~keep["pattern_name"].isin(bad_pat)]
            kept_actions.append(f"drop patterns {bad_pat}")
    if not hour_tab.empty:
        bad_h = hour_tab[(hour_tab["n"] >= 50) & (hour_tab["avg_eff_r_slip"] < 0.10)]["hour_et"].tolist()
        if bad_h:
            keep = keep[~keep["hour_et"].isin(bad_h)]
            kept_actions.append(f"drop hours {bad_h}")
    if not sym_tab.empty:
        bad_s = sym_tab[(sym_tab["n"] >= 50) & (sym_tab["avg_eff_r_slip"] < 0.05)]["symbol"].tolist()
        if bad_s:
            keep = keep[~keep["symbol"].isin(bad_s)]
            kept_actions.append(f"drop symbols {bad_s}")
    if not q_tab.empty:
        bad_q = q_tab[(q_tab["n"] >= 50) & (q_tab["avg_eff_r_slip"] < 0.05)]["q_bucket"].astype(str).tolist()
        # we can't easily map back to numeric; skip in combined sim

    if kept_actions:
        new_eff = keep["eff_r_slip"].mean()
        delta = new_eff - base
        print(f"  actions: {kept_actions}")
        print(f"  remaining n={len(keep)} ({len(keep)/len(df)*100:.1f}% of pool)")
        print(f"  combined eff_r-slip={new_eff:+.4f}  (delta={delta:+.4f})")
    else:
        print("  no combined drag actions identified.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load()
    if df.empty:
        print("no rows after filters", file=sys.stderr)
        sys.exit(1)

    pat_tab = a1_pattern(df)
    hour_tab = a2_hour(df)
    a3_pattern_hour(df)
    dir_tab = a4_direction(df)
    sym_tab = a5_symbol(df)
    strength_tab = a6_strength(df)
    volrel_tab = a7_volrel(df)
    risk_tab = a8_riskpct(df)
    a9_bars_to_entry(df)
    a10_runner_left_table(df)
    a11_trailing(df)
    a12_mae(df)
    a13_tp_target(df)
    q_tab = a14_quality(df)
    fs_tab = a15_finalscore(df)

    # Top 3 patterns and top 5 symbols (by eff_r-slip with n>=50)
    if not pat_tab.empty:
        top3p = pat_tab.sort_values("avg_eff_r_slip", ascending=False).head(3)["pattern_name"].tolist()
    else:
        top3p = []
    sym_n = sym_tab[sym_tab["n"] >= 50] if not sym_tab.empty else pd.DataFrame()
    top5s = sym_n.sort_values("avg_eff_r_slip", ascending=False).head(5)["symbol"].tolist() if not sym_n.empty else []
    a16_degradation(df, top3p, top5s)
    a17_dow(df)
    a18_month(df)
    a19_oos(df)

    recommendations(df, pat_tab, hour_tab, sym_tab, dir_tab, strength_tab, q_tab, fs_tab, volrel_tab, risk_tab)


if __name__ == "__main__":
    main()
