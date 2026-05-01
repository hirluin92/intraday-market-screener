"""
AUDIT CATENA DI CALCOLO — verifica ogni singolo step del MC v5.

Step 1: dati raw 5 trade vs DB
Step 2: formula eff_r su 10 trade
Step 3: distribuzione outcome 2024 / 2025 / 2026
Step 4: frequenza trade reale per mese
Step 5: hold medio reale (slot cap check)
Step 6: compound mensile deterministico
Step 7: IS 2024 vs OOS 2025 con slot reali
"""
from __future__ import annotations
import os
import psycopg2
import numpy as np
import pandas as pd
from datetime import timedelta

# Connessione DB (via host port-forward 5432 → postgres container)
DB_HOST = os.getenv("DB_HOST_OUTSIDE", "localhost")
DB_PORT = int(os.getenv("DB_PORT_OUTSIDE", "5432"))

CSV_1H = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production.csv"
CSV_5M = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv"

SLIP   = 0.15
RISK_1H = 0.015
RISK_5M = 0.005
CAPITAL = 100_000.0

PATTERNS = {
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
}
ALL_5M_HOURS_ET = {11, 12, 13, 14, 15}
MIN_STRENGTH = 0.60

SEP = "=" * 78


# ─── eff_r v5 ────────────────────────────────────────────────────────────────
def compute_r_tp1(entry, stop, tp1):
    sd = abs(float(entry) - float(stop))
    return 0.0 if sd < 1e-10 else abs(float(tp1) - float(entry)) / sd

def compute_r_tp2(entry, stop, tp2):
    sd = abs(float(entry) - float(stop))
    return 0.0 if sd < 1e-10 else abs(float(tp2) - float(entry)) / sd

def eff_r(row) -> float:
    outcome = str(row["outcome"])
    pnl_r   = float(row["pnl_r"])
    r1 = compute_r_tp1(row["entry_price"], row["stop_price"], row["tp1_price"])
    r2 = compute_r_tp2(row["entry_price"], row["stop_price"], row["tp2_price"])
    if outcome == "tp2":
        return 0.5 * r1 + 0.5 * r2
    elif outcome == "tp1":
        runner = 0.5 if r1 >= 1.0 else (0.0 if r1 >= 0.5 else -1.0)
        return 0.5 * r1 + 0.5 * runner
    elif outcome in ("stop", "stopped", "sl"):
        return -1.0
    elif outcome == "timeout":
        return float(pnl_r)
    else:
        return float(pnl_r)


# ─── Carica dataset ──────────────────────────────────────────────────────────
print(SEP)
print("  CARICAMENTO DATASET")
print(SEP)

df1r = pd.read_csv(CSV_1H)
df1r["pattern_timestamp"] = pd.to_datetime(df1r["pattern_timestamp"], utc=True)
print(f"  1h raw: {len(df1r):,} righe | {df1r['pattern_timestamp'].min().date()} → {df1r['pattern_timestamp'].max().date()}")

