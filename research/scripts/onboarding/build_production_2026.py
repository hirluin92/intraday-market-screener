"""
Applica filtri production al val_1h_full_2026.csv → val_1h_production_2026.csv.
Stessi filtri di backend/build_production_dataset.py.
"""
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo

TZ_ET = ZoneInfo("America/New_York")

PRODUCTION_PATTERNS = frozenset({
    "double_top","double_bottom",
    "macd_divergence_bear","macd_divergence_bull",
    "rsi_divergence_bear","rsi_divergence_bull",
})

INP = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_full_2026.csv"
OUT = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production_2026.csv"

def hour_et(ts):
    return ts.astimezone(TZ_ET).hour

raw = pd.read_csv(INP)
raw["pattern_timestamp"] = pd.to_datetime(raw["pattern_timestamp"], utc=True)
n_raw = len(raw)
print(f"Dataset grezzo: {n_raw:,}")
print(f"Range: {raw['pattern_timestamp'].min()} → {raw['pattern_timestamp'].max()}")

# Filtri identici a build_production_dataset.py
df = raw[raw["entry_filled"].astype(str).str.lower().isin(["true","1"])].copy()
print(f"Dopo entry_filled: {len(df):,}")

df = df[df["pattern_name"].isin(PRODUCTION_PATTERNS)].copy()
print(f"Dopo 6 pattern: {len(df):,}")

df["hour_et"] = df["pattern_timestamp"].apply(hour_et)
df = df[~df["hour_et"].isin([3, 9])].copy()
print(f"Dopo no 03/09 ET: {len(df):,}")

df = df[(df["pattern_strength"] >= 0.60) & (df["pattern_strength"] < 0.80)].copy()
print(f"Dopo strength [0.60,0.80): {len(df):,}")

df = df[df["risk_pct"] <= 1.5].copy()
print(f"Dopo risk_pct <= 1.5%: {len(df):,}")

if "bars_to_entry" in df.columns:
    df = df[df["bars_to_entry"] <= 4].copy()
    print(f"Dopo bars_to_entry <= 4: {len(df):,}")

df.to_csv(OUT, index=False)
print(f"\nSalvato: {OUT}")
print(f"Range finale: {df['pattern_timestamp'].min()} → {df['pattern_timestamp'].max()}")
print(f"avg_r: {df['pnl_r'].mean():+.4f}R | WR: {(df['pnl_r']>0).mean()*100:.1f}%")

# Spaccatura per anno
df["year"] = df["pattern_timestamp"].dt.year
print("\nPer anno:")
for y, g in df.groupby("year"):
    print(f"  {y}: n={len(g):,} | avg_r={g['pnl_r'].mean():+.4f}R | WR={(g['pnl_r']>0).mean()*100:.1f}%")
