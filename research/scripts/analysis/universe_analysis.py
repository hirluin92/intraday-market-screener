"""
ANALISI UNIVERSO SIMBOLI — pool TRIPLO 5m con Config D.

Sezioni:
  1. Profilo winner vs loser per simbolo
  2. Big cap escluse (AAPL, MSFT, GOOGL, WMT, DELL) ricalcolate con Config D
  3. Simboli candidati da aggiungere (qualitativo)
  4. Rimozione simboli deboli
  5. Rotazione temporale per anno
  6. Correlazione rendimenti giornalieri
  7. MC con universo ottimizzato
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
SLOT_5M = 48; SLOT_1H = 66

PATTERNS = {"double_bottom","double_top","macd_divergence_bull","macd_divergence_bear",
            "rsi_divergence_bull","rsi_divergence_bear"}
SYMBOLS_BLOCKED_5M = {"SPY","AAPL","MSFT","GOOGL","WMT","DELL"}
VAL_SYMS_5M_FULL = {"GOOGL","TSLA","AMD","META","NVDA","NFLX","COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL","ACHR","ASTS","JOBY",
    "RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX","NVO","LLY","MRNA","NKE","TGT","MP",
    "NEM","WMT","MU","LUNR","CAT","GS"}
VAL_SYMS_5M = VAL_SYMS_5M_FULL - SYMBOLS_BLOCKED_5M

# Settore + market cap classification (manuale, basato su conoscenza pubblica al 2026)
SECTOR_MAP = {
    # Mega-cap tech
    "AAPL":"Tech-Mega","MSFT":"Tech-Mega","GOOGL":"Tech-Mega","META":"Tech-Mega",
    "NVDA":"Tech-Mega","AMZN":"Tech-Mega",
    # Tech mid-large
    "TSLA":"Tech-Auto","AMD":"Semi","MU":"Semi","SMCI":"Tech-AI",
    "NFLX":"Streaming","SHOP":"E-commerce","SOFI":"Fintech","HOOD":"Fintech",
    "SCHW":"Finance","GS":"Finance",
    # Crypto-adjacent
    "COIN":"Crypto","MSTR":"Crypto",
    # Cyber/Cloud
    "ZS":"Cyber","NET":"CDN","MDB":"DB","HPE":"Tech-Hardware","DELL":"Tech-Hardware",
    "PLTR":"Data","CELH":"Beverage",
    # Game/Web3
    "RBLX":"Gaming",
    # Air mobility / space
    "ACHR":"Air-Mobility","ASTS":"Space","JOBY":"Air-Mobility","RKLB":"Space","LUNR":"Space",
    # Nuclear/SmallCap energy
    "NNE":"Nuclear","OKLO":"Nuclear","SMR":"Nuclear","WULF":"Crypto-Mining","APLD":"Tech-AI",
    "RXRX":"Biotech-AI",
    # Pharma
    "NVO":"Pharma","LLY":"Pharma","MRNA":"Pharma",
    # Consumer
    "NKE":"Consumer","TGT":"Retail","WMT":"Retail",
    # Materials
    "MP":"Materials","NEM":"Mining-Gold","CAT":"Industrial",
    # Index
    "SPY":"Index",
}
# Market cap bucket (semplificato: small/mid/large/mega)
MCAP_MAP = {
    # Mega ($500B+)
    "AAPL":"mega","MSFT":"mega","GOOGL":"mega","META":"mega","NVDA":"mega","AMZN":"mega",
    "TSLA":"mega","WMT":"mega","LLY":"mega","NVO":"mega","GS":"large",
    # Large ($50-500B)
    "AMD":"large","NFLX":"large","MU":"large","CAT":"large","NKE":"large",
    "MRNA":"mid","SCHW":"large","COIN":"large","SHOP":"large","TGT":"large",
    "DELL":"large","HPE":"mid",
    # Mid ($10-50B)
    "MSTR":"mid","HOOD":"mid","SOFI":"mid","ZS":"mid","NET":"mid","MDB":"mid",
    "CELH":"mid","PLTR":"large","SMCI":"mid","RBLX":"mid","NEM":"mid","SPY":"index",
    # Small ($1-10B)
    "ACHR":"small","ASTS":"small","JOBY":"small","RKLB":"small","NNE":"small",
    "OKLO":"small","WULF":"small","APLD":"small","SMR":"small","RXRX":"small",
    "MP":"small","LUNR":"small",
}

SEP = "=" * 100
SEP2 = "-" * 100

# ─── eff_r ────────────────────────────────────────────────────────────────────
def cr(e,s,t):
    d=abs(float(e)-float(s)); return 0.0 if d<1e-10 else abs(float(t)-float(e))/d

def eff_r_cfgd(row):
    """Config D: trail step 0.5R."""
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


# ─── Carica dataset ──────────────────────────────────────────────────────────
print(SEP)
print("  ANALISI UNIVERSO SIMBOLI — pool TRIPLO 5m con Config D")
print(SEP)

df_raw = pd.read_csv(CSV_5M)
df_raw["pattern_timestamp"] = pd.to_datetime(df_raw["pattern_timestamp"], utc=True)
df_raw["hour_et"] = df_raw["pattern_timestamp"].dt.tz_convert("America/New_York").dt.hour
df_raw["year"] = df_raw["pattern_timestamp"].dt.year

# Filtri base + TRIPLO con PPR cache (per pool TRIPLO standard)
df_b = df_raw[
    df_raw["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df_raw["pattern_name"].isin(PATTERNS) &
    df_raw["provider"].isin(["alpaca"]) &
    (df_raw["pattern_strength"].fillna(0) >= 0.60) &
    (df_raw["hour_et"] >= 11) & (df_raw["hour_et"] <= 16) &
    (df_raw["risk_pct"] >= 0.50) & (df_raw["risk_pct"] <= 2.00)
].copy()

# Pool TRIPLO standard (univer attuale)
df_ppr = pd.read_parquet(PPR_CACHE)
df_b = df_b.merge(df_ppr, on=["symbol","exchange","provider","pattern_timestamp"], how="left")

def is_triplo(row):
    h = row["hour_et"]
    if h >= 15: return True
    if h < 11: return False
    if pd.isna(row["ppr"]): return False
    pos = row["ppr"]; d = str(row["direction"]).lower()
    return ((d=="bullish" and pos<=0.10) or (d=="bearish" and pos>=0.90))

df_b["triplo_pass"] = df_b.apply(is_triplo, axis=1)
df_triplo_full = df_b[df_b["triplo_pass"]].copy()  # include ANCHE big cap (per #2)
df_triplo = df_triplo_full[df_triplo_full["symbol"].isin(VAL_SYMS_5M)].copy()  # universe attuale

df_triplo["eff_d"] = df_triplo.apply(eff_r_cfgd, axis=1)
df_triplo_full["eff_d"] = df_triplo_full.apply(eff_r_cfgd, axis=1)

print(f"\n  Pool TRIPLO universo attuale: {len(df_triplo):,} trade")
print(f"  Pool TRIPLO universo COMPLETO (incl. big cap escluse): {len(df_triplo_full):,} trade")
print(f"  Range: {df_triplo['pattern_timestamp'].min().date()} → {df_triplo['pattern_timestamp'].max().date()}")

# JOIN DB per ATR e volume medio
print("\n  JOIN DB per ATR e volume medio per simbolo...")
conn = psycopg2.connect(host="localhost", port=5432, user="postgres",
                        password="postgres", dbname="intraday_market_screener")
cur = conn.cursor()

# ATR e volume per ogni trade
keys = [(s,e,p,t) for s,e,p,t in zip(df_triplo_full["symbol"], df_triplo_full["exchange"],
                                      df_triplo_full["provider"], df_triplo_full["pattern_timestamp"])]
cur.execute("CREATE TEMP TABLE _kk (sym VARCHAR(32), ex VARCHAR(32), prov VARCHAR(32), ts TIMESTAMPTZ)")
execute_values(cur, "INSERT INTO _kk VALUES %s", keys, page_size=5000)
conn.commit()
cur.execute("""
  SELECT k.sym, k.ex, k.prov, k.ts, ci.atr_14, c.volume
  FROM _kk k
  LEFT JOIN candle_indicators ci ON ci.symbol=k.sym AND ci.exchange=k.ex AND ci.provider=k.prov
       AND ci.timeframe='5m' AND ci.timestamp=k.ts
  LEFT JOIN candles c ON c.symbol=k.sym AND c.exchange=k.ex AND c.provider=k.prov
       AND c.timeframe='5m' AND c.timestamp=k.ts
