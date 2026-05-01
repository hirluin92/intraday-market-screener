#!/usr/bin/env python3
"""
Symbol Review under TRIPLO Config (Apr 2026)
  - ALPHA   : 15:00-16:00 ET, tutti i 6 pattern
  - MIDDAY_F: 11:00-14:59 ET, solo al estremo giorno (dist_extreme<0.10) + BTE=1
  - TRIPLO  : ALPHA + MIDDAY_F

Analizza:
  1. Simboli bloccati  (SPY, AAPL, MSFT, GOOGL, WMT, DELL) — vanno ancora bloccati?
  2. Watchlist negativa (RIVN, RXRX, VKTX, SMR, LUNR) — situazione TRIPLO
  3. Tutti i simboli universo 5m — ranking per avg+slip con OOS breakdown
"""
import sys; sys.path.insert(0, '/app')
import pandas as pd
import numpy as np
import psycopg2
from datetime import timedelta

try:
    import pytz
    TZ_ET = pytz.timezone('America/New_York')
except ImportError:
    TZ_ET = None

SEP  = '═' * 80
SEP2 = '─' * 80

# ── DB ────────────────────────────────────────────────────────────────────────
print("Loading DB data...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()

# SPY 1d per regime filter
cur.execute("""
    SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
    FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp
""")
spy_1d = cur.fetchall()

# 1d OHLC per at_extreme (solo simboli che ci servono)
cur.execute("""
    SELECT symbol, DATE(timestamp AT TIME ZONE 'UTC'),
           high::float, low::float, close::float
    FROM candles WHERE timeframe='1d'
""")
sym_1d_rows = cur.fetchall()
conn.close()

spy_df = pd.DataFrame(spy_1d, columns=['date', 'close'])
spy_df['ema50']  = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']    = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] >  2, 'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2, 'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

sym_1d_dict = {(sym, dt): (h, l, c) for sym, dt, h, l, c in sym_1d_rows}

def get_regime(d):
    for i in range(1, 15):
        v = spy_dict.get(d - timedelta(days=i))
        if v is not None:
            return v
    return 'neutral'

def regime_ok(row):
    reg = row['regime']
    dir_ = row['direction']
    return (reg == 'neutral') or (reg == 'bull' and dir_ == 'bullish') or (reg == 'bear' and dir_ == 'bearish')

def add_slip(df):
    df = df.copy()
    df['pnl_r_adj'] = (df['pnl_r']
        - 0.03 / df['risk_pct']
        - np.where(df['outcome'] == 'stop', 0.05 / df['risk_pct'], 0.0))
    df['win'] = df['pnl_r_adj'] > 0
    return df

# ── Load 5m dataset ───────────────────────────────────────────────────────────
print("Loading val_5m_expanded.csv...", flush=True)
df5 = pd.read_csv('/app/data/val_5m_expanded.csv')
df5['ts']   = pd.to_datetime(df5['pattern_timestamp'], utc=True)
df5['_d']   = df5['ts'].apply(lambda x: x.date())
df5['regime'] = df5['_d'].apply(get_regime)
df5['year'] = df5['ts'].dt.year

if TZ_ET:
    df5['ts_et']   = df5['ts'].dt.tz_convert(TZ_ET)
    df5['hour_et'] = df5['ts_et'].dt.hour
    df5['min_et']  = df5['ts_et'].dt.minute
else:
    df5['ts_et']   = df5['ts']
    df5['hour_et'] = (df5['ts'].dt.hour - 4) % 24
    df5['min_et']  = df5['ts'].dt.minute

# Filtri base (SENZA filtro simbolo — includiamo anche i blocked per riesaminarli)
base_all = add_slip(df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (df5['pattern_name'] != 'engulfing_bullish') &
    df5.apply(regime_ok, axis=1)
].copy())

print(f"  Base (tutti simboli, no engulf, regime, risk OK): {len(base_all):,}", flush=True)

