"""
Valutazione OOS dei 4 candidati: NIO, RIVN, DKNG, SOUN.

Filtri TRIPLO + Config D + spaccatura per anno.
Soglia promozione: avg_r D > +0.30R, n >= 30, OOS positivo.
"""
import os
import psycopg2
import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
import warnings; warnings.filterwarnings("ignore")

CSV_5M_CANDIDATES = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_candidates_v3.csv"
SLIP = 0.15
CANDIDATES = ["NIO", "RIVN", "DKNG", "SOUN"]
PATTERNS = {"double_bottom","double_top","macd_divergence_bull","macd_divergence_bear",
            "rsi_divergence_bull","rsi_divergence_bear"}

SEP = "=" * 88

def cr(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d

def eff_r_cfgd(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if mfe >= 2.5: lock = 2.0
    elif mfe >= 2.0: lock = 1.5
    elif mfe >= 1.5: lock = 1.0
    elif mfe >= 1.0: lock = 0.5
    elif mfe >= 0.5: lock = 0.0
    else: lock = -1.0
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        runner = max(lock, 0.5) if mfe < r2 else r2
        return 0.5*r1+0.5*runner
    if o in ("stop","stopped","sl"):
        return lock
    return pr


print(SEP)
print("  VALUTAZIONE OOS — 4 simboli candidati onboarding apr 2026")
print(SEP)

# ─── Carica + filtri base 5m ─────────────────────────────────────────────────
df_raw = pd.read_csv(CSV_5M_CANDIDATES)
df_raw["pattern_timestamp"] = pd.to_datetime(df_raw["pattern_timestamp"], utc=True)
df_raw["hour_et"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
df_raw["year"] = df_raw["pattern_timestamp"].dt.year
print(f"\n  Dataset 5m raw: {len(df_raw):,}")
print(f"  Range: {df_raw['pattern_timestamp'].min().date()} → {df_raw['pattern_timestamp'].max().date()}")

# Filtri base (NO MIDDAY ancora)
df_b = df_raw[
    df_raw["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df_raw["pattern_name"].isin(PATTERNS) &
    df_raw["provider"].isin(["alpaca"]) &
    (df_raw["pattern_strength"].fillna(0) >= 0.60) &
    df_raw["symbol"].isin(CANDIDATES) &
    (df_raw["hour_et"] >= 11) & (df_raw["hour_et"] <= 16) &
    (df_raw["risk_pct"] >= 0.50) & (df_raw["risk_pct"] <= 2.00)
].copy()
print(f"\n  Pool 4 candidati (filtri base): {len(df_b):,}")
for sym in CANDIDATES:
    n = (df_b["symbol"] == sym).sum()
    print(f"    {sym}: n={n}")

if len(df_b) == 0:
    print("\n  ⚠ Nessun trade dopo filtri base — uscita")
    raise SystemExit

# ─── JOIN DB per price_position_in_range ─────────────────────────────────────
print(f"\n  JOIN DB per PPR (filtro MIDDAY)...")
conn = psycopg2.connect(host="localhost", port=5432, user="postgres",
                        password="postgres", dbname="intraday_market_screener")
cur = conn.cursor()
keys = [(s,e,p,t) for s,e,p,t in zip(df_b["symbol"],df_b["exchange"],df_b["provider"],df_b["pattern_timestamp"])]
cur.execute("CREATE TEMP TABLE _kk (sym VARCHAR(32), ex VARCHAR(32), prov VARCHAR(32), ts TIMESTAMPTZ)")
execute_values(cur, "INSERT INTO _kk VALUES %s", keys, page_size=5000)
conn.commit()
cur.execute("""
  SELECT k.sym, k.ex, k.prov, k.ts, ci.price_position_in_range
  FROM _kk k LEFT JOIN candle_indicators ci
    ON ci.symbol=k.sym AND ci.exchange=k.ex AND ci.provider=k.prov
    AND ci.timeframe='5m' AND ci.timestamp=k.ts
""")
ppr_map = {(s,e,p,pd.Timestamp(t).tz_convert("UTC")): float(v) if v else None
           for s,e,p,t,v in cur.fetchall()}
conn.close()
df_b["ppr"] = [ppr_map.get((s,e,p,t.tz_convert("UTC"))) for s,e,p,t in
               zip(df_b["symbol"],df_b["exchange"],df_b["provider"],df_b["pattern_timestamp"])]
print(f"  PPR risolto per: {df_b['ppr'].notna().sum():,}/{len(df_b):,}")

# Filtro TRIPLO
def is_triplo(row):
    h = row["hour_et"]
    if h >= 15: return True
    if h < 11: return False
    if pd.isna(row["ppr"]): return False
    pos = row["ppr"]; d = str(row["direction"]).lower()
    return ((d=="bullish" and pos<=0.10) or (d=="bearish" and pos>=0.90))

df_b["triplo"] = df_b.apply(is_triplo, axis=1)
df = df_b[df_b["triplo"]].copy()
df["eff_d"] = df.apply(eff_r_cfgd, axis=1)
print(f"\n  Pool TRIPLO (post MIDDAY_F): {len(df):,}")
for sym in CANDIDATES:
    n = (df["symbol"] == sym).sum()
    print(f"    {sym}: n={n}")


# ─── Stats per simbolo ───────────────────────────────────────────────────────
print()
print(SEP)
print("  EDGE PER SIMBOLO (Config D, post-slip)")
print(SEP)
print(f"\n  {'Symbol':<7} {'n':>5} {'avg_r D':>9} {'WR':>7} {'TP2%':>6} {'TP1%':>6} {'STOP%':>6}  {'p25':>8} {'p75':>8}")
print("  " + "-"*86)
results_global = {}
for sym in CANDIDATES:
    sub = df[df["symbol"] == sym].copy()
    if len(sub) == 0:
        print(f"  {sym:<7} (no trade nel pool TRIPLO)")
        continue
    e = (sub["eff_d"] - SLIP).mean()
    wr = ((sub["eff_d"] - SLIP) > 0).mean() * 100
    p25 = (sub["eff_d"] - SLIP).quantile(0.25)
    p75 = (sub["eff_d"] - SLIP).quantile(0.75)
    vc = sub["outcome"].value_counts(normalize=True)
    print(f"  {sym:<7} {len(sub):>5} {e:>+9.4f} {wr:>6.1f}% "
          f"{vc.get('tp2',0)*100:>5.1f}% {vc.get('tp1',0)*100:>5.1f}% {vc.get('stop',0)*100:>5.1f}% "
          f"{p25:>+8.4f} {p75:>+8.4f}")
    results_global[sym] = {"n": len(sub), "eff": e, "wr": wr}


# ─── Edge per anno ───────────────────────────────────────────────────────────
print()
print(SEP)
print("  EDGE PER ANNO (focus OOS 2026)")
print(SEP)
print(f"\n  {'Symbol':<7} {'2024':>16} {'2025':>16} {'2026 OOS':>16}  {'Stab?':<8}")
print("  " + "-"*78)
for sym in CANDIDATES:
    sub = df[df["symbol"] == sym]
    cells = []; vals = []
    for y in (2024, 2025, 2026):
        s = sub[sub["year"] == y]
        if len(s) < 5:
            cells.append(f"n/a (n={len(s)})".rjust(16))
            vals.append(None)
        else:
            v = (s["eff_d"]-SLIP).mean()
            cells.append(f"{v:+.4f} (n={len(s)})".rjust(16))
            vals.append(v)
    valid = [v for v in vals if v is not None]
    if not valid:
        stab = "no data"
    elif vals[2] is not None and vals[2] >= 0.30:
        stab = "OOS ok"
    elif vals[2] is not None and vals[2] >= 0:
        stab = "OOS marg"
    else:
        stab = "OOS neg"
    print(f"  {sym:<7} {cells[0]} {cells[1]} {cells[2]}  {stab:<8}")


# ─── Confronto vs reference simboli attuali ──────────────────────────────────
print()
print(SEP)
print("  DECISIONE PROMOZIONE")
print(SEP)
print(f"\n  Soglia promozione: avg_r D > +0.30R | n >= 30 | OOS 2026 positivo (>0)")
print(f"\n  {'Symbol':<7} {'n':>5} {'eff':>9} {'WR':>7} {'OOS 2026':>11} {'Decisione':<22}")
print("  " + "-"*78)
to_promote = []
for sym in CANDIDATES:
    if sym not in results_global:
        print(f"  {sym:<7} (no trade)")
        continue
    r = results_global[sym]
    sub = df[df["symbol"] == sym]
    sub_oos = sub[sub["year"] == 2026]
    oos_v = (sub_oos["eff_d"]-SLIP).mean() if len(sub_oos) >= 5 else None
    oos_str = f"{oos_v:+.4f} (n={len(sub_oos)})" if oos_v is not None else f"n/a (n={len(sub_oos)})"

    promote = (r["eff"] > 0.30) and (r["n"] >= 30) and (oos_v is not None and oos_v > 0)
    decision = "PROMOTE" if promote else "BLOCK (insuff/neg)"
    if promote:
        to_promote.append(sym)
    print(f"  {sym:<7} {r['n']:>5} {r['eff']:>+9.4f} {r['wr']:>6.1f}% {oos_str:>11}  {decision:<22}")

print(f"\n  Simboli da promuovere: {to_promote}")

# Salva decisioni
out = {"to_promote": to_promote, "results": results_global}
import json
with open(r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_tmp_candidates\promotion_decision.json", "w") as f:
    json.dump({"to_promote": to_promote,
               "stats": {k: {"n": int(v["n"]), "eff": float(v["eff"]), "wr": float(v["wr"])}
                         for k, v in results_global.items()}}, f, indent=2)
print(f"  Decisione salvata in: research/datasets/_tmp_candidates/promotion_decision.json")
