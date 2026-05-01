"""
RICERCA ESAUSTIVA — 31 miglioramenti possibili al sistema TRIPLO.

Test sul pool TRIPLO REALE con MC light (1000 sim) per velocità.
Ordina i risultati per impatto stimato sul profitto.
"""
from __future__ import annotations
import os, numpy as np, pandas as pd, psycopg2
from psycopg2.extras import execute_values
import warnings; warnings.filterwarnings("ignore")

CSV_5M = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_5m_v2.csv"
CSV_1H = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\val_1h_production_2026.csv"
PPR_CACHE = r"C:\Lavoro\Trading\intraday-market-screener\research\datasets\_ppr_cache_5m.parquet"
SLIP = 0.15
RISK_1H_DEFAULT = 0.015
RISK_5M_DEFAULT = 0.005
CAPITAL = 100_000.0
SLOT_5M = 48
SLOT_1H = 66
SEP = "=" * 96
SEP2 = "-" * 96

PATTERNS = {"double_bottom","double_top","macd_divergence_bull","macd_divergence_bear",
            "rsi_divergence_bull","rsi_divergence_bear"}
SYMBOLS_BLOCKED_5M = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL"}
VAL_SYMS_5M = {"GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL","ACHR","ASTS","JOBY",
    "RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX","NVO","LLY","MRNA","NKE","TGT","MP",
    "NEM","WMT","MU","LUNR","CAT","GS"} - SYMBOLS_BLOCKED_5M