""")
atr_rows = cur.fetchall()
atr_map = {(s,e,p,pd.Timestamp(t).tz_convert("UTC")): (float(a) if a else None, float(v) if v else None)
           for s,e,p,t,a,v in atr_rows}
df_triplo_full["atr_14"] = [atr_map.get((s,e,p,t.tz_convert("UTC")), (None,None))[0]
                             for s,e,p,t in zip(df_triplo_full["symbol"],df_triplo_full["exchange"],
                                                 df_triplo_full["provider"],df_triplo_full["pattern_timestamp"])]
df_triplo_full["volume"] = [atr_map.get((s,e,p,t.tz_convert("UTC")), (None,None))[1]
                             for s,e,p,t in zip(df_triplo_full["symbol"],df_triplo_full["exchange"],
                                                 df_triplo_full["provider"],df_triplo_full["pattern_timestamp"])]
df_triplo_full["atr_pct"] = df_triplo_full["atr_14"] / df_triplo_full["entry_price"] * 100
df_triplo["atr_14"] = df_triplo_full.loc[df_triplo.index, "atr_14"]
df_triplo["volume"] = df_triplo_full.loc[df_triplo.index, "volume"]
df_triplo["atr_pct"] = df_triplo_full.loc[df_triplo.index, "atr_pct"]
print(f"  ATR risolto: {df_triplo_full['atr_14'].notna().sum():,}/{len(df_triplo_full):,}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PROFILO WINNER vs LOSER PER SIMBOLO
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  1. PROFILO PER SIMBOLO (universo attuale, pool TRIPLO Config D)")
print(SEP)

stats = df_triplo.groupby("symbol").agg(
    n=("eff_d", "count"),
    avg_d=("eff_d", lambda x: (x-SLIP).mean()),
    wr=("eff_d", lambda x: ((x-SLIP)>0).mean()*100),
    atr_pct=("atr_pct", "mean"),
    volume_avg=("volume", "mean"),
    entry_price=("entry_price", "mean"),
).reset_index()
stats["sector"] = stats["symbol"].map(SECTOR_MAP).fillna("?")
stats["mcap"] = stats["symbol"].map(MCAP_MAP).fillna("?")
stats = stats.sort_values("avg_d", ascending=False)

print(f"\n  {'Symbol':<7} {'n':>4} {'avg_r D':>8} {'WR':>6} {'ATR%':>6} {'Vol/min':>10} "
      f"{'$avg':>8} {'mcap':<6} {'sector':<14}")
print("  " + SEP2)
for _, r in stats.iterrows():
    vol = f"{r['volume_avg']/1000:.0f}k" if pd.notna(r['volume_avg']) else "n/a"
    print(f"  {r['symbol']:<7} {r['n']:>4} {r['avg_d']:>+8.4f} {r['wr']:>5.1f}% "
          f"{r['atr_pct']:>5.2f}% {vol:>10} ${r['entry_price']:>6.0f} "
          f"{r['mcap']:<6} {r['sector']:<14}")

# Top 10 / Bottom 10
top10 = stats.head(10)
bot10 = stats.tail(10)

print(f"\n  {'Group':<24} {'n':>5} {'avg_r D':>9} {'WR':>6} {'ATR% mean':>10}")
print("  " + SEP2)
for label, g in [("TOP 10", top10), ("BOTTOM 10", bot10), ("ALL", stats)]:
    n = g["n"].sum()
    if n == 0: continue
    # Pesato per n
    avg_w = (g["avg_d"] * g["n"]).sum() / n
    wr_w  = (g["wr"]    * g["n"]).sum() / n
    atr_w = (g["atr_pct"] * g["n"]).sum() / n if g["atr_pct"].notna().any() else float("nan")
    print(f"  {label:<24} {n:>5} {avg_w:>+9.4f} {wr_w:>5.1f}% {atr_w:>9.2f}%")

# Per gruppo mcap e settore
print(f"\n  Per market cap:")
mcap_g = stats.groupby("mcap").agg(n=("n","sum"),
    avg_d=("avg_d", lambda x: np.average(x, weights=stats.loc[x.index,"n"]))).sort_values("avg_d", ascending=False)
print(mcap_g.round(4).to_string())

print(f"\n  Per settore (top 8 con n totale > 30):")
sect_g = stats.groupby("sector").agg(n=("n","sum"),
    avg_d=("avg_d", lambda x: np.average(x, weights=stats.loc[x.index,"n"])))
sect_g = sect_g[sect_g["n"] >= 30].sort_values("avg_d", ascending=False).head(8)
print(sect_g.round(4).to_string())


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BIG CAP ESCLUSE — ricalcolate con Config D
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  2. BIG CAP ESCLUSE — performance con Config D sul TRIPLO")
print(SEP)

big_cap = ["AAPL","MSFT","GOOGL","WMT","DELL","SPY"]
df_big = df_triplo_full[df_triplo_full["symbol"].isin(big_cap)].copy()

# Sul pool TRIPLO le big cap incluse
print(f"\n  Big cap nel pool TRIPLO (Config D):")
print(f"  {'Symbol':<7} {'n':>4} {'avg_r D':>8} {'WR':>6} {'ATR%':>6} "
      f"{'tmo%':>6} {'Decision':<25}")
print("  " + SEP2)
for sym in big_cap:
    sub = df_big[df_big["symbol"] == sym]
    if len(sub) == 0:
        print(f"  {sym:<7} {0:>4} (no trade nel pool TRIPLO)")
        continue
    eff = (sub["eff_d"] - SLIP).mean()
    wr = ((sub["eff_d"] - SLIP) > 0).mean() * 100
    atr = sub["atr_pct"].mean()
    tmo = (sub["outcome"] == "timeout").mean() * 100
    decision = "✓ REINSERIRE" if eff > 0.30 else ("? marginale" if eff > 0.0 else "✗ tenere fuori")
    print(f"  {sym:<7} {len(sub):>4} {eff:>+8.4f} {wr:>5.1f}% {atr:>5.2f}% "
          f"{tmo:>5.1f}% {decision:<25}")

# Anche sul pool RAW (no TRIPLO) per confronto
df_raw_big = df_raw[
    df_raw["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df_raw["pattern_name"].isin(PATTERNS) &
    df_raw["provider"].isin(["alpaca"]) &
    (df_raw["pattern_strength"].fillna(0) >= 0.60) &
    (df_raw["hour_et"] >= 11) & (df_raw["hour_et"] <= 16) &
    (df_raw["risk_pct"] >= 0.50) & (df_raw["risk_pct"] <= 2.00) &
    df_raw["symbol"].isin(big_cap)
].copy()
df_raw_big["eff_d"] = df_raw_big.apply(eff_r_cfgd, axis=1)

print(f"\n  Big cap nel pool RAW (no MIDDAY_F, Config D, hour>=11, risk valid):")
print(f"  {'Symbol':<7} {'n':>4} {'avg_r D':>8} {'WR':>6} {'tmo%':>6}  Note")
print("  " + SEP2)
for sym in big_cap:
    sub = df_raw_big[df_raw_big["symbol"] == sym]
    if len(sub) == 0: continue
    eff = (sub["eff_d"] - SLIP).mean()
    wr = ((sub["eff_d"] - SLIP) > 0).mean() * 100
    tmo = (sub["outcome"] == "timeout").mean() * 100
    print(f"  {sym:<7} {len(sub):>4} {eff:>+8.4f} {wr:>5.1f}% {tmo:>5.1f}%")

# Per HOUR=15 ALPHA only (senza filtro MIDDAY)
print(f"\n  Big cap HOUR=15 ET only (ALPHA, no MIDDAY filter, Config D):")
print(f"  {'Symbol':<7} {'n':>4} {'avg_r D':>8} {'WR':>6}  Note")
print("  " + SEP2)
df_raw_big_h15 = df_raw_big[df_raw_big["hour_et"] == 15]
for sym in big_cap:
    sub = df_raw_big_h15[df_raw_big_h15["symbol"] == sym]
    if len(sub) == 0:
        print(f"  {sym:<7} {0:>4} (no trade)")
        continue
    eff = (sub["eff_d"] - SLIP).mean()
    wr = ((sub["eff_d"] - SLIP) > 0).mean() * 100
    decision = "✓ REINSERIRE" if eff > 0.30 else ("? marginale" if eff > 0.0 else "✗ confermato fuori")
    print(f"  {sym:<7} {len(sub):>4} {eff:>+8.4f} {wr:>5.1f}%  {decision}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SIMBOLI MAI TESTATI — analisi qualitativa
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  3. SIMBOLI CANDIDATI DA AGGIUNGERE (qualitativo)")
print(SEP)

# Profilo dei top performer (per identificare simboli simili)
top10_atr = top10["atr_pct"].mean()
top10_vol = top10["volume_avg"].dropna().mean()
top10_price = top10["entry_price"].mean()
top10_sectors = top10["sector"].value_counts()

print(f"""
  Profilo TOP 10 simboli (universo attuale, Config D):
    ATR% medio: {top10_atr:.2f}%
    Volume medio (per barra 5m): {top10_vol/1000:.0f}k azioni
    Prezzo medio: ${top10_price:.0f}
    Settori: {top10_sectors.to_dict()}

  Caratteristiche edge: ATR% 1.5-4%, volume liquido, settori "growth/volatile"
  (nuclear, AI, crypto-adjacent, fintech, space).

  Candidati da considerare per estensione universe (NON nel DB attuale):

  HIGH MATCH:
    NIO, XPEV, LI, RIVN — EV cinesi/USA, ATR% 4-7%, volume alto
    BBAI, AI, IONQ      — AI/Quantum mid-cap, ATR% 5-10%
    SOUN, ARQQ          — AI speech/Quantum small-cap
    ENPH, FSLR          — Solar mid-cap, ATR% 3-5%
    UPST, AFRM          — Fintech, ATR% 3-6%
    DKNG, PENN          — iGaming, ATR% 3-5%
    PYPL, SQ            — Fintech mature, ATR% 2-3%
    UBER, LYFT          — Mobility, ATR% 2-3%

  MEDIUM MATCH (più stable, edge atteso più basso):
    ORCL, CSCO, INTC, IBM — Tech-mature
    ADBE, CRM, NOW       — SaaS mature

  LOW MATCH (edge atteso basso):
    BRK.B, JPM, BAC, BA  — Big finance/industrial troppo stabili

  ⚠ Per testarli serve:
    1. Aggiungerli a VALIDATED_SYMBOLS_ALPACA_5M
    2. Backfill 6 mesi di candele 5m + indicators + patterns
    3. Validazione OOS prima di promuoverli a "execute"
  Beneficio: 8-12 simboli aggiuntivi possono raddoppiare la frequenza segnali.
