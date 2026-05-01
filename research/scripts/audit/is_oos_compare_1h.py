"""
Confronto IS 2023-2025 vs OOS nov 2025 - apr 2026 sul 1h.

Usa val_1h_production_2026.csv (rigenerato con holdout=0).
"""
import pandas as pd
import numpy as np

INP = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production_2026.csv"

PATTERNS = {
    "double_bottom","double_top",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
}
SLIP = 0.15

def cr1(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d
def cr2(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d
def eff_r(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr1(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr2(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        rn=0.5 if r1>=1.0 else (0.0 if r1>=0.5 else -1.0)
        return 0.5*r1+0.5*rn
    if o in ("stop","stopped","sl"): return -1.0
    return pr

df = pd.read_csv(INP)
df["pattern_timestamp"] = pd.to_datetime(df["pattern_timestamp"], utc=True)
df = df[
    df["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df["pattern_name"].isin(PATTERNS) &
    ~df["provider"].isin(["ibkr"]) &
    (df["pattern_strength"].fillna(0) >= 0.60)
].copy()
df["eff_r"] = df.apply(eff_r, axis=1)
df["eff_r_slip"] = df["eff_r"] - SLIP

print("="*80)
print("  CONFRONTO IS vs OOS sul 1h — dataset rigenerato")
print("="*80)
print(f"\n  Range dataset: {df['pattern_timestamp'].min()} → {df['pattern_timestamp'].max()}")
print(f"  Trade totali (filtri MC): {len(df):,}")

OOS_FROM = pd.Timestamp("2025-11-01", tz="UTC")
df_is  = df[df["pattern_timestamp"] <  OOS_FROM]
df_oos = df[df["pattern_timestamp"] >= OOS_FROM]

print()
print(f"  {'Periodo':<28} {'n':>6} {'avg_r':>8} {'eff_r':>8} {'eff_r-slip':>10} {'WR':>6}")
print("  " + "-"*72)

def stats(d, lab):
    if len(d)==0:
        return f"  {lab:<28} {0:>6}"
    ar=d["pnl_r"].mean()
    er=d["eff_r"].mean()
    ers=d["eff_r_slip"].mean()
    wr=(d["eff_r_slip"]>0).mean()*100
    return f"  {lab:<28} {len(d):>6} {ar:>+8.4f} {er:>+8.4f} {ers:>+10.4f} {wr:>5.1f}%"

print(stats(df_is, "2023-2025 (IS, pre-Nov25)"))
print(stats(df_oos, "Nov 2025 - Apr 2026 (OOS)"))

# Spaccatura mensile OOS
print()
print("  OOS detailed (mensile):")
print(f"  {'mese':<10} {'n':>6} {'avg_r':>8} {'eff_r-slip':>10} {'WR':>6}")
print("  " + "-"*48)
df_oos_c = df_oos.copy()
df_oos_c["ym"] = df_oos_c["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
for ym, g in df_oos_c.groupby("ym", sort=True):
    print(f"  {str(ym):<10} {len(g):>6} {g['pnl_r'].mean():>+8.4f} "
          f"{(g['eff_r']-SLIP).mean():>+10.4f} {((g['eff_r']-SLIP)>0).mean()*100:>5.1f}%")

# Spaccatura per anno (full)
df["year"] = df["pattern_timestamp"].dt.year
print()
print("  Per anno (tutto):")
print(f"  {'anno':<6} {'n':>6} {'avg_r':>8} {'eff_r-slip':>10} {'WR':>6}")
print("  " + "-"*44)
for y, g in df.groupby("year"):
    print(f"  {y:<6} {len(g):>6} {g['pnl_r'].mean():>+8.4f} "
          f"{(g['eff_r']-SLIP).mean():>+10.4f} {((g['eff_r']-SLIP)>0).mean()*100:>5.1f}%")

# Outcome mix IS vs OOS
print()
print("  Distribuzione outcome:")
print(f"  {'periodo':<28} {'tp2':>6} {'tp1':>6} {'stop':>6} {'tmo':>6}")
print("  " + "-"*58)
def outc(d, lab):
    if len(d)==0:
        return f"  {lab:<28}"
    vc=d["outcome"].value_counts(normalize=True)
    return f"  {lab:<28} {vc.get('tp2',0)*100:>5.1f}% {vc.get('tp1',0)*100:>5.1f}% {vc.get('stop',0)*100:>5.1f}% {vc.get('timeout',0)*100:>5.1f}%"
print(outc(df_is,  "IS (2023-2025)"))
print(outc(df_oos, "OOS (nov 2025 - apr 2026)"))

# Edge ratio
if len(df_oos)>0 and len(df_is)>0:
    e_is  = (df_is["eff_r"]-SLIP).mean()
    e_oos = (df_oos["eff_r"]-SLIP).mean()
    print()
    print("="*80)
    print(f"  EDGE OOS/IS: {e_oos/e_is*100:.1f}%  (haircut da applicare al MC)")
    if e_oos/e_is > 0.85:
        print("  ✓ STABILE: edge tiene in OOS (>85%) — i numeri MC sono credibili")
    elif e_oos/e_is > 0.50:
        print("  ⚠ DEGRADO MODERATO: 50-85% — applicare haircut nel MC")
    else:
        print("  ✗ DEGRADO FORTE: <50% — il sistema non funziona OOS")
    print("="*80)