# ── Fetch candle OHLC per at_extreme ─────────────────────────────────────────
print("Fetching 5m candle OHLC for at_extreme...", flush=True)
# Solo quelli in finestra 11-14 ET (necessari per MIDDAY_F)
midday_rows = base_all[base_all['hour_et'].between(11, 14)]
print(f"  Righe midday (11-14 ET): {len(midday_rows):,}", flush=True)

conn2 = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                         user='postgres', password='postgres')
cur2  = conn2.cursor()
cur2.execute("CREATE TEMP TABLE _tt (sym VARCHAR(20), ts TIMESTAMPTZ) ON COMMIT DELETE ROWS")
cur2.executemany("INSERT INTO _tt VALUES (%s,%s)",
                 [(r['symbol'], r['ts']) for _, r in midday_rows.iterrows()])
cur2.execute("""
    SELECT c.symbol, c.timestamp, c.high::float, c.low::float, c.close::float
    FROM candles c JOIN _tt t ON c.symbol=t.sym AND c.timestamp=t.ts
    WHERE c.timeframe='5m'
""")
candle_data = {(sym, pd.Timestamp(ts)): (h, l, cl)
               for sym, ts, h, l, cl in cur2.fetchall()}
conn2.close()
print(f"  Candle OHLC matched: {len(candle_data):,}/{len(midday_rows):,}", flush=True)

# ── Compute at_extreme per midday rows ────────────────────────────────────────
print("Computing at_extreme...", flush=True)
c_low = []; c_high = []; d_high = []; d_low = []
for _, row in midday_rows.iterrows():
    cd = candle_data.get((row['symbol'], row['ts']), (np.nan, np.nan, np.nan))
    sd = sym_1d_dict.get((row['symbol'], row['_d']), (np.nan, np.nan, np.nan))
    c_high.append(cd[0]); c_low.append(cd[1])
    d_high.append(sd[0]); d_low.append(sd[1])

midday_ext = midday_rows.copy()
midday_ext['c_low']  = c_low;  midday_ext['c_high']  = c_high
midday_ext['d_low']  = d_low;  midday_ext['d_high']  = d_high

day_range = midday_ext['d_high'] - midday_ext['d_low']
midday_ext['dist_extreme'] = np.where(
    midday_ext['direction'] == 'bullish',
    np.where(day_range > 0, (midday_ext['c_low'] - midday_ext['d_low']) / day_range, np.nan),
    np.where(day_range > 0, (midday_ext['d_high'] - midday_ext['c_high']) / day_range, np.nan)
)
midday_ext['at_extreme'] = midday_ext['dist_extreme'] < 0.10

# ── Assemble TRIPLO ───────────────────────────────────────────────────────────
alpha  = base_all[base_all['hour_et'] == 15].copy()
mid_f  = midday_ext[
    midday_ext['at_extreme'] &
    (midday_ext['bars_to_entry'] == 1)
].copy()
triplo = pd.concat([alpha, mid_f], ignore_index=True)

print(f"  ALPHA (15:xx): {len(alpha):,}", flush=True)
print(f"  MIDDAY_F (11-14, estremo+BTE=1): {len(mid_f):,}", flush=True)
print(f"  TRIPLO totale: {len(triplo):,}", flush=True)

# ── Helper functions ───────────────────────────────────────────────────────────
def sym_stats(df, label=""):
    n   = len(df)
    if n == 0:
        return {"n": 0, "avg": float("nan"), "wr": float("nan")}
    avg = df['pnl_r_adj'].mean()
    wr  = df['win'].mean() * 100
    return {"n": n, "avg": avg, "wr": wr}

def oos_row(df, sym_label=""):
    parts = []
    vals  = []
    for yr in [2024, 2025, 2026]:
        s = df[df['year'] == yr]
        n = len(s)
        v = s['pnl_r_adj'].mean() if n >= 3 else float('nan')
        vs = f"{'N/A':>7}" if np.isnan(v) else f"{v:>+7.3f}"
        parts.append(f"{vs}({n:>3})")
        vals.append((v, n))
    ok  = sum(1 for v, _ in vals if not np.isnan(v) and v > 0)
    tot = sum(1 for v, _ in vals if not np.isnan(v))
    stab = 'SI  ' if (ok == tot and tot >= 2) else ('PARZ' if ok >= 2 else 'NO  ')
    return parts, stab

