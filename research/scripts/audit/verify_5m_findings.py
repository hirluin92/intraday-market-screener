"""
VERIFICA finding audit 5m sul pool TRIPLO REALE (non raw).

Filtri TRIPLO produzione (replica esatta opportunity_validator.py):
  - provider = alpaca
  - timeframe = 5m
  - 6 pattern validati (no engulfing)
  - hour ET >= 11
  - 11-14 ET: price_position_in_range <= 0.10 (bull) OR >= 0.90 (bear) — MIDDAY_F
  - 15-16 ET: nessun filtro estremo (ALPHA)
  - pattern_strength >= 0.60
  - risk_pct in [0.50, 2.00]
  - simboli in VALIDATED_SYMBOLS_ALPACA_5M
  - regime SPY (skipped here — proxy via direction post-2026 stable)

Verifiche:
  1. TP fisso vs runner Config C (su pool TRIPLO + simulazione corretta)
  2. risk_pct < 0.50: confermare che è già scartato
  3. final_score >= 85 sul pool TRIPLO
  4. double_bottom 2024/2025/2026 sul pool TRIPLO
"""
from __future__ import annotations
import os
import psycopg2
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

CSV_5M = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv"
SLIP   = 0.15

PATTERNS_5M = {
    "double_bottom","double_top",
    "macd_divergence_bull","macd_divergence_bear",
    "rsi_divergence_bull","rsi_divergence_bear",
}
VALIDATED_SYMBOLS_ALPACA_5M = {
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
    "MU","LUNR","CAT","GS",
}
# Note: WMT è rimosso ad apr 2026 da opportunity_validator
SYMBOLS_BLOCKED_ALPACA_5M = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL"}
VALIDATED_SYMBOLS_ALPACA_5M = VALIDATED_SYMBOLS_ALPACA_5M - SYMBOLS_BLOCKED_ALPACA_5M

SEP  = "=" * 82
SEP2 = "-" * 82