""")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RIMOZIONE SIMBOLI DEBOLI
# ═══════════════════════════════════════════════════════════════════════════════
print(SEP)
print("  4. SIMBOLI DEBOLI nel TRIPLO (avg_r D < +0.30)")
print(SEP)

weak = stats[stats["avg_d"] < 0.30].copy()
weak["contrib_pct"] = weak["n"] / stats["n"].sum() * 100
print(f"\n  {'Symbol':<7} {'n':>4} {'avg_r D':>9} {'contrib%':>8}  {'sector':<14}")
print("  " + SEP2)
for _, r in weak.iterrows():
    print(f"  {r['symbol']:<7} {r['n']:>4} {r['avg_d']:>+9.4f} {r['contrib_pct']:>7.2f}%  {r['sector']:<14}")

# Pool senza weak
strong_syms = set(stats[stats["avg_d"] >= 0.30]["symbol"])
df_strong = df_triplo[df_triplo["symbol"].isin(strong_syms)].copy()
e_full   = (df_triplo["eff_d"] - SLIP).mean()
e_strong = (df_strong["eff_d"] - SLIP).mean()
print(f"\n  Confronto pool:")
print(f"    Pool completo: n={len(df_triplo):,} | avg_d-slip={e_full:+.4f}R")
print(f"    Pool solo strong (avg_d>=+0.30): n={len(df_strong):,} | avg_d-slip={e_strong:+.4f}R")
print(f"    Riduzione volume: -{(1-len(df_strong)/len(df_triplo))*100:.1f}% | Δ edge: {e_strong-e_full:+.4f}R")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ROTAZIONE TEMPORALE
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  5. ROTAZIONE TEMPORALE (avg_r D per simbolo per anno)")
print(SEP)
print(f"\n  {'Symbol':<7} {'2024':>10} {'2025':>10} {'2026 OOS':>11} {'stab?':<8}")
print("  " + SEP2)

# Solo simboli con n>=20 totali
for sym in stats[stats["n"] >= 20]["symbol"]:
    sub = df_triplo[df_triplo["symbol"] == sym]
    cells = []; vals = []
    for y in (2024, 2025, 2026):
        s = sub[sub["year"] == y]
        if len(s) < 5:
            cells.append(f"n/a (n={len(s)})".rjust(10))
            vals.append(None)
        else:
            v = (s["eff_d"]-SLIP).mean()
            cells.append(f"{v:+.4f}".rjust(10))
            vals.append(v)
    valid_vals = [v for v in vals if v is not None]
    if len(valid_vals) >= 2 and all(v > 0.10 for v in valid_vals):
        stab = "STABILE"
    elif len(valid_vals) >= 2 and any(v < 0 for v in valid_vals):
        stab = "ROTTO"
    else:
        stab = "?"
    print(f"  {sym:<7} {cells[0]} {cells[1]} {cells[2]}  {stab:<8}")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. CORRELAZIONE TRA SIMBOLI (rendimenti giornalieri)
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  6. CORRELAZIONE RENDIMENTI GIORNALIERI tra i top 10 simboli")
print(SEP)

# Aggrega per (symbol, date) → media eff_r del giorno
df_triplo["date"] = df_triplo["pattern_timestamp"].dt.tz_convert("America/New_York").dt.date
top10_syms = top10["symbol"].tolist()
piv = df_triplo[df_triplo["symbol"].isin(top10_syms)].pivot_table(
    index="date", columns="symbol", values="eff_d", aggfunc="mean"
)
print(f"\n  Pivot daily eff_d per top 10 simboli (n={piv.shape[0]} giorni)")
corr = piv.corr()
print(f"\n  Matrix correlazione (Pearson):")
print(corr.round(2).to_string())

# Coppie con correlation > 0.3 (non casuale)
import itertools
print(f"\n  Coppie con |corr| > 0.30 (segnale di clustering):")
print(f"  {'Coppia':<18} {'corr':>6} {'note':<30}")
print("  " + SEP2)
seen = set()
for s1, s2 in itertools.combinations(top10_syms, 2):
    if (s1, s2) in seen or s1 not in corr.index or s2 not in corr.columns:
        continue
    c = corr.loc[s1, s2]
    if pd.notna(c) and abs(c) > 0.30:
        sec1 = SECTOR_MAP.get(s1, "?"); sec2 = SECTOR_MAP.get(s2, "?")
        same_sec = "STESSO SETTORE" if sec1 == sec2 else f"{sec1}/{sec2}"
        print(f"  {s1+'-'+s2:<18} {c:>+6.3f}  {same_sec:<30}")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. MC CON UNIVERSO OTTIMIZZATO
# ═══════════════════════════════════════════════════════════════════════════════
print()
print(SEP)
print("  7. MC v6 — universi a confronto (Config D + risk per ora)")
print(SEP)

# 1h pool baseline
df1 = pd.read_csv(CSV_1H)
df1["pattern_timestamp"] = pd.to_datetime(df1["pattern_timestamp"], utc=True)
df1 = df1[
    df1["entry_filled"].astype(str).str.lower().isin(["true","1"]) &
    df1["pattern_name"].isin(PATTERNS) &
    ~df1["provider"].isin(["ibkr"]) &
    (df1["pattern_strength"].fillna(0) >= 0.60)
].copy()
df1["eff_split"] = df1.apply(eff_r_split, axis=1)

def build_blocks(d, slot_cap, eff_col):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    blocks = []
    for _, sub in d.groupby("ym"):
        sub = sub.head(slot_cap)
        if len(sub) > 0: blocks.append((sub[eff_col]-SLIP).values)
    return blocks

def build_blocks_with_risk_hour(d, slot_cap, eff_col):
    d = d.sort_values("pattern_timestamp").copy()
    d["ym"] = d["pattern_timestamp"].dt.tz_convert("UTC").dt.to_period("M")
    risk_for_h = lambda h: 0.0075 if h==15 else (0.005 if 12<=h<=14 else 0.003)
    d["risk_h"] = d["hour_et"].apply(risk_for_h)
    blocks = []
    for _, sub in d.groupby("ym"):
        sub = sub.head(slot_cap)
        if len(sub) > 0:
            blocks.append(((sub[eff_col]-SLIP).values, sub["risk_h"].values))
    return blocks

blocks_1h = build_blocks(df1, SLOT_1H, "eff_split")

def run_mc_dyn_risk(b1, b5_pairs, nsim=2000, seed=42):
    rng = np.random.default_rng(seed)
    finals = np.empty(nsim)
    have_a = len(b1)>0
    ia = np.arange(len(b1)); ib = np.arange(len(b5_pairs))
    for i in range(nsim):
        eq = CAPITAL
        for _ in range(12):
            r_a = eq*RISK_1H_DEFAULT; pnl=0.0
            if have_a: pnl += (b1[rng.choice(ia)]*r_a).sum()
            eff_b, rsk_b = b5_pairs[rng.choice(ib)]
            pnl += (eff_b * eq * rsk_b).sum()
            eq = max(0, eq+pnl)
        finals[i] = eq
    return dict(med=np.median(finals), p05=np.percentile(finals,5),
                p95=np.percentile(finals,95))

# Universo varianti
print(f"\n  Costruzione universi:")
print(f"  - ATTUALE: 36 simboli ({len(df_triplo):,} trade)")

# Universo "ottimizzato": attuale + big cap che potrebbero rientrare
# Determina big cap con avg_d > 0.30 da #2
big_cap_to_add = []
for sym in big_cap:
    sub = df_triplo_full[df_triplo_full["symbol"] == sym]
    if len(sub) >= 5:
        eff = (sub["eff_d"]-SLIP).mean()
        if eff > 0.30:
            big_cap_to_add.append(sym)
print(f"  - OTTIMIZZATO: ATTUALE + big cap reinseribili = ATTUALE + {big_cap_to_add}")
df_opt = df_triplo_full[df_triplo_full["symbol"].isin(set(VAL_SYMS_5M) | set(big_cap_to_add))].copy()
df_opt["eff_d"] = df_opt.apply(eff_r_cfgd, axis=1)

# Universo ridotto: solo top 15 stabili (avg_d>=+0.50)
top15 = stats[stats["avg_d"] >= 0.50].head(15)["symbol"].tolist()
print(f"  - RIDOTTO (top 15 con avg_d>=+0.50): {top15}")
df_top15 = df_triplo[df_triplo["symbol"].isin(top15)].copy()

# Universo solo strong (avg_d >= +0.30)
print(f"  - SOLO STRONG (avg_d>=+0.30): {len(strong_syms)} simboli")
df_strong["eff_d"] = df_strong.apply(eff_r_cfgd, axis=1)

print()
print(f"  {'Universo':<32} {'n':>5} {'avg_d':>8} {'Mediana':>13} {'Worst5%':>13} {'Δ vs base':>10}")
print("  " + SEP2)

universes = [
    ("ATTUALE (36 simboli)",  df_triplo,  "baseline"),
    ("OTTIMIZZATO (attuale+bigcap)", df_opt, ""),
    ("RIDOTTO (top 15)", df_top15, ""),
    ("SOLO STRONG (avg_d>=+0.30)", df_strong, ""),
]
mc_baseline = None
for label, d_u, note in universes:
    blocks = build_blocks_with_risk_hour(d_u, SLOT_5M, "eff_d")
    if not blocks:
        print(f"  {label:<32} (no blocchi)")
        continue
    mc = run_mc_dyn_risk(blocks_1h, blocks)
    avg = (d_u["eff_d"]-SLIP).mean()
    if mc_baseline is None:
        mc_baseline = mc
        delta = "—"
    else:
        delta = f"{(mc['med']/mc_baseline['med']-1)*100:+.1f}%"
    print(f"  {label:<32} {len(d_u):>5} {avg:>+8.4f} €{mc['med']:>11,.0f} €{mc['p05']:>11,.0f} {delta:>10}")


print()
print(SEP)
print("  CONCLUSIONI")
print(SEP)