BLOCKED_BASE = ['SPY', 'AAPL', 'MSFT', 'GOOGL', 'WMT', 'DELL']
WATCHLIST_NEG = ['RIVN', 'RXRX', 'VKTX', 'SMR', 'LUNR']

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SECTION 1 — SIMBOLI BLOCCATI: performance TRIPLO")
print("  (bloccati perché negativi pre-TRIPLO: SPY, AAPL, MSFT, GOOGL, WMT, DELL)")
print(SEP)
print(f"\n  {'Simbolo':<8}  {'n_tot':>6}  {'avg+slip':>9}  {'WR':>6}  "
      f"{'2024':>9}(n)    {'2025':>9}(n)    {'2026':>9}(n)   Stab?  Blocco?")
print("  " + SEP2)

for sym in BLOCKED_BASE:
    sub = triplo[triplo['symbol'] == sym]
    st  = sym_stats(sub)
    if st['n'] == 0:
        print(f"  {sym:<8}  {'0':>6}  {'N/A':>9}  {'N/A':>6}  — no data —")
        continue
    parts, stab = oos_row(sub)
    avg_s  = f"{st['avg']:>+9.3f}" if not np.isnan(st['avg']) else f"{'N/A':>9}"
    wr_s   = f"{st['wr']:>5.1f}%" if not np.isnan(st['wr']) else f"{'N/A':>6}"
    # Blocking recommendation
    blocco = "MANTIENI" if (np.isnan(st['avg']) or st['avg'] < 0 or stab in ('NO  ', 'PARZ')) else "RIMUOVI "
    print(f"  {sym:<8}  {st['n']:>6,}  {avg_s}  {wr_s}  "
          f"{'  '.join(parts)}  {stab}  {blocco}")

# ── Breakdown per componente dei blocked ──────────────────────────────────────
print(f"\n  Dettaglio per componente (ALPHA vs MIDDAY_F):")
print(f"  {'Simbolo':<8}  {'Comp':<10}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}")
print("  " + "─" * 48)
for sym in BLOCKED_BASE:
    for comp_lbl, comp_df in [('ALPHA', alpha), ('MIDDAY_F', mid_f)]:
        sub = comp_df[comp_df['symbol'] == sym]
        if len(sub) == 0:
            continue
        print(f"  {sym:<8}  {comp_lbl:<10}  {len(sub):>5,}  "
              f"{sub['pnl_r_adj'].mean():>+9.3f}  {sub['win'].mean()*100:>5.1f}%")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SECTION 2 — WATCHLIST NEGATIVA: performance TRIPLO")
print("  (RIVN, RXRX, VKTX, SMR, LUNR — erano negativi sul config precedente)")
print(SEP)
print(f"\n  {'Simbolo':<8}  {'n_tot':>6}  {'avg+slip':>9}  {'WR':>6}  "
      f"{'2024':>9}(n)    {'2025':>9}(n)    {'2026':>9}(n)   Stab?  Azione")
print("  " + SEP2)

for sym in WATCHLIST_NEG:
    sub = triplo[triplo['symbol'] == sym]
    st  = sym_stats(sub)
    if st['n'] == 0:
        print(f"  {sym:<8}  {'0':>6}  {'N/A':>9}  {'N/A':>6}  — no data —")
        continue
    parts, stab = oos_row(sub)
    avg_s  = f"{st['avg']:>+9.3f}" if not np.isnan(st['avg']) else f"{'N/A':>9}"
    wr_s   = f"{st['wr']:>5.1f}%" if not np.isnan(st['wr']) else f"{'N/A':>6}"
    # Watchlist recommendation
    if np.isnan(st['avg']) or st['avg'] < 0:
        azione = "BLOCCA  "
    elif stab == 'SI  ' and st['avg'] > 0:
        azione = "OK KEEP "
    else:
        azione = "WATCH   "
    print(f"  {sym:<8}  {st['n']:>6,}  {avg_s}  {wr_s}  "
          f"{'  '.join(parts)}  {stab}  {azione}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SECTION 3 — TUTTI I SIMBOLI UNIVERSO 5m (TRIPLO config, no blocked)")