# ─── eff_r SPLIT (config attuale: 50/50 TP1+runner +0.5R) ─────────────────────
def cr1(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d
def cr2(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d

def eff_r_split_runner(row):
    """Config attuale: 50% TP1 + 50% runner (+0.5R fisso se r1>=1)."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr1(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr2(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1 + 0.5*r2
    if o=="tp1":
        rn = 0.5 if r1>=1.0 else (0.0 if r1>=0.5 else -1.0)
        return 0.5*r1 + 0.5*rn
    if o in ("stop","stopped","sl"): return -1.0
    return pr

def eff_r_full_tp1(row):
    """Config alt: chiusura completa al TP1 (no runner, no TP2)."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr1(row["entry_price"],row["stop_price"],row["tp1_price"])
    if o in ("tp1","tp2"): return r1
    if o in ("stop","stopped","sl"): return -1.0
    return pr

def eff_r_config_c_trailing(row):
    """
    Config C trailing (auto_execute_service):
      - +0.50R MFE: stop sale a breakeven
      - +1.00R MFE: stop sale a entry+0.5R (locked)
    Position-sizing: 50% chiude a TP1, 50% runner con Config C trailing.

    Simulazione runner usando mfe_r e mae_r dal dataset:
      - Se MFE < 0.50: runner mai trailato → outcome originale stop o tp1+pos2 dipende
      - Se 0.50 <= MFE < 1.0: trailing breakeven attivo. Runner exit a 0R o TP2.
      - Se MFE >= 1.0: trailing +0.5R locked. Runner exit a +0.5R o TP2.
    """
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r", 0) or 0)
    mae=float(row.get("mae_r", 0) or 0)
    r1=cr1(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr2(row["entry_price"],row["stop_price"],row["tp2_price"])

    # Pos1 (50%): chiude a TP1 standard
    if o == "tp2":
        # Pos1 ha già fatto TP1, pos2 va fino a TP2 (trailing non triggera prima)
        return 0.5*r1 + 0.5*r2
    if o == "tp1":
        # Pos1 chiude a TP1 (=r1). Pos2 runner con Config C.
        # Runner exit dipende da MFE post-TP1: se ha visto >=tp2 esce a tp2,
        # altrimenti esce al lock (assumendo r1 ~ 1-2R, mfe>=1 quasi sempre).
        if mfe >= r2:
            runner = r2
        elif mfe >= 1.0:
            runner = 0.5  # locked
        elif mfe >= 0.5:
            runner = 0.0  # breakeven
        else:
            runner = -1.0
        return 0.5*r1 + 0.5*runner
    if o in ("stop","stopped","sl"):
        # Sia pos1 che pos2 stoppate. Ma se MFE >= 0.5, il trailing avrebbe protetto.
        if mfe >= 1.0:
            return 0.5  # entrambe locked +0.5R prima dello stop
        if mfe >= 0.5:
            return 0.0  # entrambe a breakeven
        return -1.0
    if o == "timeout":
        # Timeout: usa pnl_r del dataset come proxy
        return pr
    return pr


# ─── Carica dataset 5m ────────────────────────────────────────────────────────
print(SEP)
print("  VERIFICA FINDING 5m SUL POOL TRIPLO REALE")
print(SEP)

df = pd.read_csv(CSV_5M)
df["pattern_timestamp"] = pd.to_datetime(df["pattern_timestamp"], utc=True)
print(f"  Dataset raw: {len(df):,} righe | range {df['pattern_timestamp'].min().date()} → {df['pattern_timestamp'].max().date()}")

# Filtri base (no TRIPLO ancora)
df["hour_et"] = df["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
df_pre = df[
    df["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df["pattern_name"].isin(PATTERNS_5M) &
    df["provider"].isin(["alpaca"]) &
    (df["pattern_strength"].fillna(0) >= 0.60) &
    df["symbol"].isin(VALIDATED_SYMBOLS_ALPACA_5M)
].copy()
print(f"  Dopo filtri base (provider/pattern/symbol/strength): {len(df_pre):,}")

# Hour filter base (>=11, <=16)
df_pre = df_pre[(df_pre["hour_et"] >= 11) & (df_pre["hour_et"] <= 16)].copy()
print(f"  Dopo hour ET 11-16: {len(df_pre):,}")

# risk filter 5m: 0.50 <= risk_pct <= 2.00
df_pre["risk_pct_pct"] = df_pre["risk_pct"]  # assume già in %
# Nota: nel dataset risk_pct è in % già (0.557 = 0.557%)
n_below = (df_pre["risk_pct_pct"] < 0.50).sum()
n_above = (df_pre["risk_pct_pct"] > 2.00).sum()
df_risk = df_pre[(df_pre["risk_pct_pct"] >= 0.50) & (df_pre["risk_pct_pct"] <= 2.00)].copy()
print(f"  Filtro risk_pct in [0.50, 2.00]:  scartati < 0.50% = {n_below:,}, > 2.0% = {n_above:,}")
print(f"  Dopo risk filter: {len(df_risk):,}")

# ─── JOIN con DB per recuperare price_position_in_range ───────────────────────
print()
print("  Joining con DB per recuperare price_position_in_range...")
conn = psycopg2.connect(host="localhost", port=5432, user="postgres",
                        password="postgres", dbname="intraday_market_screener")
cur = conn.cursor()

# Query batch su (symbol, exchange, provider, timestamp)
keys = list(zip(df_risk["symbol"], df_risk["exchange"], df_risk["provider"],
                df_risk["pattern_timestamp"]))
print(f"  Keys da risolvere: {len(keys):,}")

# Tabella temporanea per JOIN efficiente
cur.execute("CREATE TEMP TABLE _audit_keys (sym VARCHAR(32), ex VARCHAR(32), prov VARCHAR(32), ts TIMESTAMPTZ)")
from psycopg2.extras import execute_values
execute_values(cur, "INSERT INTO _audit_keys VALUES %s",
               [(k[0], k[1], k[2], k[3]) for k in keys], page_size=5000)
conn.commit()

cur.execute("""
SELECT k.sym, k.ex, k.prov, k.ts, ci.price_position_in_range
FROM _audit_keys k
LEFT JOIN candle_indicators ci ON
  ci.symbol = k.sym AND ci.exchange = k.ex AND ci.provider = k.prov
  AND ci.timeframe = '5m' AND ci.timestamp = k.ts
""")
rows = cur.fetchall()
ppr_map = {}
for sym, ex, prov, ts, ppr in rows:
    if ppr is not None:
        ppr_map[(sym, ex, prov, ts)] = float(ppr)
conn.close()
print(f"  PPR risolto per {len(ppr_map):,} / {len(keys):,} trade ({len(ppr_map)/len(keys)*100:.1f}%)")

df_risk["ppr"] = [
    ppr_map.get((s, e, p, t), None)
    for s, e, p, t in zip(df_risk["symbol"], df_risk["exchange"],
                          df_risk["provider"], df_risk["pattern_timestamp"])
]

# ─── Applica MIDDAY_F: 11-14 ET solo se al estremo ────────────────────────────
def is_triplo_passed(row):
    h = row["hour_et"]
    if h < 11 or h > 16:
        return False
    if 15 <= h <= 16:
        return True  # ALPHA: nessun filtro
    # 11-14: MIDDAY_F
    if pd.isna(row["ppr"]):
        return False
    pos = row["ppr"]
    direction = str(row["direction"]).lower()
    if direction == "bullish" and pos <= 0.10:
        return True
    if direction == "bearish" and pos >= 0.90:
        return True
    return False

df_risk["triplo_pass"] = df_risk.apply(is_triplo_passed, axis=1)
df_triplo = df_risk[df_risk["triplo_pass"]].copy()
print(f"  Dopo filtro TRIPLO completo: {len(df_triplo):,}")

# Cumulativi
print(f"\n  CUMULATIVO:")
print(f"  raw → base → risk → TRIPLO  =  {len(df):,} → {len(df_pre):,} → {len(df_risk):,} → {len(df_triplo):,}")

# Calcola eff_r per le 3 config su entrambi i pool
for d in [df_risk, df_triplo]:
    d["eff_r_split"]  = d.apply(eff_r_split_runner, axis=1)
    d["eff_r_tp1"]    = d.apply(eff_r_full_tp1, axis=1)
    d["eff_r_cfgc"]   = d.apply(eff_r_config_c_trailing, axis=1)


# ═══ VERIFICA 1: TP fisso vs runner ═══════════════════════════════════════════
print()
print(SEP)
print("  VERIFICA 1 — TP fisso vs runner (Config C) sul POOL TRIPLO REALE")
print(SEP)

def cfg_stats(d, label):
    if len(d) == 0:
        return
    n = len(d)
    s_split = d["eff_r_split"]  - SLIP
    s_tp1   = d["eff_r_tp1"]    - SLIP
    s_cfgc  = d["eff_r_cfgc"]   - SLIP
    print(f"\n  {label} (n={n:,}):")
    print(f"  {'Config':<32} {'avg_r':>8} {'eff_r-slip':>10} {'WR':>6}")
    print("  " + "-"*60)
    print(f"  {'Split 50/50 + runner +0.5R':<32} "
          f"{d['eff_r_split'].mean():>+8.4f} {s_split.mean():>+10.4f} "
          f"{(s_split>0).mean()*100:>5.1f}%")
    print(f"  {'TP fisso 2.0R (chiudi tutto)':<32} "
          f"{d['eff_r_tp1'].mean():>+8.4f} {s_tp1.mean():>+10.4f} "
          f"{(s_tp1>0).mean()*100:>5.1f}%")
    print(f"  {'Split + Config C trailing':<32} "
          f"{d['eff_r_cfgc'].mean():>+8.4f} {s_cfgc.mean():>+10.4f} "
          f"{(s_cfgc>0).mean()*100:>5.1f}%")

cfg_stats(df_risk,   "Pool senza filtro MIDDAY (errato — l'audit precedente)")
cfg_stats(df_triplo, "Pool TRIPLO (vero, con MIDDAY_F applicato)")

# Spaccatura per fascia oraria su pool TRIPLO
print()
print("  Pool TRIPLO — spaccatura ALPHA (15-16) vs MIDDAY (11-14):")
df_alpha = df_triplo[df_triplo["hour_et"].isin([15, 16])]
df_mid   = df_triplo[df_triplo["hour_et"].isin([11, 12, 13, 14])]
for d, lab in [(df_alpha, "ALPHA 15-16"), (df_mid, "MIDDAY 11-14 (post filtro est.)")]:
    if len(d) == 0:
        continue
    s_split = (d["eff_r_split"] - SLIP).mean()
    s_tp1   = (d["eff_r_tp1"]   - SLIP).mean()
    s_cfgc  = (d["eff_r_cfgc"]  - SLIP).mean()
    print(f"    {lab:<35} n={len(d):,} | split={s_split:+.4f}  TP1_full={s_tp1:+.4f}  Cfg_C={s_cfgc:+.4f}")


# ═══ VERIFICA 2: risk_pct < 0.50 ══════════════════════════════════════════════
print()
print(SEP)
print("  VERIFICA 2 — risk_pct: in produzione MIN_RISK_PCT_5M = 0.50%")
print(SEP)
buckets_risk = [(0.0, 0.30), (0.30, 0.50), (0.50, 0.75),
                (0.75, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 99.0)]
print(f"\n  {'Bucket risk_pct':<18} {'n':>6} {'eff_split':>10} {'eff_tp1':>10} {'eff_cfgc':>10}  {'in TRIPLO?':<12}")
print("  " + "-"*72)
for lo, hi in buckets_risk:
    sub = df_pre[(df_pre["risk_pct"] >= lo) & (df_pre["risk_pct"] < hi)].copy()
    if len(sub) == 0:
        continue
    sub["eff_r_split"] = sub.apply(eff_r_split_runner, axis=1)
    sub["eff_r_tp1"]   = sub.apply(eff_r_full_tp1, axis=1)
    sub["eff_r_cfgc"]  = sub.apply(eff_r_config_c_trailing, axis=1)
    in_triplo = "SI" if (lo >= 0.50 and hi <= 2.0) else ("NO — scartato" if (hi <= 0.50 or lo >= 2.0) else "PARZIALE")
    print(f"  [{lo:.2f}, {hi:.2f})       {len(sub):>6} "
          f"{(sub['eff_r_split']-SLIP).mean():>+10.4f} "
          f"{(sub['eff_r_tp1']-SLIP).mean():>+10.4f} "
          f"{(sub['eff_r_cfgc']-SLIP).mean():>+10.4f}  {in_triplo}")

print(f"\n  → I trade con risk < 0.50% sono GIÀ scartati dal validator in produzione.")
print(f"     L'audit precedente li includeva — il finding 'cap risk < 0.5%' è già IN produzione.")


# ═══ VERIFICA 3: final_score >= 85 ═══════════════════════════════════════════
print()
print(SEP)
print("  VERIFICA 3 — final_score >= 85 sul POOL TRIPLO")
print(SEP)
score_buckets = [(0, 60), (60, 70), (70, 80), (80, 85), (85, 90), (90, 95), (95, 101)]
for d, lab in [(df_risk, "Pool senza MIDDAY_F (audit precedente)"),
               (df_triplo, "Pool TRIPLO (vero)")]:
    print(f"\n  {lab}:")
    print(f"  {'score bucket':<14} {'n':>6} {'eff_r_split-slip':>16} {'WR':>6}")
    print("  " + "-"*48)
    for lo, hi in score_buckets:
        sub = d[(d["final_score"] >= lo) & (d["final_score"] < hi)]
        if len(sub) == 0:
            continue
        ers = (sub["eff_r_split"] - SLIP).mean()
        wr  = ((sub["eff_r_split"] - SLIP) > 0).mean()*100
        print(f"  [{lo:>2}, {hi:>3})    {len(sub):>6} {ers:>+16.4f} {wr:>5.1f}%")


# ═══ VERIFICA 4: double_bottom degrado 2026 ══════════════════════════════════
print()
print(SEP)
print("  VERIFICA 4 — double_bottom degrado 2024/2025/2026 sul TRIPLO")
print(SEP)

for d, lab in [(df_risk, "Pool senza MIDDAY_F (audit precedente)"),
               (df_triplo, "Pool TRIPLO (vero)")]:
    print(f"\n  {lab}:")
    print(f"  {'pattern':<24} {'2024':>10} {'2025':>10} {'2026':>10}  {'stab?':<6}")
    print("  " + "-"*64)
    d_c = d.copy()
    d_c["year"] = d_c["pattern_timestamp"].dt.year
    for pat in sorted(PATTERNS_5M):
        sub = d_c[d_c["pattern_name"] == pat]
        if len(sub) == 0:
            continue
        ann = {}
        for y, g in sub.groupby("year"):
            if len(g) >= 30:
                ann[y] = (g["eff_r_split"] - SLIP).mean()
        out = []
        for y in [2024, 2025, 2026]:
            if y in ann:
                out.append(f"{ann[y]:+.4f}")
            else:
                out.append("    n/a")
        if all(y in ann for y in [2024, 2025, 2026]):
            stab = "STABILE" if min(ann.values()) > 0.10 else "DEGRADO"
        else:
            stab = "n/a"
        # Print con n
        ns = []
        for y in [2024, 2025, 2026]:
            ns.append(str((sub["pattern_timestamp"].dt.year == y).sum()))
        print(f"  {pat:<24} {out[0]:>10} {out[1]:>10} {out[2]:>10}  {stab:<6}  n=({','.join(ns)})")


# ═══ Hour-by-hour sul TRIPLO ═══════════════════════════════════════════════════
print()
print(SEP)
print("  EXTRA — eff_r per ora ET sul POOL TRIPLO")
print(SEP)
print(f"  {'hour':<6} {'n':>6} {'eff_split':>10} {'eff_tp1':>10} {'eff_cfgc':>10} {'WR':>6}")
print("  " + "-"*56)
for h in sorted(df_triplo["hour_et"].unique()):
    sub = df_triplo[df_triplo["hour_et"] == h]
    s_split = (sub["eff_r_split"] - SLIP).mean()
    s_tp1   = (sub["eff_r_tp1"]   - SLIP).mean()
    s_cfgc  = (sub["eff_r_cfgc"]  - SLIP).mean()
    wr = ((sub["eff_r_split"] - SLIP) > 0).mean()*100
    print(f"  {h:<6} {len(sub):>6} {s_split:>+10.4f} {s_tp1:>+10.4f} {s_cfgc:>+10.4f} {wr:>5.1f}%")


print()
print(SEP)
print("  CONCLUSIONI")
print(SEP)
print(f"  Pool TRIPLO valido: {len(df_triplo):,} trade (vs {len(df_risk):,} senza MIDDAY_F)")
print(f"  Riduzione MIDDAY_F: {(1 - len(df_triplo)/len(df_risk))*100:.1f}% di trade scartati")