df5r = pd.read_csv(CSV_5M)
df5r["pattern_timestamp"] = pd.to_datetime(df5r["pattern_timestamp"], utc=True)
df5r["hour_et"] = df5r["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
print(f"  5m raw: {len(df5r):,} righe | {df5r['pattern_timestamp'].min().date()} → {df5r['pattern_timestamp'].max().date()}")

# Filtri MC v5
df1 = df1r[
    df1r["entry_filled"].astype(str).str.lower().isin(["true", "1"]) &
    df1r["pattern_name"].isin(PATTERNS) &
    ~df1r["provider"].isin(["ibkr"]) &
    (df1r["pattern_strength"].fillna(0) >= MIN_STRENGTH)
].copy()
df5 = df5r[
    df5r["entry_filled"].astype(str).str.lower().isin(["true", "1"]) &
    df5r["pattern_name"].isin(PATTERNS) &
    df5r["provider"].isin(["alpaca"]) &
    df5r["hour_et"].isin(ALL_5M_HOURS_ET) &
    (df5r["pattern_strength"].fillna(0) >= MIN_STRENGTH)
].copy()
df1["eff_r"] = df1.apply(eff_r, axis=1)
df5["eff_r"] = df5.apply(eff_r, axis=1)
print(f"  1h filtered: {len(df1):,} | 5m filtered: {len(df5):,}")
print()


# ═══ STEP 1: DATI RAW vs DB ════════════════════════════════════════════════════
print(SEP)
print("  STEP 1 — VERIFICA DATI RAW vs DATABASE (5 trade specifici)")
print(SEP)

# Prendi 5 trade con outcome variati e simboli in DB
sample_ids = []
for outcome in ["tp1", "tp2", "stop", "timeout", "tp1"]:
    sub = df1[df1["outcome"] == outcome]
    if len(sub):
        sample_ids.append(sub.iloc[len(sub)//2]["opportunity_id"])

samples = df1[df1["opportunity_id"].isin(sample_ids)].copy()
print(f"  Trade campionati: {len(samples)}")
print()

try:
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT,
                            user="postgres", password="postgres",
                            dbname="intraday_market_screener")
    cur = conn.cursor()

    print(f"  {'sym':<6} {'tf':<3} {'pattern_ts':<20} {'entry_csv':>10} {'close_db':>10} {'match':>6} "
          f"{'stop_csv':>9} {'atr_db':>8} {'stop_dist_R':>11} {'outcome':>8}")
    print("  " + "-"*108)

    for _, r in samples.iterrows():
        sym  = r["symbol"]
        tf   = r["timeframe"]
        ts   = r["pattern_timestamp"]
        prov = r["provider"]
        ent  = float(r["entry_price"])
        stp  = float(r["stop_price"])
        out  = r["outcome"]

        # close della candela del pattern
        cur.execute("""
            SELECT c.close, ci.atr_14
            FROM candles c
            LEFT JOIN candle_indicators ci ON ci.candle_id = c.id
            WHERE c.symbol=%s AND c.timeframe=%s AND c.timestamp=%s AND c.provider=%s
            LIMIT 1
        """, (sym, tf, ts, prov))
        row = cur.fetchone()
        if row is None:
            print(f"  {sym:<6} {tf:<3} {str(ts):<20}  (NON TROVATO IN DB)")
            continue
        close_db, atr_db = float(row[0]), float(row[1]) if row[1] else None
        match = "OK" if abs(close_db - ent) < 0.01 else "DIFF"
        atr_s = f"{atr_db:.4f}" if atr_db else "—"
        if atr_db:
            stop_dist_atr = abs(ent - stp) / atr_db
            stop_dist_R = f"{stop_dist_atr:.2f}xATR"
        else:
            stop_dist_R = "—"
        print(f"  {sym:<6} {tf:<3} {str(ts)[:19]:<20} {ent:>10.4f} {close_db:>10.4f} {match:>6} "
              f"{stp:>9.4f} {atr_s:>8} {stop_dist_R:>11} {out:>8}")

    print()
    print("  Verifica TP1/TP2 risk multiples:")
    print(f"  {'sym':<6} {'entry':>10} {'stop':>9} {'tp1':>10} {'tp2':>10} {'r_tp1':>6} {'r_tp2':>6} {'outcome':>8}")
    print("  " + "-"*78)
    for _, r in samples.iterrows():
        ent = float(r["entry_price"]); stp=float(r["stop_price"])
        tp1 = float(r["tp1_price"]); tp2=float(r["tp2_price"])
        r1 = compute_r_tp1(ent, stp, tp1)
        r2 = compute_r_tp2(ent, stp, tp2)
        print(f"  {r['symbol']:<6} {ent:>10.4f} {stp:>9.4f} {tp1:>10.4f} {tp2:>10.4f} "
              f"{r1:>6.2f} {r2:>6.2f} {r['outcome']:>8}")

    print()
    print("  Verifica outcome dalla candela successiva:")
    print(f"  {'sym':<6} {'pattern_ts':<20} {'next_high':>10} {'next_low':>10} {'tp1':>10} {'stop':>9} {'predicted':>10} {'csv':>8}")
    print("  " + "-"*98)
    for _, r in samples.iterrows():
        sym=r["symbol"]; tf=r["timeframe"]; ts=r["pattern_timestamp"]; prov=r["provider"]
        direction = r["direction"]
        cur.execute("""
            SELECT high, low, close FROM candles
            WHERE symbol=%s AND timeframe=%s AND provider=%s AND timestamp > %s
            ORDER BY timestamp ASC LIMIT 5
        """, (sym, tf, prov, ts))
        rows = cur.fetchall()
        if not rows:
            continue
        # Considera solo le prime barre per check
        max_h = max(float(x[0]) for x in rows)
        min_l = min(float(x[1]) for x in rows)
        tp1=float(r["tp1_price"]); stp=float(r["stop_price"])
        if direction == "bullish":
            hit_tp1 = max_h >= tp1
            hit_stop = min_l <= stp
        else:
            hit_tp1 = min_l <= tp1
            hit_stop = max_h >= stp
        if hit_tp1 and not hit_stop:
            pred = "tp1+"
        elif hit_stop and not hit_tp1:
            pred = "stop"
        elif hit_tp1 and hit_stop:
            pred = "ambig"
        else:
            pred = "open"
        print(f"  {sym:<6} {str(ts)[:19]:<20} {max_h:>10.4f} {min_l:>10.4f} {tp1:>10.4f} {stp:>9.4f} {pred:>10} {r['outcome']:>8}")

    conn.close()
except Exception as e:
    print(f"  ERRORE DB: {e}")


# ═══ STEP 2: FORMULA eff_r ═════════════════════════════════════════════════════
print()
print(SEP)
print("  STEP 2 — VERIFICA FORMULA eff_r")
print(SEP)

# Esempi sintetici
print("  Esempi sintetici (entry=$100, stop=$98, tp1=$104, tp2=$107):")
ex_tp1 = {"entry_price":100, "stop_price":98, "tp1_price":104, "tp2_price":107, "outcome":"tp1", "pnl_r":2.0}
ex_tp2 = {"entry_price":100, "stop_price":98, "tp1_price":104, "tp2_price":107, "outcome":"tp2", "pnl_r":3.5}
ex_st  = {"entry_price":100, "stop_price":98, "tp1_price":104, "tp2_price":107, "outcome":"stop", "pnl_r":-1.0}
print(f"    tp1: r1={compute_r_tp1(100,98,104)}, eff_r={eff_r(ex_tp1):.4f}, after slip={eff_r(ex_tp1)-SLIP:.4f}R")
print(f"         atteso: 0.5*2.0 + 0.5*0.5 = 1.25R, dopo slip 1.10R")
print(f"    tp2: r1=2.0, r2=3.5, eff_r={eff_r(ex_tp2):.4f}, after slip={eff_r(ex_tp2)-SLIP:.4f}R")
print(f"         atteso: 0.5*2.0 + 0.5*3.5 = 2.75R, dopo slip 2.60R")
print(f"    stop: eff_r={eff_r(ex_st):.4f}, after slip={eff_r(ex_st)-SLIP:.4f}R")
print(f"         atteso: -1.0R, dopo slip -1.15R")

print()
print("  10 trade reali dal dataset 1h (eff_r vs verifica manuale):")

real = []
for outcome, n in [("tp1", 5), ("tp2", 2), ("stop", 2), ("timeout", 1)]:
    sub = df1[df1["outcome"] == outcome].head(n)
    real.append(sub)
real = pd.concat(real)

print(f"  {'sym':<6} {'outcome':<8} {'r1':>5} {'r2':>5} {'pnl_r_csv':>9} {'eff_r':>7} {'after_slip':>10} {'check':>9}")
print("  " + "-"*72)
for _, r in real.iterrows():
    e=float(r["entry_price"]); s=float(r["stop_price"])
    t1=float(r["tp1_price"]); t2=float(r["tp2_price"])
    r1=compute_r_tp1(e,s,t1); r2=compute_r_tp2(e,s,t2)
    er = eff_r(r); ers = er - SLIP
    # ricalcolo manuale
    if r["outcome"] == "tp1":
        runner = 0.5 if r1 >= 1.0 else (0.0 if r1 >= 0.5 else -1.0)
        manual = 0.5*r1 + 0.5*runner
    elif r["outcome"] == "tp2":
        manual = 0.5*r1 + 0.5*r2
    elif r["outcome"] == "stop":
        manual = -1.0
    else:
        manual = float(r["pnl_r"])
    chk = "OK" if abs(manual - er) < 1e-6 else "FAIL"
    print(f"  {r['symbol']:<6} {r['outcome']:<8} {r1:>5.2f} {r2:>5.2f} {float(r['pnl_r']):>9.4f} "
          f"{er:>7.4f} {ers:>10.4f} {chk:>9}")


# ═══ STEP 3: DISTRIBUZIONE OUTCOME ═════════════════════════════════════════════
print()
print(SEP)
print("  STEP 3 — DISTRIBUZIONE OUTCOME PER ANNO")
print(SEP)

def stats(df, label):
    if len(df) == 0:
        return {"label": label, "n": 0, "tp2": 0, "tp1": 0, "stop": 0, "timeout": 0,
                "wr": 0, "avg_r": 0, "eff_r_slip": 0}
    vc = df["outcome"].value_counts(normalize=True)
    pool = (df["eff_r"] - SLIP).values if "eff_r" in df.columns else np.array([0.0])
    return {
        "label": label,
        "n": len(df),
        "tp2": vc.get("tp2", 0),
        "tp1": vc.get("tp1", 0),
        "stop": vc.get("stop", 0),
        "timeout": vc.get("timeout", 0),
        "wr": (pool > 0).mean(),
        "avg_r": df["pnl_r"].mean(),
        "eff_r_slip": pool.mean(),
    }

df1["year"] = df1["pattern_timestamp"].dt.year
df5["year"] = df5["pattern_timestamp"].dt.year

print("  1h:")
print(f"  {'periodo':<14} {'n':>6} {'tp2':>6} {'tp1':>6} {'stop':>6} {'tmo':>6} {'WR':>6} {'avg_r':>7} {'eff-slip':>8}")
print("  " + "-"*72)
rows = [stats(df1, "completo")]
for y in sorted(df1["year"].unique()):
    rows.append(stats(df1[df1["year"]==y], str(y)))
for s in rows:
    print(f"  {s['label']:<14} {s['n']:>6} {s['tp2']:>5.1%} {s['tp1']:>5.1%} {s['stop']:>5.1%} "
          f"{s['timeout']:>5.1%} {s['wr']:>5.1%} {s['avg_r']:>+7.4f} {s['eff_r_slip']:>+8.4f}")

print()
print("  5m:")
print(f"  {'periodo':<14} {'n':>6} {'tp2':>6} {'tp1':>6} {'stop':>6} {'tmo':>6} {'WR':>6} {'avg_r':>7} {'eff-slip':>8}")
print("  " + "-"*72)
rows = [stats(df5, "completo")]
for y in sorted(df5["year"].unique()):
    rows.append(stats(df5[df5["year"]==y], str(y)))
for s in rows:
    print(f"  {s['label']:<14} {s['n']:>6} {s['tp2']:>5.1%} {s['tp1']:>5.1%} {s['stop']:>5.1%} "
          f"{s['timeout']:>5.1%} {s['wr']:>5.1%} {s['avg_r']:>+7.4f} {s['eff_r_slip']:>+8.4f}")


# ═══ STEP 4: FREQUENZA TRADE ════════════════════════════════════════════════════
print()
print(SEP)
print("  STEP 4 — FREQUENZA TRADE PER MESE (varianza)")
print(SEP)

df1["ym"] = df1["pattern_timestamp"].dt.to_period("M")
df5["ym"] = df5["pattern_timestamp"].dt.to_period("M")

print("  1h — trade per mese:")
print(f"  {'mese':<10} {'n':>6} {'avg_r':>8} {'eff_r_slip':>10}")
print("  " + "-"*42)
m_stats_1h = []
for m, sub in df1.groupby("ym", sort=True):
    n = len(sub); ar = sub["pnl_r"].mean(); ers = (sub["eff_r"]-SLIP).mean()
    m_stats_1h.append((str(m), n, ar, ers))
    print(f"  {str(m):<10} {n:>6} {ar:>+8.4f} {ers:>+10.4f}")
ns_1h = [r[1] for r in m_stats_1h]
print(f"  → MEDIA {np.mean(ns_1h):.1f}/mese | MEDIANA {np.median(ns_1h):.1f}/mese | "
      f"MIN {min(ns_1h)} | MAX {max(ns_1h)} | STD {np.std(ns_1h):.1f}")

print()
print("  5m — trade per mese:")
print(f"  {'mese':<10} {'n':>6} {'avg_r':>8} {'eff_r_slip':>10}")
print("  " + "-"*42)
m_stats_5m = []
for m, sub in df5.groupby("ym", sort=True):
    n = len(sub); ar = sub["pnl_r"].mean(); ers = (sub["eff_r"]-SLIP).mean()
    m_stats_5m.append((str(m), n, ar, ers))
    print(f"  {str(m):<10} {n:>6} {ar:>+8.4f} {ers:>+10.4f}")
ns_5m = [r[1] for r in m_stats_5m]
print(f"  → MEDIA {np.mean(ns_5m):.1f}/mese | MEDIANA {np.median(ns_5m):.1f}/mese | "
      f"MIN {min(ns_5m)} | MAX {max(ns_5m)} | STD {np.std(ns_5m):.1f}")


# ═══ STEP 5: HOLD MEDIO ════════════════════════════════════════════════════════
print()
print(SEP)
print("  STEP 5 — HOLD MEDIO REALE (slot cap check)")
print(SEP)

# bars_to_exit è già nel CSV
# 1h: bar = 1h, quindi bars_to_exit ≈ ore di hold
# 5m: bar = 5min, quindi bars_to_exit/12 = ore

print("  1h — hold (bars_to_exit, 1 bar = 1h):")
b1 = df1["bars_to_exit"].dropna()
print(f"    n={len(b1)} | media={b1.mean():.1f} bar = {b1.mean():.1f}h ≈ {b1.mean()/6.5:.2f} sessioni")
print(f"    mediana={b1.median():.1f} bar | p25={b1.quantile(0.25):.1f} | p75={b1.quantile(0.75):.1f}")
hold_h_1h = b1.mean()
hold_d_1h = hold_h_1h / 6.5  # 6.5h trading day
print(f"    Hold medio in giorni trading: {hold_d_1h:.2f}")
slot_cap_real_1h = round(3 * 21 / max(hold_d_1h, 0.5))
print(f"    Slot cap: 3 slot × 21gg / {hold_d_1h:.2f}gg = {slot_cap_real_1h}/mese")
print(f"    MC v5 usa: 21/mese (basato su hold=3gg)")

print()
print("  5m — hold (bars_to_exit, 1 bar = 5min):")
b5 = df5["bars_to_exit"].dropna()
print(f"    n={len(b5)} | media={b5.mean():.1f} bar = {b5.mean()*5:.0f} min = {b5.mean()*5/60:.2f}h")
print(f"    mediana={b5.median():.1f} bar | p25={b5.quantile(0.25):.1f} | p75={b5.quantile(0.75):.1f}")
hold_min_5m = b5.mean() * 5
hold_h_5m = hold_min_5m / 60
print(f"    Power Hours = 2h = 120min")
cycles_realtime = 120 / hold_min_5m if hold_min_5m > 0 else 0
print(f"    Cicli/giorno power hours: 120/{hold_min_5m:.0f} = {cycles_realtime:.2f}")
slot_cap_real_5m = round(2 * cycles_realtime * 21 * 0.5)  # 50% fill
print(f"    Slot cap: 2 slot × {cycles_realtime:.2f} cicli × 21gg × 50% fill = {slot_cap_real_5m}/mese")
print(f"    MC v5 usa: 84/mese (basato su 2 cicli/h)")


# ═══ STEP 6: COMPOUND DETERMINISTICO ═══════════════════════════════════════════
print()
print(SEP)
print("  STEP 6 — COMPOUND MENSILE DETERMINISTICO 12 mesi")
print(SEP)

n1m = 21
n5m = 84
ar1s = (df1["eff_r"] - SLIP).mean()
ar5s = (df5["eff_r"] - SLIP).mean()

eq = CAPITAL
print(f"  Capitale iniziale: €{eq:,.0f}")
print(f"  avg_r 1h (net slip): {ar1s:+.4f}R | avg_r 5m: {ar5s:+.4f}R")
print(f"  Trade/mese: 1h={n1m}, 5m={n5m}")
print(f"  Risk: 1h={RISK_1H*100}% / 5m={RISK_5M*100}%")
print()
print(f"  {'Mese':>4} {'risk_1h':>10} {'risk_5m':>10} {'pnl_1h':>10} {'pnl_5m':>10} {'pnl_tot':>10} {'eq_fine':>12}")
print("  " + "-"*72)
for m in range(1, 13):
    r1 = eq * RISK_1H
    r5 = eq * RISK_5M
    p1 = n1m * ar1s * r1
    p5 = n5m * ar5s * r5
    pt = p1 + p5
    eq2 = eq + pt
    print(f"  {m:>4} {r1:>10,.0f} {r5:>10,.0f} {p1:>+10,.0f} {p5:>+10,.0f} {pt:>+10,.0f} {eq2:>12,.0f}")
    eq = eq2

print(f"  → Capitale finale deterministico (12m, edge 100%): €{eq:,.0f} ({(eq/CAPITAL-1)*100:+.1f}%)")
print(f"  → MC v5 mediana atteso simile (~stesso ordine grandezza)")


# ═══ STEP 7: IS 2024 vs OOS 2025 ═══════════════════════════════════════════════
print()
print(SEP)
print("  STEP 7 — IS 2024 (training) vs OOS 2025 (test) — simulazione realistica")
print(SEP)

is_24 = df1[df1["year"] == 2024].copy()
oos_25 = df1[df1["year"] == 2025].copy()
oos_26 = df1[df1["year"] == 2026].copy()

def simulate_realistic(df_trades, slot_cap_per_month=21):
    """
    Simulazione realistica: ordina trade per timestamp, usa max slot_cap/mese.
    Approssimazione: prendi i primi N trade di ogni mese (cap) e sum eff_r-slip.
    """
    if len(df_trades) == 0:
        return {"n": 0, "n_capped": 0, "avg_r": 0, "tot_r": 0, "wr": 0}
    df_s = df_trades.sort_values("pattern_timestamp").copy()
    df_s["ym"] = df_s["pattern_timestamp"].dt.to_period("M")
    df_capped = df_s.groupby("ym", group_keys=False).head(slot_cap_per_month)
    pool = (df_capped["eff_r"] - SLIP).values
    return {
        "n": len(df_s),
        "n_capped": len(df_capped),
        "avg_r": pool.mean() if len(pool) else 0.0,
        "tot_r": pool.sum() if len(pool) else 0.0,
        "wr": (pool > 0).mean() if len(pool) else 0.0,
    }

def simulate_compound(df_trades, slot_cap_per_month=21, risk_pct=RISK_1H, capital=CAPITAL):
    """
    Compound mensile: applica sequenza reale trade con slot cap.
    """
    if len(df_trades) == 0:
        return capital, 0
    df_s = df_trades.sort_values("pattern_timestamp").copy()
    df_s["ym"] = df_s["pattern_timestamp"].dt.to_period("M")
    eq = capital
    n_used = 0
    for ym, group in df_s.groupby("ym", sort=True):
        group = group.head(slot_cap_per_month)
        risk_dollars = eq * risk_pct
        pnl = ((group["eff_r"] - SLIP) * risk_dollars).sum()
        eq += pnl
        n_used += len(group)
        if eq <= 0:
            return 0.0, n_used
    return eq, n_used

print("  Statistiche trade pool per anno (1h, già filtrato per pattern/strength/no-ibkr):")
print(f"  {'periodo':<10} {'n_tot':>6} {'WR':>6} {'avg_r':>8} {'eff_slip':>9}")
print("  " + "-"*42)
for label, df in [("IS 2024", is_24), ("OOS 2025", oos_25), ("OOS 2026", oos_26)]:
    if len(df):
        pool = (df["eff_r"] - SLIP).values
        wr = (pool > 0).mean()
        avg_r = df["pnl_r"].mean()
        ers = pool.mean()
        print(f"  {label:<10} {len(df):>6} {wr*100:>5.1f}% {avg_r:>+8.4f} {ers:>+9.4f}")
    else:
        print(f"  {label:<10} {0:>6}")

print()
print("  Simulazione realistica con slot cap 21/mese (1h):")
print(f"  {'periodo':<10} {'n_raw':>6} {'n_cap':>6} {'WR':>6} {'avg_r_slip':>10} {'tot_R':>9} "
      f"{'eq_finale':>12} {'rend':>8}")
print("  " + "-"*82)
for label, df in [("IS 2024", is_24), ("OOS 2025", oos_25), ("OOS 2026", oos_26)]:
    s = simulate_realistic(df, 21)
    eq_fin, n_used = simulate_compound(df, 21, RISK_1H, CAPITAL)
    rend = (eq_fin/CAPITAL-1)*100 if eq_fin > 0 else -100
    print(f"  {label:<10} {s['n']:>6} {s['n_capped']:>6} {s['wr']*100:>5.1f}% "
          f"{s['avg_r']:>+10.4f} {s['tot_r']:>+9.2f} {eq_fin:>12,.0f} {rend:>+7.1f}%")


print()
print(SEP)
print("  AUDIT COMPLETATO")
print(SEP)