print("  Ranking per avg+slip, min 5 trade totali")
print(SEP)

# Escludi blocked base per il ranking pulito
BLOCKED_SET = frozenset(BLOCKED_BASE)
triplo_clean = triplo[~triplo['symbol'].isin(BLOCKED_SET)].copy()
all_syms = sorted(triplo_clean['symbol'].unique())

rows = []
for sym in all_syms:
    sub = triplo_clean[triplo_clean['symbol'] == sym]
    if len(sub) < 5:
        continue
    st = sym_stats(sub)
    # OOS stability
    vals = []
    for yr in [2024, 2025, 2026]:
        s = sub[sub['year'] == yr]
        v = s['pnl_r_adj'].mean() if len(s) >= 3 else float('nan')
        vals.append(v)
    ok  = sum(1 for v in vals if not np.isnan(v) and v > 0)
    tot = sum(1 for v in vals if not np.isnan(v))
    stab = 'SI' if (ok == tot and tot >= 2) else ('PARZ' if ok >= 2 else 'NO')

    # Per-year counts
    n24 = len(sub[sub['year'] == 2024])
    n25 = len(sub[sub['year'] == 2025])
    n26 = len(sub[sub['year'] == 2026])
    v24 = sub[sub['year'] == 2024]['pnl_r_adj'].mean() if n24 >= 3 else float('nan')
    v25 = sub[sub['year'] == 2025]['pnl_r_adj'].mean() if n25 >= 3 else float('nan')
    v26 = sub[sub['year'] == 2026]['pnl_r_adj'].mean() if n26 >= 3 else float('nan')

    rows.append({
        'symbol': sym,
        'n': st['n'],
        'avg': st['avg'],
        'wr': st['wr'],
        'stab': stab,
        'v24': v24, 'n24': n24,
        'v25': v25, 'n25': n25,
        'v26': v26, 'n26': n26,
    })

rank_df = pd.DataFrame(rows).sort_values('avg', ascending=False)

print(f"\n  {'#':>3}  {'Simbolo':<8}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  "
      f"{'2024':>9}(n)  {'2025':>9}(n)  {'2026':>9}(n)  Stab")
print("  " + "─" * 90)

for i, (_, r) in enumerate(rank_df.iterrows(), 1):
    v24s = f"{r['v24']:>+9.3f}" if not np.isnan(r['v24']) else f"{'N/A':>9}"
    v25s = f"{r['v25']:>+9.3f}" if not np.isnan(r['v25']) else f"{'N/A':>9}"
    v26s = f"{r['v26']:>+9.3f}" if not np.isnan(r['v26']) else f"{'N/A':>9}"
    avg_s = f"{r['avg']:>+9.3f}" if not np.isnan(r['avg']) else f"{'N/A':>9}"
    wr_s  = f"{r['wr']:>5.1f}%" if not np.isnan(r['wr']) else f"{'N/A':>6}"
    marker = " ★" if (r['stab'] == 'SI' and not np.isnan(r['avg']) and r['avg'] > 0) else ""
    print(f"  {i:>3}  {r['symbol']:<8}  {r['n']:>5,}  {avg_s}  {wr_s}  "
          f"{v24s}({r['n24']:>3})  {v25s}({r['n25']:>3})  {v26s}({r['n26']:>3})  "
          f"{r['stab']}{marker}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SECTION 4 — SUMMARY STATISTICHE UNIVERSO")
print(SEP)

total_syms  = len(rank_df)
pos_avg     = (rank_df['avg'] > 0).sum()
stable_si   = (rank_df['stab'] == 'SI').sum()
stable_parz = (rank_df['stab'] == 'PARZ').sum()
both_ok     = ((rank_df['avg'] > 0) & (rank_df['stab'] == 'SI')).sum()
neg_syms    = (rank_df['avg'] < 0).sum()