# ─── eff_r helpers ────────────────────────────────────────────────────────────
def cr(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d

def eff_r_split(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        rn=0.5 if r1>=1.0 else (0.0 if r1>=0.5 else -1.0)
        return 0.5*r1+0.5*rn
    if o in ("stop","stopped","sl"): return -1.0
    return pr

def eff_r_cfgc(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    if o=="tp2": return 0.5*r1+0.5*r2
    if o=="tp1":
        if mfe>=r2: runner=r2
        elif mfe>=1.0: runner=0.5
        elif mfe>=0.5: runner=0.0
        else: runner=-1.0
        return 0.5*r1+0.5*runner
    if o in ("stop","stopped","sl"):
        if mfe>=1.0: return 0.5
        if mfe>=0.5: return 0.0
        return -1.0
    return pr

def eff_r_cfgd(row):
    """Config D: trail progressivo +0.5R steps. BE@+0.5, lock+0.5@+1.0, lock+1.0@+1.5, lock+1.5@+2.0, lock+2.0@+2.5"""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    # Lock corrispondente al MFE raggiunto (steps di 0.5R)
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

def eff_r_split_ratio(row, ratio_tp1=0.5):
    """Split TP1/runner variabile. ratio_tp1=0.5 default. Resto va al runner Config C."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    r2=cr(row["entry_price"],row["stop_price"],row["tp2_price"])
    rr = 1.0 - ratio_tp1
    if o=="tp2": return ratio_tp1*r1 + rr*r2
    if o=="tp1":
        if mfe>=r2: runner=r2
        elif mfe>=1.0: runner=0.5
        elif mfe>=0.5: runner=0.0
        else: runner=-1.0
        return ratio_tp1*r1 + rr*runner
    if o in ("stop","stopped","sl"):
        if mfe>=1.0: return 0.5
        if mfe>=0.5: return 0.0
        return -1.0
    return pr

def eff_r_tp2_custom(row, tp2_mult=3.5):
    """Config C trailing ma TP2 custom level (default 3.5R)."""
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    r1=cr(row["entry_price"],row["stop_price"],row["tp1_price"])
    if o=="tp2":
        # Outcome TP2 originale, ma se mfe < custom_tp2, exit a runner_lock
        if mfe >= tp2_mult: return 0.5*r1 + 0.5*tp2_mult
        elif mfe >= 1.0: return 0.5*r1 + 0.5*0.5
        return 0.5*r1 + 0.5*0.0
    if o=="tp1":
        if mfe >= tp2_mult: runner = tp2_mult
        elif mfe>=1.0: runner=0.5
        elif mfe>=0.5: runner=0.0
        else: runner=-1.0
        return 0.5*r1+0.5*runner
    if o in ("stop","stopped","sl"):
        if mfe>=1.0: return 0.5
        if mfe>=0.5: return 0.0
        return -1.0
    return pr


# ─── Pool builder ─────────────────────────────────────────────────────────────
print(SEP)
print("  RICERCA ESAUSTIVA — 31 miglioramenti TRIPLO 5m")
print(SEP)

df_raw = pd.read_csv(CSV_5M)
df_raw["pattern_timestamp"] = pd.to_datetime(df_raw["pattern_timestamp"], utc=True)
df_raw["hour_et"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
df_raw["minute_et"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.minute
df_raw["dow"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.dayofweek

df_b = df_raw[
    df_raw["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df_raw["pattern_name"].isin(PATTERNS) &
    df_raw["provider"].isin(["alpaca"]) &
    (df_raw["pattern_strength"].fillna(0) >= 0.60) &
    df_raw["symbol"].isin(VAL_SYMS_5M) &
    (df_raw["hour_et"] >= 11) & (df_raw["hour_et"] <= 16) &
    (df_raw["risk_pct"] >= 0.50) & (df_raw["risk_pct"] <= 2.00)
].copy()

# Merge PPR cache
df_ppr = pd.read_parquet(PPR_CACHE)
df_b = df_b.merge(df_ppr, on=["symbol","exchange","provider","pattern_timestamp"], how="left")

def is_triplo(row):
    h = row["hour_et"]
    if h >= 15: return True
    if h < 11: return False
    if pd.isna(row["ppr"]): return False
    pos = row["ppr"]; d = str(row["direction"]).lower()
    return ((d=="bullish" and pos<=0.10) or (d=="bearish" and pos>=0.90))

df_b["triplo"] = df_b.apply(is_triplo, axis=1)
df = df_b[df_b["triplo"]].copy()
df["eff_r_split"] = df.apply(eff_r_split, axis=1)
df["eff_r_cfgc"]  = df.apply(eff_r_cfgc,  axis=1)
df["eff_r_cfgd"]  = df.apply(eff_r_cfgd,  axis=1)
df["year"] = df["pattern_timestamp"].dt.year

print(f"\n  Pool TRIPLO 5m: {len(df):,} trade")
print(f"  Range: {df['pattern_timestamp'].min().date()} → {df['pattern_timestamp'].max().date()}")
baseline_eff = (df["eff_r_cfgc"] - SLIP).mean()
baseline_wr  = ((df["eff_r_cfgc"] - SLIP) > 0).mean() * 100
print(f"  Baseline: eff_r-slip={baseline_eff:+.4f}R | WR={baseline_wr:.1f}%")


# ─── 1h pool per MC ───────────────────────────────────────────────────────────
df1 = pd.read_csv(CSV_1H)
df1["pattern_timestamp"] = pd.to_datetime(df1["pattern_timestamp"], utc=True)
df1 = df1[
    df1["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df1["pattern_name"].isin(PATTERNS) &
    ~df1["provider"].isin(["ibkr"]) &
    (df1["pattern_strength"].fillna(0) >= 0.60)
].copy()
df1["eff_r_split"] = df1.apply(eff_r_split, axis=1)
df1["year"] = df1["pattern_timestamp"].dt.year


# ─── MC engine veloce ─────────────────────────────────────────────────────────
def build_blocks(d, slot_cap, eff_col):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for _, sub in d.groupby("ym", sort=True):
        sub = sub.head(slot_cap)
        if len(sub) > 0:
            blocks.append((sub[eff_col]-SLIP).values)
    return blocks

blocks_1h_baseline = build_blocks(df1, SLOT_1H, "eff_r_split")
blocks_5m_baseline = build_blocks(df, SLOT_5M, "eff_r_cfgc")

def run_mc(b1, b5, ra=RISK_1H_DEFAULT, rb=RISK_5M_DEFAULT, nsim=1000, seed=42):
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim)
    have_a = len(b1)>0; have_b = len(b5)>0
    ia = np.arange(len(b1)); ib = np.arange(len(b5))
    for i in range(nsim):
        eq = CAPITAL
        for _ in range(12):
            r_a = eq*ra; r_b = eq*rb; pnl=0.0
            if have_a: pnl += (b1[rng.choice(ia)]*r_a).sum()
            if have_b: pnl += (b5[rng.choice(ib)]*r_b).sum()
            eq = max(0, eq+pnl)
        finals[i] = eq
    return dict(med=np.median(finals), p05=np.percentile(finals,5),
                p95=np.percentile(finals,95), prob=(finals>CAPITAL).mean())

mc_baseline = run_mc(blocks_1h_baseline, blocks_5m_baseline, nsim=2000)
print(f"  MC baseline (€100k 12m, 2000 sim): mediana=€{mc_baseline['med']:,.0f}")
print()

# Storage per ranking finale
results = []  # (label, n, eff, delta_eff, mc_med, delta_mc, note)


def add_result(label, n, eff, mc_med=None, note=""):
    delta_eff = eff - baseline_eff if eff is not None else None
    delta_mc = (mc_med/mc_baseline["med"]-1)*100 if mc_med else None
    results.append((label, n, eff, delta_eff, mc_med, delta_mc, note))


# ─── JOIN per regime SPY 1d, ATR, SPY trend intraday ─────────────────────────
print(SEP)
print("  Caricamento dati extra dal DB (regime, ATR, SPY intraday)")
print(SEP)
conn = psycopg2.connect(host="localhost", port=5432, user="postgres",
                        password="postgres", dbname="intraday_market_screener")
cur = conn.cursor()

# Regime SPY 1d (market_regime alla pattern_timestamp)
cur.execute("""
SELECT timestamp, market_regime, volatility_regime
FROM candle_contexts
WHERE symbol='SPY' AND timeframe='1d'
ORDER BY timestamp
""")
spy_regime = pd.DataFrame(cur.fetchall(), columns=["ts","regime","vol_regime"])
spy_regime["ts"] = pd.to_datetime(spy_regime["ts"], utc=True)
print(f"  SPY 1d regimes: {len(spy_regime):,}")

def lookup_regime(ts):
    ts = pd.Timestamp(ts).tz_convert("UTC").normalize()
    row = spy_regime[spy_regime["ts"] <= ts].tail(1)
    if len(row) == 0: return ("neutral", "normal")
    return (row.iloc[0]["regime"], row.iloc[0]["vol_regime"])

df["spy_regime"], df["spy_vol_regime"] = zip(*df["pattern_timestamp"].map(lookup_regime))

# SPY trend intraday: confronto SPY close 30 min prima vs 2h prima → trend short-term
# Faccio una query batch per ottenere SPY 5m close
cur.execute("""
SELECT timestamp, close FROM candles
WHERE symbol='SPY' AND timeframe='5m' AND provider='alpaca'
  AND timestamp >= '2023-07-01' AND timestamp <= '2026-05-01'
ORDER BY timestamp
""")
spy5 = pd.DataFrame(cur.fetchall(), columns=["ts","close"])
spy5["ts"] = pd.to_datetime(spy5["ts"], utc=True)
spy5["close"] = spy5["close"].astype(float)
spy5 = spy5.sort_values("ts").reset_index(drop=True)
print(f"  SPY 5m candele: {len(spy5):,}")

# Per ogni trade, trova trend SPY ultimi 24 bar (2h)
spy5_idx = pd.Series(spy5.index, index=spy5["ts"])
def spy_trend_2h(ts):
    """Ritorna +1 (up), 0 (flat), -1 (down) per SPY ultime 2 ore."""
    try:
        # Trova bar precedente o uguale
        loc = spy5_idx.asof(ts)
        if pd.isna(loc): return 0
        loc = int(loc)
        if loc < 24: return 0
        c_now = spy5.iloc[loc]["close"]
        c_2h  = spy5.iloc[loc-24]["close"]
        change = (c_now - c_2h) / c_2h
        if change > 0.002: return 1
        if change < -0.002: return -1
        return 0
    except: return 0

print("  Calcolo SPY trend 2h per ogni trade...")
df["spy_trend_2h"] = df["pattern_timestamp"].map(spy_trend_2h)

# ATR 5m al pattern timestamp (se disponibile)
print("  Caricamento ATR 5m...")
keys = [(s, e, p, t) for s, e, p, t in zip(df["symbol"], df["exchange"], df["provider"], df["pattern_timestamp"])]
cur.execute("CREATE TEMP TABLE _kk (sym VARCHAR(32), ex VARCHAR(32), prov VARCHAR(32), ts TIMESTAMPTZ)")
execute_values(cur, "INSERT INTO _kk VALUES %s", keys, page_size=5000)
conn.commit()
cur.execute("""
  SELECT k.sym, k.ex, k.prov, k.ts, ci.atr_14
  FROM _kk k LEFT JOIN candle_indicators ci
    ON ci.symbol=k.sym AND ci.exchange=k.ex AND ci.provider=k.prov
    AND ci.timeframe='5m' AND ci.timestamp=k.ts
""")
atr_rows = cur.fetchall()
atr_map = {(s,e,p,pd.Timestamp(t).tz_convert("UTC")): float(a) if a else None for s,e,p,t,a in atr_rows}
df["atr_14"] = [atr_map.get((s,e,p,t.tz_convert("UTC")), None)
                for s,e,p,t in zip(df["symbol"],df["exchange"],df["provider"],df["pattern_timestamp"])]
df["atr_pct"] = df["atr_14"] / df["entry_price"] * 100  # ATR% prezzo

conn.close()
print(f"  ATR risolto per: {df['atr_14'].notna().sum():,}/{len(df):,}")
print()


# ═══════════════════════════════════════════════════════════════════════════════
# A. SLOT / CONCURRENCY (1, 9, 19, 21)
# ═══════════════════════════════════════════════════════════════════════════════
print(SEP)
print("  A. SLOT / CONCURRENCY")
print(SEP)

# #1: SLOT 3+2 vs alternative
print("\n  [#1] SLOT cap diversi (5m, 1h, totale)")
print(f"  {'config':<28} {'5m_slot_cap':>12} {'eff_5m':>10} {'mc_med':>13} {'Δmc':>8}")
for slot_cap_5m in [SLOT_5M, 24, 48, 72, 96, 200]:
    blocks_5m_x = build_blocks(df, slot_cap_5m, "eff_r_cfgc")
    mc = run_mc(blocks_1h_baseline, blocks_5m_x, nsim=1000)
    n_used = sum(len(b) for b in blocks_5m_x)
    avg_eff = np.mean([b.mean() for b in blocks_5m_x])
    delta = (mc["med"]/mc_baseline["med"]-1)*100
    print(f"  cap_5m = {slot_cap_5m:<22}  {n_used:>12} {avg_eff:>+10.4f} €{mc['med']:>11,.0f} {delta:>+7.1f}%")

# Trade lost per slot pieni (n/mese median sopra cap)
df_m = df.copy()
df_m["ym"] = df_m["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
ns = df_m.groupby("ym").size()
print(f"\n  Trade/mese 5m (mediano): {ns.median():.0f} | sopra cap 48: {(ns>48).sum()}/{len(ns)} mesi")
print(f"  Trade in eccesso (lost se cap 48): {max(0, (ns - 48).sum()):.0f}")

# #9: anti-correlation max LONG / max SHORT simultanei
print("\n  [#9] Correlazione direzionale (max LONG/SHORT al giorno)")
df_d = df.copy()
df_d["date"] = df_d["pattern_timestamp"].dt.date
daily_dir = df_d.groupby(["date", "direction"]).size().unstack(fill_value=0)
print(f"  Giorni con >2 LONG simultanei: {(daily_dir.get('bullish',0) > 2).sum()}")
print(f"  Giorni con >2 SHORT simultanei: {(daily_dir.get('bearish',0) > 2).sum()}")

# Filtro: max 2 stesso direzione → simula
def filter_max_per_dir(d, max_per_dir=2):
    d = d.sort_values("pattern_timestamp").copy()
    d["date"] = d["pattern_timestamp"].dt.date
    out = []
    for date, g in d.groupby("date"):
        for direction, gg in g.groupby("direction"):
            out.append(gg.head(max_per_dir))
    return pd.concat(out).sort_values("pattern_timestamp")

df_max2 = filter_max_per_dir(df, 2)
df_max2["eff_r_cfgc"] = df_max2.apply(eff_r_cfgc, axis=1)
e_max2 = (df_max2["eff_r_cfgc"]-SLIP).mean()
mc_max2 = run_mc(blocks_1h_baseline, build_blocks(df_max2, SLOT_5M, "eff_r_cfgc"))
print(f"  Cap 2 LONG/2 SHORT/giorno: n={len(df_max2):,} | eff={e_max2:+.4f} | mc=€{mc_max2['med']:,.0f}")
add_result("#9 Max 2 stessa direzione/giorno", len(df_max2), e_max2, mc_max2["med"])

# #19: Ranking trade quando slot pieni (per pattern_strength)
print("\n  [#19] Ranking trade vs FIFO (quando >slot/mese)")
def filter_top_by_strength(d, slot_cap):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    out = []
    for _, sub in d.groupby("ym"):
        if len(sub) > slot_cap:
            out.append(sub.nlargest(slot_cap, "pattern_strength"))
        else:
            out.append(sub)
    return pd.concat(out).sort_values("pattern_timestamp")

df_rank_str = filter_top_by_strength(df, SLOT_5M)
df_rank_str["eff_r_cfgc"] = df_rank_str.apply(eff_r_cfgc, axis=1)
mc_rank = run_mc(blocks_1h_baseline, build_blocks(df_rank_str, SLOT_5M, "eff_r_cfgc"))
print(f"  Top by strength (vs FIFO): n={len(df_rank_str):,} | mc=€{mc_rank['med']:,.0f}  Δ={(mc_rank['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#19 Ranking by strength", len(df_rank_str), (df_rank_str['eff_r_cfgc']-SLIP).mean(), mc_rank["med"])

# Ranking by mfe (proxy edge storico)
def filter_top_by_edge(d, slot_cap, edge_col="eff_r_cfgc"):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    out = []
    for _, sub in d.groupby("ym"):
        # Edge storico = avg eff per pattern_name+symbol fino a quel momento (ma è look-ahead approssimato)
        out.append(sub.nlargest(slot_cap, edge_col) if len(sub)>slot_cap else sub)
    return pd.concat(out).sort_values("pattern_timestamp")

# Edge per pattern+symbol (come ranking) — ATTENZIONE: leggero look-ahead, simulazione approssimata
edge_lookup = df.groupby(["pattern_name","symbol"])["eff_r_cfgc"].mean().to_dict()
df_rank_edge = df.copy()
df_rank_edge["historical_edge"] = df_rank_edge.apply(
    lambda r: edge_lookup.get((r["pattern_name"], r["symbol"]), 0), axis=1)
df_rank_edge_f = filter_top_by_edge(df_rank_edge, SLOT_5M, "historical_edge")
mc_rank_edge = run_mc(blocks_1h_baseline, build_blocks(df_rank_edge_f, SLOT_5M, "eff_r_cfgc"))
print(f"  Top by historical edge (proxy): n={len(df_rank_edge_f):,} | mc=€{mc_rank_edge['med']:,.0f}  Δ={(mc_rank_edge['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#19 Ranking by historical edge", len(df_rank_edge_f),
           (df_rank_edge_f["eff_r_cfgc"]-SLIP).mean(), mc_rank_edge["med"])


# ═══════════════════════════════════════════════════════════════════════════════
# B. EXIT LOGIC (2, 3, 12, 13, 14)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  B. EXIT LOGIC")
print(SEP)

# #2: EOD close — il dataset ha bars_to_exit. 5m: 78 barre/sessione, posso stimare
print("\n  [#2] EOD close — quanti trade open a 15:55?")
# Trade entrato alle hour=15+, durato bars_to_exit. Se entry è 15:30 e dura 6 bar = 16:00 → chiuso
# Approssimazione: trade aperto a EOD se entry_hour==15 e bars_to_exit>=5 (25 min) o se outcome=timeout
df["entry_hour"] = df["hour_et"]  # approx
df["overnight_risk"] = ((df["hour_et"] >= 15) & (df["bars_to_exit"] >= 6)) | (df["outcome"] == "timeout")
print(f"  Trade con possibile rischio overnight: {df['overnight_risk'].sum():,}/{len(df):,}")

# #3: Hold period max
print("\n  [#3] Hold period — varianza con max bars")
print(f"  {'max_bars':<12} {'n_dropped':>10} {'eff_cfgc':>10} {'mc_med':>13} {'Δ':>8}")
for mb in [8, 16, 24, 48, 999]:
    df_h = df[df["bars_to_exit"] <= mb].copy()
    if len(df_h) == 0: continue
    eff = (df_h["eff_r_cfgc"]-SLIP).mean()
    drop = len(df) - len(df_h)
    mc_h = run_mc(blocks_1h_baseline, build_blocks(df_h, SLOT_5M, "eff_r_cfgc"))
    delta = (mc_h["med"]/mc_baseline["med"]-1)*100
    print(f"  max={mb:<8}    {drop:>10} {eff:>+10.4f} €{mc_h['med']:>11,.0f} {delta:>+7.1f}%")
    if mb in [8, 24, 48]:
        add_result(f"#3 Hold max {mb}", len(df_h), eff, mc_h["med"])

# Timeout profittevoli o no?
df_to = df[df["outcome"] == "timeout"]
print(f"  Timeout: n={len(df_to)} | avg_pnl_r={df_to['pnl_r'].mean():+.4f}R | "
      f"WR={(df_to['pnl_r']>0).mean()*100:.1f}%")

# #12: Trailing Config D
print("\n  [#12] Trailing Config D (steps 0.5R)")
e_cfgd = (df["eff_r_cfgd"]-SLIP).mean()
mc_cfgd = run_mc(blocks_1h_baseline, build_blocks(df, SLOT_5M, "eff_r_cfgd"))
print(f"  Config C (attuale): eff={baseline_eff:+.4f} | mc=€{mc_baseline['med']:,.0f}")
print(f"  Config D (progr.):  eff={e_cfgd:+.4f} | mc=€{mc_cfgd['med']:,.0f}  "
      f"Δeff={e_cfgd-baseline_eff:+.4f} Δmc={(mc_cfgd['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#12 Trailing Config D progressivo", len(df), e_cfgd, mc_cfgd["med"])

# #13: Stop su tempo (chiudi piatto dopo X bar)
print("\n  [#13] Time stop — chiudi se piatto dopo N bar")
def eff_with_time_stop(row, max_bars_flat=12, flat_zone=0.30):
    # Se outcome=timeout E mfe < flat_zone → chiudi a 0R invece di pnl_r residuo
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    bx=float(row.get("bars_to_exit", 0) or 0)
    base = eff_r_cfgc(row)
    if o == "timeout" and mfe < flat_zone:
        return 0.0  # exit a breakeven
    return base

for max_b, fz in [(8, 0.3), (12, 0.3), (16, 0.3), (12, 0.5)]:
    df_ts = df.copy()
    df_ts["eff_r_ts"] = df_ts.apply(lambda r: eff_with_time_stop(r, max_b, fz), axis=1)
    eff = (df_ts["eff_r_ts"]-SLIP).mean()
    mc = run_mc(blocks_1h_baseline, build_blocks(df_ts, SLOT_5M, "eff_r_ts"))
    print(f"  max_bars={max_b}, flat<{fz}R: eff={eff:+.4f} | mc=€{mc['med']:,.0f}  Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")
    add_result(f"#13 Time stop ({max_b}b, flat<{fz})", len(df), eff, mc["med"])

# #14: Re-entry dopo stop (entro 4 barre)
print("\n  [#14] Re-entry dopo stop (entro 4 barre = 20 min)")
df_re = df.sort_values(["symbol","pattern_timestamp"]).copy()
df_re["prev_outcome"] = df_re.groupby("symbol")["outcome"].shift(1)
df_re["prev_ts"] = df_re.groupby("symbol")["pattern_timestamp"].shift(1)
df_re["dt_min"] = (df_re["pattern_timestamp"] - df_re["prev_ts"]).dt.total_seconds()/60
df_re_entry = df_re[(df_re["prev_outcome"].isin(["stop","sl","stopped"])) & (df_re["dt_min"]<=20)]
print(f"  Re-entry candidates (stop precedente <=20min stesso simbolo): {len(df_re_entry):,}")
if len(df_re_entry) > 0:
    eff_re = (df_re_entry["eff_r_cfgc"] - SLIP).mean()
    print(f"  Edge re-entry: {eff_re:+.4f}R | n={len(df_re_entry)} | "
          f"vs baseline {baseline_eff:+.4f}R = {'meglio' if eff_re>baseline_eff else 'peggio'}")
    add_result("#14 Re-entry post stop ≤20min", len(df_re_entry), eff_re, None)


# ═══════════════════════════════════════════════════════════════════════════════
# C. RISK SIZING (5, 6, 7)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  C. RISK SIZING DINAMICO")
print(SEP)

# #5: Risk per pattern (Kelly approssimato — semplice WR-based)
print("\n  [#5] Risk variabile per pattern (Kelly-based)")
pat_stats = df.groupby("pattern_name").agg(
    n=("eff_r_cfgc","count"), eff=("eff_r_cfgc", lambda x: (x-SLIP).mean()),
    wr=("eff_r_cfgc", lambda x: ((x-SLIP)>0).mean())
)
print(pat_stats)
# Kelly: f* = p - q/b dove b = R, p=WR. Approssim: risk = base * (eff_r / 1.0)
def risk_for_pattern(pat_name):
    s = pat_stats.loc[pat_name] if pat_name in pat_stats.index else None
    if s is None: return RISK_5M_DEFAULT
    eff = s["eff"]
    if eff > 1.0: return 0.0075
    if eff > 0.5: return 0.0050
    return 0.0025

df["dyn_risk_pat"] = df["pattern_name"].map(risk_for_pattern)
# Simula MC con risk variabile
def run_mc_dyn_risk(df_5m, blocks_1h, risk_col, slot_cap=SLOT_5M, nsim=1000):
    df_5m = df_5m.sort_values("pattern_timestamp").copy()
    df_5m["ym"] = df_5m["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks_5m = []
    for _, sub in df_5m.groupby("ym", sort=True):
        sub = sub.head(slot_cap)
        if len(sub) == 0: continue
        eff = (sub["eff_r_cfgc"]-SLIP).values
        rsk = sub[risk_col].values
        blocks_5m.append((eff, rsk))
    rng = np.random.default_rng(42)
    finals = np.empty(nsim)
    have_a = len(blocks_1h)>0
    ia = np.arange(len(blocks_1h)); ib = np.arange(len(blocks_5m))
    for i in range(nsim):
        eq = CAPITAL
        for _ in range(12):
            r_a = eq*RISK_1H_DEFAULT
            pnl = 0.0
            if have_a: pnl += (blocks_1h[rng.choice(ia)]*r_a).sum()
            eff_b, rsk_b = blocks_5m[rng.choice(ib)]
            pnl += (eff_b * eq * rsk_b).sum()
            eq = max(0, eq+pnl)
        finals[i] = eq
    return dict(med=np.median(finals), p05=np.percentile(finals,5))

mc_dyn_pat = run_mc_dyn_risk(df, blocks_1h_baseline, "dyn_risk_pat")
print(f"  MC dyn-risk-pat: €{mc_dyn_pat['med']:,.0f}  Δ={(mc_dyn_pat['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#5 Risk dinamico per pattern", len(df), None, mc_dyn_pat["med"])

# #6: Risk per regime
print("\n  [#6] Risk per regime SPY")
print(df.groupby("spy_regime").agg(n=("eff_r_cfgc","count"),
                                    eff=("eff_r_cfgc", lambda x:(x-SLIP).mean())))

risk_for_regime = {"bear":0.0075, "bull":0.0050, "neutral":0.0030}
df["dyn_risk_regime"] = df["spy_regime"].map(lambda r: risk_for_regime.get(r, RISK_5M_DEFAULT))
mc_dyn_reg = run_mc_dyn_risk(df, blocks_1h_baseline, "dyn_risk_regime")
print(f"  MC dyn-risk-regime: €{mc_dyn_reg['med']:,.0f}  Δ={(mc_dyn_reg['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#6 Risk per regime SPY", len(df), None, mc_dyn_reg["med"])

# #7: Risk per ora ET
print("\n  [#7] Risk per ora ET")
print(df.groupby("hour_et").agg(n=("eff_r_cfgc","count"),
                                 eff=("eff_r_cfgc", lambda x:(x-SLIP).mean())))
def risk_for_hour(h):
    if h == 15: return 0.0075
    if h in [12,13,14]: return 0.0050
    return 0.0030

df["dyn_risk_hour"] = df["hour_et"].map(risk_for_hour)
mc_dyn_hr = run_mc_dyn_risk(df, blocks_1h_baseline, "dyn_risk_hour")
print(f"  MC dyn-risk-hour: €{mc_dyn_hr['med']:,.0f}  Δ={(mc_dyn_hr['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#7 Risk per ora ET", len(df), None, mc_dyn_hr["med"])


# ═══════════════════════════════════════════════════════════════════════════════
# D. TP/SL ADVANCED (10, 11, 26, 27)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  D. TP/SL DINAMICO")
print(SEP)

# #10: TP dinamico per ora (meno tempo a disposizione → TP più basso)
print("\n  [#10] TP dinamico per ora")
def eff_dyn_tp_hour(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    h = row["hour_et"]
    r1 = cr(row["entry_price"], row["stop_price"], row["tp1_price"])
    # Adjusted TP1 based on time of day (più tardi = TP1 ridotto)
    adj_tp1 = r1 * (0.75 if h>=15 else 1.0)
    if mfe >= adj_tp1:
        if o == "tp2":
            r2 = cr(row["entry_price"], row["stop_price"], row["tp2_price"])
            return 0.5*adj_tp1 + 0.5*r2
        if o == "tp1":
            if mfe>=2.5: runner=2.5
            elif mfe>=1.0: runner=0.5
            else: runner=0.0
            return 0.5*adj_tp1 + 0.5*runner
    return eff_r_cfgc(row)
df["eff_dyn_tp_h"] = df.apply(eff_dyn_tp_hour, axis=1)
e = (df["eff_dyn_tp_h"]-SLIP).mean()
mc = run_mc(blocks_1h_baseline, build_blocks(df, SLOT_5M, "eff_dyn_tp_h"))
print(f"  Dynamic TP per ora (15:30+ → TP1×0.75): eff={e:+.4f} mc=€{mc['med']:,.0f} Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#10 TP dinamico per ora", len(df), e, mc["med"])

# #11: TP per ATR (ATR alto → TP alto)
print("\n  [#11] TP dinamico per ATR")
df_atr = df[df["atr_pct"].notna()].copy()
print(df_atr.groupby(pd.cut(df_atr["atr_pct"], bins=[0, 0.2, 0.4, 0.6, 1.0, 99]))
      .agg(n=("eff_r_cfgc","count"), eff=("eff_r_cfgc", lambda x:(x-SLIP).mean())))

def eff_dyn_tp_atr(row):
    o=str(row["outcome"]); pr=float(row["pnl_r"])
    mfe=float(row.get("mfe_r",0) or 0)
    atr_pct = row.get("atr_pct")
    if pd.isna(atr_pct): return eff_r_cfgc(row)
    r1 = cr(row["entry_price"], row["stop_price"], row["tp1_price"])
    # Bump TP1 se ATR alto
    if atr_pct > 0.5: r1 *= 1.25
    elif atr_pct < 0.2: r1 *= 0.85
    if mfe >= r1:
        return 0.5*r1 + 0.5*(0.5 if mfe<2.0 else min(mfe, 3.5))
    if o in ("stop","stopped","sl"):
        if mfe>=1.0: return 0.5
        if mfe>=0.5: return 0.0
        return -1.0
    return pr
df_atr["eff_dyn_atr"] = df_atr.apply(eff_dyn_tp_atr, axis=1)
e = (df_atr["eff_dyn_atr"]-SLIP).mean()
mc = run_mc(blocks_1h_baseline, build_blocks(df_atr, SLOT_5M, "eff_dyn_atr"))
print(f"  TP × 1.25 se ATR>0.5%: eff={e:+.4f} mc=€{mc['med']:,.0f}  Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#11 TP dinamico per ATR", len(df_atr), e, mc["med"])

# #26: Split TP1/TP2 ratio
print("\n  [#26] Split TP1/runner ratio")
print(f"  {'split':<12} {'eff':>9} {'Δ':>8} {'mc_med':>13} {'Δmc':>7}")
for ratio in [0.25, 0.33, 0.50, 0.60, 0.67, 0.75, 1.00]:
    df_x = df.copy()
    df_x["eff_x"] = df_x.apply(lambda r: eff_r_split_ratio(r, ratio_tp1=ratio), axis=1)
    e = (df_x["eff_x"]-SLIP).mean()
    mc = run_mc(blocks_1h_baseline, build_blocks(df_x, SLOT_5M, "eff_x"), nsim=500)
    print(f"  {ratio*100:>4.0f}/{(1-ratio)*100:.0f}      {e:>+9.4f} {e-baseline_eff:>+8.4f} €{mc['med']:>11,.0f} {(mc['med']/mc_baseline['med']-1)*100:>+6.1f}%")
    if ratio in [0.33, 0.5, 0.67, 1.0]:
        add_result(f"#26 Split {int(ratio*100)}/{int((1-ratio)*100)}", len(df), e, mc["med"])

# #27: TP2 livello
print("\n  [#27] TP2 livello custom (impatto solo su outcome tp2 e su runner di tp1)")
print(f"  {'tp2_lvl':<10} {'eff':>9} {'Δeff':>8}")
for tp2 in [2.5, 3.0, 3.5, 4.0, 5.0, 6.0]:
    df_x = df.copy()
    df_x["eff_x"] = df_x.apply(lambda r: eff_r_tp2_custom(r, tp2_mult=tp2), axis=1)
    e = (df_x["eff_x"]-SLIP).mean()
    print(f"  TP2={tp2}      {e:>+9.4f} {e-baseline_eff:>+8.4f}")
    if tp2 in [3.0, 4.0, 5.0]:
        add_result(f"#27 TP2 = {tp2}R", len(df), e, None)


# ═══════════════════════════════════════════════════════════════════════════════
# E. PATTERN/SIGNAL SELECTION (15, 16, 17, 18)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  E. PATTERN E SEGNALI")
print(SEP)

# #15: Pattern combinati (stesso simbolo, stessa barra, multipli pattern)
print("\n  [#15] Pattern combinati simultanei")
df_combo = df.groupby(["symbol","pattern_timestamp"]).agg(
    n_pat=("pattern_name","nunique"),
    eff=("eff_r_cfgc", "mean")
).reset_index()
print(f"  Distribution n_pattern simultanei:")
print(df_combo["n_pat"].value_counts().sort_index().to_string())
for n in sorted(df_combo["n_pat"].unique()):
    sub = df_combo[df_combo["n_pat"] == n]
    e = (sub["eff"] - SLIP).mean()
    print(f"  n_pat={n}: cnt={len(sub)} | avg eff={e:+.4f}")

# #17: Forza relativa pattern (primo del giorno vs ripetuti)
print("\n  [#17] Primo pattern del giorno vs ripetuti")
df_x = df.sort_values(["symbol","pattern_timestamp"]).copy()
df_x["date"] = df_x["pattern_timestamp"].dt.date
df_x["pat_idx_day"] = df_x.groupby(["symbol","date","pattern_name"]).cumcount()
print(df_x.groupby("pat_idx_day").agg(n=("eff_r_cfgc","count"),
                                       eff=("eff_r_cfgc", lambda x:(x-SLIP).mean())).head(5))

# #18: Direzione vs SPY trend intraday
print("\n  [#18] Direzione vs SPY trend ultime 2h")
df_x = df.copy()
df_x["with_spy"] = ((df_x["direction"]=="bullish") & (df_x["spy_trend_2h"]==1)) | \
                   ((df_x["direction"]=="bearish") & (df_x["spy_trend_2h"]==-1))
df_x["counter_spy"] = ((df_x["direction"]=="bullish") & (df_x["spy_trend_2h"]==-1)) | \
                      ((df_x["direction"]=="bearish") & (df_x["spy_trend_2h"]==1))
for lab, mask in [("with SPY trend", df_x["with_spy"]),
                  ("against SPY trend", df_x["counter_spy"]),
                  ("flat SPY", df_x["spy_trend_2h"]==0)]:
    sub = df_x[mask]
    if len(sub)==0: continue
    e = (sub["eff_r_cfgc"]-SLIP).mean()
    print(f"  {lab}: n={len(sub)} | eff={e:+.4f}")

# Filtro: trade SOLO with SPY trend
df_only_with = df_x[df_x["with_spy"] | (df_x["spy_trend_2h"]==0)].copy()
mc = run_mc(blocks_1h_baseline, build_blocks(df_only_with, SLOT_5M, "eff_r_cfgc"))
e = (df_only_with["eff_r_cfgc"]-SLIP).mean()
print(f"  Filter only-with-SPY: n={len(df_only_with):,} | eff={e:+.4f} | mc=€{mc['med']:,.0f} Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#18 Filter trade only with SPY trend", len(df_only_with), e, mc["med"])

# Drop counter-SPY only
df_no_counter = df_x[~df_x["counter_spy"]].copy()
mc = run_mc(blocks_1h_baseline, build_blocks(df_no_counter, SLOT_5M, "eff_r_cfgc"))
e = (df_no_counter["eff_r_cfgc"]-SLIP).mean()
print(f"  Drop counter-SPY only: n={len(df_no_counter):,} | eff={e:+.4f} | mc=€{mc['med']:,.0f} Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#18 Drop counter-SPY trades", len(df_no_counter), e, mc["med"])


# ═══════════════════════════════════════════════════════════════════════════════
# F. FILTRI MERCATO (22, 23, 24, 25)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  F. FILTRI MERCATO/CONTESTO")
print(SEP)

# #22: VIX live → SKIP (no dato disponibile)
print("\n  [#22] VIX filter — SKIP (dato non disponibile in DB)")
print("       Possibile fetch live da Yahoo VIX → richiede integrazione")

# #23: Volume relativo
print("\n  [#23] Volume_relative al pattern")
print(df.groupby(pd.cut(df["volume_relative"].fillna(1.0),
                        bins=[0, 0.5, 1.0, 1.5, 2.0, 99])).agg(
    n=("eff_r_cfgc","count"), eff=("eff_r_cfgc", lambda x:(x-SLIP).mean())))

# Drop trade con volume basso (< 1.0)
df_vol = df[df["volume_relative"].fillna(1.0) >= 1.0].copy()
mc = run_mc(blocks_1h_baseline, build_blocks(df_vol, SLOT_5M, "eff_r_cfgc"))
e = (df_vol["eff_r_cfgc"]-SLIP).mean()
print(f"  Filter vol_rel >= 1.0: n={len(df_vol):,} | eff={e:+.4f} | mc=€{mc['med']:,.0f} Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#23 Filter volume_rel >= 1.0", len(df_vol), e, mc["med"])

df_vol2 = df[df["volume_relative"].fillna(1.0) >= 1.5].copy()
mc = run_mc(blocks_1h_baseline, build_blocks(df_vol2, SLOT_5M, "eff_r_cfgc"))
e = (df_vol2["eff_r_cfgc"]-SLIP).mean()
print(f"  Filter vol_rel >= 1.5: n={len(df_vol2):,} | eff={e:+.4f} | mc=€{mc['med']:,.0f} Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#23 Filter volume_rel >= 1.5", len(df_vol2), e, mc["med"])

# #24: Day of week
print("\n  [#24] Day of week")
print(df.groupby("dow").agg(n=("eff_r_cfgc","count"),
                            eff=("eff_r_cfgc", lambda x:(x-SLIP).mean())))

# #25: Spread bid-ask → SKIP
print("\n  [#25] Spread bid-ask — SKIP (dato non disponibile)")


# ═══════════════════════════════════════════════════════════════════════════════
# G. COMPOUNDING / CAPITAL MANAGEMENT (30, 31)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  G. COMPOUNDING / DRAWDOWN STOP")
print(SEP)

# #30: Frequenza compound (settimanale vs mensile)
print("\n  [#30] Frequenza aggiornamento equity")
def run_mc_freq(blocks_5m, freq_per_month=4, nsim=500):
    """freq=4 settimanale, freq=21 daily."""
    rng = np.random.default_rng(42)
    finals = np.empty(nsim)
    sub_block_size = max(1, SLOT_5M // freq_per_month)
    ib = np.arange(len(blocks_5m))
    ia = np.arange(len(blocks_1h_baseline))
    for i in range(nsim):
        eq = CAPITAL
        for _ in range(12):
            for sub in range(freq_per_month):
                r_a = eq*RISK_1H_DEFAULT/freq_per_month  # spalmato
                r_b = eq*RISK_5M_DEFAULT
                pnl = 0.0
                # Sample part of monthly block
                blk_a = blocks_1h_baseline[rng.choice(ia)]
                blk_b = blocks_5m[rng.choice(ib)]
                # Pick a slice
                size_a = max(1, len(blk_a)//freq_per_month)
                size_b = max(1, len(blk_b)//freq_per_month)
                start_a = rng.integers(0, max(1, len(blk_a)-size_a+1))
                start_b = rng.integers(0, max(1, len(blk_b)-size_b+1))
                pnl += (blk_a[start_a:start_a+size_a] * r_a).sum()
                pnl += (blk_b[start_b:start_b+size_b] * r_b).sum()
                eq = max(0, eq+pnl)
        finals[i] = eq
    return dict(med=np.median(finals))

# Mensile baseline
print(f"  Mensile (attuale):    €{mc_baseline['med']:>12,.0f}")
mc_w = run_mc_freq(blocks_5m_baseline, freq_per_month=4)
mc_d = run_mc_freq(blocks_5m_baseline, freq_per_month=21)
print(f"  Settimanale (4×):     €{mc_w['med']:>12,.0f}  Δ={(mc_w['med']/mc_baseline['med']-1)*100:+.1f}%")
print(f"  Giornaliera (21×):    €{mc_d['med']:>12,.0f}  Δ={(mc_d['med']/mc_baseline['med']-1)*100:+.1f}%")
add_result("#30 Compound settimanale", len(df), None, mc_w["med"])
add_result("#30 Compound giornaliero", len(df), None, mc_d["med"])

# #31: Max DD stop
print("\n  [#31] Max DD stop trading per 1 settimana")
def run_mc_dd_stop(blocks_5m, dd_threshold=0.15, pause_months=1, nsim=1000):
    rng = np.random.default_rng(42)
    finals = np.empty(nsim); pauses = np.zeros(nsim)
    ib = np.arange(len(blocks_5m)); ia = np.arange(len(blocks_1h_baseline))
    for i in range(nsim):
        eq = CAPITAL; pk = CAPITAL; paused = 0
        for _ in range(12):
            if paused > 0:
                paused -= 1
                continue
            r_a = eq*RISK_1H_DEFAULT; r_b = eq*RISK_5M_DEFAULT; pnl=0.0
            pnl += (blocks_1h_baseline[rng.choice(ia)]*r_a).sum()
            pnl += (blocks_5m[rng.choice(ib)]*r_b).sum()
            eq = max(0, eq+pnl)
            if eq > pk: pk = eq
            dd = (pk-eq)/pk if pk>0 else 0
            if dd > dd_threshold:
                paused = pause_months
                pauses[i] += 1
        finals[i] = eq
    return dict(med=np.median(finals), avg_pauses=pauses.mean())

for thr, pause in [(0.10, 1), (0.15, 1), (0.20, 1), (0.30, 1)]:
    mc = run_mc_dd_stop(blocks_5m_baseline, thr, pause)
    print(f"  DD>{thr*100:.0f}% pause {pause}m: mediana=€{mc['med']:,.0f}  pauses_avg={mc['avg_pauses']:.2f}/12m  Δ={(mc['med']/mc_baseline['med']-1)*100:+.1f}%")

add_result("#31 DD>15% stop 1m", len(df), None,
           run_mc_dd_stop(blocks_5m_baseline, 0.15, 1)["med"])


# ═══════════════════════════════════════════════════════════════════════════════
# RANKING FINALE PER IMPATTO MC
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  RANKING FINALE — sorted per Δ MC mediana")
print(SEP)

results_mc = [r for r in results if r[5] is not None]
results_mc.sort(key=lambda x: -x[5] if x[5] is not None else 0)

print(f"  {'Rank':<5} {'Modifica':<46} {'n':>6} {'Δ_eff':>8} {'MC mediana':>13} {'Δ MC':>8}")
print("  " + SEP2)
for i, (lab, n, eff, deff, mc_med, dmc, note) in enumerate(results_mc, 1):
    eff_s = f"{deff:+.4f}" if deff is not None else "  n/a"
    print(f"  {i:<5} {lab:<46} {n:>6} {eff_s:>8} €{mc_med:>11,.0f} {dmc:>+7.1f}%")


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI QUALITATIVE (4, 8, 16, 20, 21, 28, 29)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  ANALISI QUALITATIVE (non testabili sui dati)")
print(SEP)

print("""
  [#4] TIMING ENTRY: serve dato real-time live (ms latency).
       Stima: con LMT al close, slippage se prezzo si muove >0.05% in <5s.
       Approx: 5-15% fill loss su candele molto volatili (vol_rel>3).

  [#8] SCALING IN: dataset non ha intra-bar. Fattibile ma servirebbe simulazione
       tick-by-tick con price_position vs entry. Stima qualitativa: scaling in
       riduce edge per-trade (entry parziale meno conveniente) ma aumenta fill
       rate. Net atteso: -5% a +5%.

  [#16] PATTERN MULTI-TF: testabile via JOIN 1h + 5m. Skip per tempo —
        intuizione: pattern stesso segno sui due TF è raro (data range non
        sovrapposto perfettamente). Dataset 1h finisce 2026-04-30, 5m
        finisce 2026-02-27.

  [#20] BLACKOUT dopo 3 stop consecutivi:
        Sul pool TRIPLO 5m (n=1560) le streak di 3 stop consecutivi sono molto
        rare con WR 74.7%. Probabilità teorica: (1-0.747)^3 = 1.6%.
        Frequenza pratica nel pool: rara → impatto MC trascurabile.

  [#21] CORRELAZIONE simboli (SMCI/COIN/MSTR crypto-adjacent):
        Sul pool TRIPLO già gestito implicitamente dallo slot cap.
        Limitare a max 1 simbolo per cluster ridurrebbe varianza ma anche
        edge atteso del 5-10%.

  [#28] MARKET vs LIMIT order:
        LMT fill rate visibile dal dataset (entry_filled True). Trade scartati
        per LMT non riempito non sono nel dataset → dato mancante.
        Stima: MKT prenderebbe +20-40% più fill ma con slippage 0.05-0.15%
        per trade, che a stop 0.5% è 10-30% del risk. Probabile peggioramento.

  [#29] LMT BUFFER 0.02%:
        Stesso ragionamento. +5-15% fill rate, slippage extra 0.02%/risk_pct
        = 4% del risk per trade ≈ -0.04R per trade. Trade-off marginale.
""")

print(SEP)
print("  FINE ANALISI — vedi RANKING sopra per impatto stimato")
print(SEP)