print(f"\n  Simboli analizzati (n≥5):        {total_syms}")
print(f"  avg+slip > 0:                    {pos_avg} ({pos_avg/total_syms*100:.0f}%)")
print(f"  Stabili OOS (SI):                {stable_si} ({stable_si/total_syms*100:.0f}%)")
print(f"  Stabili OOS (PARZ):              {stable_parz} ({stable_parz/total_syms*100:.0f}%)")
print(f"  avg>0 E OOS stabile (top tier):  {both_ok} ({both_ok/total_syms*100:.0f}%)")
print(f"  Negativi (avg+slip < 0):         {neg_syms} ({neg_syms/total_syms*100:.0f}%)")

print(f"\n  TOP 10 per avg+slip:")
print(f"  {'Simbolo':<8}  {'avg+slip':>9}  {'WR':>6}  {'n':>5}  Stab")
print("  " + "─" * 40)
for _, r in rank_df.head(10).iterrows():
    avg_s = f"{r['avg']:>+9.3f}" if not np.isnan(r['avg']) else f"{'N/A':>9}"
    wr_s  = f"{r['wr']:>5.1f}%" if not np.isnan(r['wr']) else f"{'N/A':>6}"
    print(f"  {r['symbol']:<8}  {avg_s}  {wr_s}  {r['n']:>5,}  {r['stab']}")

print(f"\n  BOTTOM 10 (potenziali da bloccare):")
print(f"  {'Simbolo':<8}  {'avg+slip':>9}  {'WR':>6}  {'n':>5}  Stab")
print("  " + "─" * 40)
for _, r in rank_df.tail(10).sort_values('avg').iterrows():
    avg_s = f"{r['avg']:>+9.3f}" if not np.isnan(r['avg']) else f"{'N/A':>9}"
    wr_s  = f"{r['wr']:>5.1f}%" if not np.isnan(r['wr']) else f"{'N/A':>6}"
    print(f"  {r['symbol']:<8}  {avg_s}  {wr_s}  {r['n']:>5,}  {r['stab']}")

# ── Simboli con n < 5 (troppo pochi dati) ─────────────────────────────────────
sparse_syms = [sym for sym in all_syms if len(triplo_clean[triplo_clean['symbol'] == sym]) < 5]
if sparse_syms:
    print(f"\n  Simboli con < 5 trade (esclusi dal ranking): {len(sparse_syms)}")
    print(f"  {', '.join(sorted(sparse_syms))}")

# ── Dettaglio blocked symbols con TRIPLO (incluso conteggio per componente) ───
print(f"\n{SEP}")
print("SECTION 5 — DETTAGLIO PER BLOCKED: pattern breakdown")
print(SEP)

for sym in BLOCKED_BASE:
    sub = triplo[triplo['symbol'] == sym]
    if len(sub) == 0:
        print(f"\n  {sym}: nessun trade con TRIPLO config")
        continue
    print(f"\n  {sym}  (n_tot={len(sub)}, avg+slip={sub['pnl_r_adj'].mean():+.3f}, WR={sub['win'].mean()*100:.1f}%)")
    # Per pattern
    for pat in sorted(sub['pattern_name'].unique()):
        sp = sub[sub['pattern_name'] == pat]
        print(f"    {pat:<30}  n={len(sp):>4}  avg={sp['pnl_r_adj'].mean():>+7.3f}  WR={sp['win'].mean()*100:.1f}%")
    # Per direction
    print(f"    {'bullish':<30}  n={len(sub[sub['direction']=='bullish']):>4}  avg={sub[sub['direction']=='bullish']['pnl_r_adj'].mean():>+7.3f}")
    print(f"    {'bearish':<30}  n={len(sub[sub['direction']=='bearish']):>4}  avg={sub[sub['direction']=='bearish']['pnl_r_adj'].mean():>+7.3f}")

print(f"\n{SEP}")
print("DONE — symbol_review_triplo.py")
print(SEP)
