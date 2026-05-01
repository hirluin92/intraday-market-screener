#!/usr/bin/env python3
"""ANALISI PROFONDA 5m — 12 variabili nascoste. PH 14-16, 6 pattern."""
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

# ═══ Regime & base setup ══════════════════════════════════════════════════
print("Setup...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()

cur.execute("""SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
               FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp""")
spy_df = pd.DataFrame(cur.fetchall(), columns=['date','close'])
spy_df['ema50'] = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']   = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = np.where(spy_df['pct']>2,'bull', np.where(spy_df['pct']<-2,'bear','neutral'))
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

def get_regime(d):
    for i in range(1,15):
        v = spy_dict.get(d - timedelta(days=i))
        if v is not None: return v
    return 'neutral'

# ═══ Load & filter dataset ════════════════════════════════════════════════
print("Loading dataset...", flush=True)
df = pd.read_csv('/app/data/val_5m_expanded.csv')
df['ts']     = pd.to_datetime(df['pattern_timestamp'], utc=True)
df['_d']     = df['ts'].apply(lambda x: x.date())
df['regime'] = df['_d'].apply(get_regime)
df['year']   = df['ts'].dt.year

if TZ_ET:
    df['ts_et']    = df['ts'].dt.tz_convert(TZ_ET)
    df['hour_et']  = df['ts_et'].dt.hour
    df['min_et']   = df['ts_et'].dt.minute
    df['dow']      = df['ts_et'].dt.dayofweek
    df['month']    = df['ts_et'].dt.month
else:
    df['hour_et']  = (df['ts'].dt.hour - 4) % 24
    df['min_et']   = df['ts'].dt.minute
    df['dow']      = df['ts'].dt.dayofweek
    df['month']    = df['ts'].dt.month

BLOCKED = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})
regime_ok = (
    ((df['regime']=='bull')    & (df['direction']=='bullish')) |
    ((df['regime']=='bear')    & (df['direction']=='bearish')) |
    (df['regime']=='neutral')
)

base = df[
    (df['entry_filled']==True) &
    (df['risk_pct']>=0.50) & (df['risk_pct']<=2.00) &
    (~df['symbol'].isin(BLOCKED)) &
    (df['pattern_name']!='engulfing_bullish') &
    regime_ok &
    df['hour_et'].between(14,15)
].copy()

base['pnl_r_adj'] = (
    base['pnl_r']
    - 0.03/base['risk_pct']
    - np.where(base['outcome']=='stop', 0.05/base['risk_pct'], 0.0)
)
base['win'] = base['pnl_r_adj'] > 0
print(f"Base PH dataset: n={len(base):,}", flush=True)

# ═══ Batch DB queries ════════════════════════════════════════════════════
unique_dates  = list(base['_d'].unique())
unique_syms   = list(base['symbol'].unique())

# ── 1. VIX 1d (or SPY realized vol proxy) ──────────────────────────────
print("Fetching VIX...", flush=True)
cur.execute("""SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
               FROM candles WHERE symbol=ANY(%s) AND timeframe='1d'
               ORDER BY timestamp""", (["^VIX","VIX","VIXY"],))
vix_rows = cur.fetchall()
if vix_rows:
    vix_dict_raw = dict(vix_rows)
    vix_is_proxy = False
    print(f"  VIX: {len(vix_rows)} rows")
else:
    # SPY realized vol 20d as proxy
    spy_ret = spy_df['close'].pct_change()
    rvol = spy_ret.rolling(20).std() * np.sqrt(252) * 100
    vix_dict_raw = dict(zip(spy_df['date'], rvol))
    vix_is_proxy = True
    print("  VIX not in DB → SPY 20d realized vol as proxy")

def get_vix(d):
    for i in range(0,5):
        v = vix_dict_raw.get(d - timedelta(days=i))
        if v is not None and not (isinstance(v,float) and np.isnan(v)):
            return float(v)
    return None

# ── 2. SPY 5m (pre-PH trend + PH correlation) ───────────────────────────
print("Fetching SPY 5m...", flush=True)
cur.execute("""
    SELECT DATE(timestamp AT TIME ZONE 'America/New_York') AS d,
           EXTRACT(HOUR   FROM timestamp AT TIME ZONE 'America/New_York')::int AS h,
           EXTRACT(MINUTE FROM timestamp AT TIME ZONE 'America/New_York')::int AS m,
           open::float, close::float
    FROM candles
    WHERE symbol='SPY' AND timeframe='5m'
      AND DATE(timestamp AT TIME ZONE 'America/New_York') = ANY(%s)
    ORDER BY timestamp
""", (unique_dates,))
spy5_rows = cur.fetchall()
spy5 = pd.DataFrame(spy5_rows, columns=['date','h','m','open','close'])
spy5['date'] = pd.to_datetime(spy5['date']).dt.date
spy5['t_min'] = spy5['h']*60 + spy5['m']
print(f"  SPY 5m: {len(spy5):,} rows")

# Pre-PH: open 9:30 → last close before 14:00
preph_ret = {}
for d, grp in spy5.groupby('date'):
    morning = grp[(grp['h']==9) & (grp['m']==30)]
    before  = grp[grp['h']<14]
    if len(morning)>0 and len(before)>0:
        preph_ret[d] = (before.iloc[-1]['close'] - morning.iloc[0]['open']) / morning.iloc[0]['open'] * 100

# PH SPY: cumulative return from 14:00 → per date+minute dict
ph_spy_ret = {}   # (date, t_min) -> cum_ret from ph open
for d, grp in spy5.groupby('date'):
    ph = grp[(grp['h']>=14) & (grp['h']<16)].sort_values('t_min')
    if len(ph)==0: continue
    ph_open = ph.iloc[0]['open']
    for _, r in ph.iterrows():
        ph_spy_ret[(d, int(r['t_min']))] = (r['close'] - ph_open) / ph_open * 100

# ── 3. Symbol 1d OHLC (for H/L position) ───────────────────────────────
print("Fetching symbol 1d OHLC...", flush=True)
cur.execute("""
    SELECT symbol, DATE(timestamp AT TIME ZONE 'UTC'), high::float, low::float
    FROM candles
    WHERE symbol=ANY(%s) AND timeframe='1d'
      AND DATE(timestamp AT TIME ZONE 'UTC') = ANY(%s)
""", (unique_syms, unique_dates))
sym1d = {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}
print(f"  Symbol 1d OHLC: {len(sym1d):,} rows")

# ── 4. Pattern candle OHLC (for candle range) via temp table ────────────
print("Fetching pattern candle OHLC...", flush=True)
cur.execute("""
    CREATE TEMP TABLE _trade_ts (symbol VARCHAR(20), ts TIMESTAMPTZ)
    ON COMMIT DELETE ROWS
""")
rows_to_insert = [(row['symbol'], row['ts']) for _, row in base.iterrows()]
cur.executemany("INSERT INTO _trade_ts VALUES (%s,%s)", rows_to_insert)
cur.execute("""
    SELECT c.symbol, c.timestamp, c.high::float, c.low::float, c.close::float
    FROM candles c
    JOIN _trade_ts t ON c.symbol=t.symbol AND c.timestamp=t.ts
    WHERE c.timeframe='5m'
""")
candle_ohlc = {}
for sym, ts, h, l, c in cur.fetchall():
    candle_ohlc[(sym, pd.Timestamp(ts))] = (h, l, c)
print(f"  Pattern candle OHLC: {len(candle_ohlc):,} rows")
conn.close()

# ═══ Compute derived features ═════════════════════════════════════════════
print("Computing features...", flush=True)
b = base.copy()

# 1. Day of week / month (already in df)
DOW = {0:'Lun',1:'Mar',2:'Mer',3:'Gio',4:'Ven'}
MON = {1:'Gen',2:'Feb',3:'Mar',4:'Apr',5:'Mag',6:'Giu',
       7:'Lug',8:'Ago',9:'Set',10:'Ott',11:'Nov',12:'Dic'}
b['dow_name']   = b['dow'].map(DOW)
b['month_name'] = b['month'].map(MON)

# 3. VIX band
b['vix'] = b['_d'].apply(get_vix)
def vix_band(v):
    if v is None or (isinstance(v,float) and np.isnan(v)): return 'N/A'
    if v<15: return '1 <15 (calm)'
    if v<20: return '2 15-20'
    if v<25: return '3 20-25'
    if v<35: return '4 25-35 (elevated)'
    return '5 >35 (panic)'
b['vix_band'] = b['vix'].apply(vix_band)

# 4. Pre-PH trend
b['preph_ret'] = b['_d'].apply(lambda d: preph_ret.get(d))
def preph_band(r):
    if r is None or (isinstance(r,float) and np.isnan(r)): return 'N/A'
    if r>1.0:  return '1 >+1% (forte rialzo)'
    if r>0.0:  return '2 0 a +1% (rialzo)'
    if r>-1.0: return '3 -1 a 0% (ribasso)'
    return '4 <-1% (forte ribasso)'
b['preph_band'] = b['preph_ret'].apply(preph_band)

# 4b. Pre-PH per direzione trade
b['preph_aligned'] = b.apply(lambda r:
    ('aligned' if (r['direction']=='bullish' and (r['preph_ret'] or 0)>0) or
                  (r['direction']=='bearish' and (r['preph_ret'] or 0)<0)
     else 'counter') if r['preph_ret'] is not None else 'N/A', axis=1)

# 5. H/L position
def hl_pos(row):
    hl = sym1d.get((row['symbol'], row['_d']))
    if hl is None: return None
    h,l = hl
    return (row['entry_price']-l)/(h-l) if h>l else 0.5
b['hl_pos'] = b.apply(hl_pos, axis=1)
def hl_band(p):
    if p is None or (isinstance(p,float) and np.isnan(p)): return 'N/A'
    if p>=0.9: return '1 Top 10% (near high)'
    if p>=0.5: return '2 Upper 50-90%'
    if p>=0.1: return '3 Lower 10-50%'
    return '4 Bottom 10% (near low)'
b['hl_band'] = b['hl_pos'].apply(hl_band)

# 7. Candle size vs stop (proxy for candle/ATR ratio)
def candle_ratio(row):
    oc = candle_ohlc.get((row['symbol'], row['ts']))
    if oc is None: return None
    h,l,c = oc
    candle_pct = (h-l)/c*100 if c>0 else None
    if candle_pct is None: return None
    return candle_pct / row['risk_pct']  # candle range / stop distance
b['candle_ratio'] = b.apply(candle_ratio, axis=1)
def candle_band(r):
    if r is None or (isinstance(r,float) and np.isnan(r)): return 'N/A'
    if r<0.5:  return '1 <0.5× (piccola)'
    if r<1.0:  return '2 0.5-1.0×'
    if r<1.5:  return '3 1.0-1.5×'
    if r<2.5:  return '4 1.5-2.5×'
    return '5 >2.5× (grande/volatile)'
b['candle_band'] = b['candle_ratio'].apply(candle_band)

# 8. Consecutive signals same symbol, same day
b_s = b.sort_values(['symbol','_d','ts']).copy()
sig_cnt = {}
sig_list = []
for _, row in b_s.iterrows():
    key = (row['symbol'], row['_d'])
    sig_cnt[key] = sig_cnt.get(key,0)+1
    sig_list.append(min(sig_cnt[key],3))
b_s['sig_n'] = sig_list
b = b.merge(b_s[['opportunity_id','sig_n']], on='opportunity_id', how='left')
SIG = {1:'1° segnale',2:'2° segnale',3:'3°+ segnale'}
b['sig_band'] = b['sig_n'].map(SIG)

# 9. SPY PH correlation
def spy_ph(row):
    d = row['_d']
    t_min = row['hour_et']*60 + row['min_et']
    # Find closest bar at or before trade time
    best = None
    for dt in range(-5,6):
        v = ph_spy_ret.get((d, t_min + dt))
        if v is not None:
            best = v
            break
    return best
b['spy_ph_ret'] = b.apply(spy_ph, axis=1)
def spy_band(r):
    if r is None or (isinstance(r,float) and np.isnan(r)): return 'N/A'
    if r>0.3:   return '1 SPY >+0.3% (sale)'
    if r>-0.3:  return '2 SPY ±0.3% (flat)'
    return '3 SPY <-0.3% (scende)'
b['spy_band'] = b['spy_ph_ret'].apply(spy_band)

# 9b. SPY aligned with trade direction
b['spy_dir_aligned'] = b.apply(lambda r:
    'aligned' if (r['direction']=='bullish' and (r['spy_ph_ret'] or 0)>0.1) or
                 (r['direction']=='bearish' and (r['spy_ph_ret'] or 0)<-0.1)
    else ('counter' if r['spy_ph_ret'] is not None else 'N/A'), axis=1)

# 10. Bars to exit
def bex_band(bx):
    if pd.isna(bx): return 'N/A'
    bx = int(bx)
    if bx<=3: return '1  1-3 bar (15 min)'
    if bx<=6: return '2  4-6 bar (30 min)'
    if bx<=12: return '3  7-12 bar (1h)'
    return '4  13+ bar (>1h)'
b['bex_band'] = b['bars_to_exit'].apply(bex_band)

# 6. Bars to entry
def bte_band(bt):
    if pd.isna(bt): return 'N/A'
    bt = int(bt)
    if bt==1: return '1  1 barra (5 min)'
    if bt==2: return '2  2 barre (10 min)'
    if bt==3: return '3  3 barre (15 min)'
    return '4  4+ barre'
b['bte_band'] = b['bars_to_entry'].apply(bte_band)

# 11. PH slot (per minuto preciso)
def ph_slot(row):
    h,m = row['hour_et'], row['min_et']
    t = h*60+m
    if t<845:   return '1  14:00-14:04'   # 840=14:00
    if t<870:   return '2  14:05-14:29'   # 870=14:30
    if t<900:   return '3  14:30-14:59'   # 900=15:00
    if t<930:   return '4  15:00-15:29'   # 930=15:30
    return       '5  15:30-15:59'
b['ph_slot'] = b.apply(ph_slot, axis=1)

# 12. Entry price level (spread proxy)
def price_band(p):
    if p<20:  return '1 <$20'
    if p<50:  return '2 $20-50'
    if p<100: return '3 $50-100'
    if p<200: return '4 $100-200'
    return '5 >$200'
b['price_band'] = b['entry_price'].apply(price_band)

print(f"Features done. Coverage check:")
for col,lbl in [('vix','VIX'),('preph_ret','Pre-PH'),('hl_pos','H/L'),
                ('candle_ratio','Candle'),('spy_ph_ret','SPY PH')]:
    nn = b[col].notna().sum()
    print(f"  {lbl}: {nn}/{len(b)} ({nn/len(b)*100:.0f}%)")

SEP  = '═'*72
SEP2 = '─'*66

def T(df_in, gcol, order=None, min_n=1, note=''):
    """Print analysis table."""
    t = df_in.groupby(gcol).apply(lambda g: pd.Series({
        'n':        len(g),
        'avg+slip': round(g['pnl_r_adj'].mean(),3),
        'WR%':      round(g['win'].mean()*100,1)
    })).reset_index()
    t = t[t['n']>=min_n]
    if order:
        t[gcol] = pd.Categorical(t[gcol], categories=order, ordered=True)
        t.sort_values(gcol, inplace=True)
    else:
        t.sort_values(gcol, inplace=True)
    if note: print(f"  ({note})")
    print(f"  {gcol:<32} {'n':>5}  {'avg+slip':>9}  {'WR%':>6}")
    print(f"  {SEP2}")
    for _, r in t.iterrows():
        print(f"  {str(r[gcol]):<32} {r['n']:>5,}  {r['avg+slip']:>9.3f}  {r['WR%']:>6.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 1 — GIORNO DELLA SETTIMANA
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("1. GIORNO DELLA SETTIMANA (PH 14-16 ET)")
print(SEP)
T(b, 'dow_name', order=['Lun','Mar','Mer','Gio','Ven'])

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 2 — STAGIONALITÀ MENSILE
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("2. STAGIONALITÀ MENSILE")
print(SEP)
T(b, 'month_name', order=['Gen','Feb','Mar','Apr','Mag','Giu','Lug','Ago','Set','Ott','Nov','Dic'])

print(f"\n  Stagioni:")
b['season'] = b['month'].map({12:'Inverno',1:'Inverno',2:'Inverno',
                               3:'Primavera',4:'Primavera',5:'Primavera',
                               6:'Estate',7:'Estate',8:'Estate',
                               9:'Autunno',10:'Autunno',11:'Autunno'})
T(b, 'season', order=['Primavera','Estate','Autunno','Inverno'])

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 3 — VIX
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
lbl3 = "VIX 1d" if not vix_is_proxy else "SPY Realized Vol 20d (proxy VIX)"
print(f"3. {lbl3.upper()} COME FILTRO")
print(SEP)
b_v = b[b['vix_band']!='N/A']
T(b_v, 'vix_band', note=f"n con dati VIX: {len(b_v)}/{len(b)}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 4 — TREND INTRADAY PRE-POWER HOURS
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("4. TREND INTRADAY PRE-POWER HOURS (9:30→14:00 SPY)")
print(SEP)
b_p = b[b['preph_band']!='N/A']
T(b_p, 'preph_band', note=f"n con dati SPY 5m: {len(b_p)}/{len(b)}")

print(f"\n  4b. Trade ALLINEATO vs CONTROTENDENZA rispetto al trend pre-PH:")
b_p2 = b[b['preph_aligned']!='N/A']
T(b_p2, 'preph_aligned')

print(f"\n  4c. Per direzione trade × trend pre-PH:")
b_p3 = b[b['preph_band']!='N/A'].copy()
b_p3['dir_preph'] = b_p3['direction'] + ' × ' + b_p3['preph_band'].str[2:]
t4c = b_p3.groupby('dir_preph').apply(lambda g: pd.Series({
    'n': len(g), 'avg+slip': round(g['pnl_r_adj'].mean(),3), 'WR%': round(g['win'].mean()*100,1)
})).reset_index()
t4c = t4c[t4c['n']>=10].sort_values('avg+slip', ascending=False)
for _,r in t4c.iterrows():
    print(f"  {r['dir_preph']:<40} n={r['n']:>4,}  avg+slip={r['avg+slip']:>7.3f}  WR={r['WR%']:.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 5 — DISTANZA DAL HIGH/LOW DEL GIORNO
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("5. POSIZIONE RISPETTO AL HIGH/LOW GIORNALIERO")
print(SEP)
b_hl = b[b['hl_band']!='N/A']
T(b_hl, 'hl_band', note=f"n con dati 1d: {len(b_hl)}/{len(b)}")

print(f"\n  5b. Per direzione:")
for direction in ['bullish','bearish']:
    sub = b_hl[b_hl['direction']==direction]
    print(f"\n  {direction}:")
    T(sub, 'hl_band')

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 6 — BARS TO ENTRY
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("6. BARS TO ENTRY (velocità fill)")
print(SEP)
T(b, 'bte_band')
print(f"\n  Nota: bars_to_entry=1 significa fill alla prima barra (5 min) dopo il pattern.")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 7 — DIMENSIONE CANDELA DEL PATTERN
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("7. DIMENSIONE CANDELA (candle range / stop distance)")
print(SEP)
b_c = b[b['candle_band']!='N/A']
T(b_c, 'candle_band', note=f"n con dati OHLC: {len(b_c)}/{len(b)}")
print(f"""
  Interpretazione ratio:
  - <0.5×: candela piccola, stop molto ampio → setup conservativo
  - 0.5-1.0×: candela ~= metà stop → normale
  - 1.0-1.5×: candela ≈ stop distance → stop al bordo della candela
  - >1.5×: candela molto grande → stop dentro la candela, rischio rumore""")

# Candle size per pattern
print(f"\n  Per pattern (n>=15):")
t7b = b_c.groupby(['pattern_name','candle_band']).apply(lambda g: pd.Series({
    'n': len(g), 'avg+slip': round(g['pnl_r_adj'].mean(),3)
})).reset_index()
t7b = t7b[t7b['n']>=15].sort_values(['pattern_name','candle_band'])
prev_pat = None
for _,r in t7b.iterrows():
    if r['pattern_name'] != prev_pat:
        print(f"  {r['pattern_name']}:")
        prev_pat = r['pattern_name']
    print(f"    {r['candle_band']:<22} n={r['n']:>4}  avg+slip={r['avg+slip']:>7.3f}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 8 — SEGNALI CONSECUTIVI STESSO SIMBOLO
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("8. SEGNALI CONSECUTIVI STESSO SIMBOLO (stesso giorno)")
print(SEP)
T(b, 'sig_band', order=['1° segnale','2° segnale','3°+ segnale'])

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 9 — CORRELAZIONE SPY INTRADAY
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("9. CORRELAZIONE SPY NELLE POWER HOURS (14:00 ET in poi)")
print(SEP)
b_s = b[b['spy_band']!='N/A']
T(b_s, 'spy_band', note=f"n con dati SPY PH: {len(b_s)}/{len(b)}")

print(f"\n  9b. Direzione trade × SPY direction:")
b_s2 = b_s.copy()
b_s2['dir_spy'] = b_s2['direction'] + ' × ' + b_s2['spy_band'].str[2:]
t9b = b_s2.groupby('dir_spy').apply(lambda g: pd.Series({
    'n': len(g), 'avg+slip': round(g['pnl_r_adj'].mean(),3), 'WR%': round(g['win'].mean()*100,1)
})).reset_index()
t9b = t9b[t9b['n']>=10].sort_values('avg+slip', ascending=False)
for _,r in t9b.iterrows():
    print(f"  {r['dir_spy']:<42} n={r['n']:>4,}  avg+slip={r['avg+slip']:>7.3f}  WR={r['WR%']:.1f}%")

print(f"\n  9c. Trade allineato/controtendenza a SPY:")
b_s3 = b[b['spy_dir_aligned']!='N/A']
T(b_s3, 'spy_dir_aligned')

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 10 — HOLDING PERIOD EFFETTIVO
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("10. HOLDING PERIOD EFFETTIVO (bars to exit)")
print(SEP)
b_bx = b[b['bars_to_exit'].notna()]
T(b_bx, 'bex_band')

print(f"\n  Per outcome:")
bx_out = b_bx.groupby(['bex_band','outcome']).size().unstack(fill_value=0)
pct = bx_out.div(bx_out.sum(axis=1), axis=0).mul(100).round(1)
cols = [c for c in ['tp2','tp1','timeout','stop'] if c in pct.columns]
print(pct[cols].to_string())

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 11 — SLOT DELLA PRIMA BARRA POWER HOURS
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("11. SLOT ORARIO PRECISO NELLE POWER HOURS")
print(SEP)
T(b, 'ph_slot')

print(f"\n  Per ora intera (14 vs 15 ET):")
T(b, 'hour_et', order=[14,15])

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 12 — PREZZO ENTRY (proxy spread bid-ask)
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("12. PREZZO ENTRY (proxy spread — spread relativo ∝ 1/prezzo)")
print(SEP)
T(b, 'price_band')

print(f"\n  12b. Top/bottom 10 simboli per prezzo medio:")
sym_price = b.groupby('symbol')['entry_price'].mean().sort_values()
print(f"  Più economici (spread maggiore):")
for s,p in sym_price.head(10).items():
    n = len(b[b['symbol']==s])
    avg = b[b['symbol']==s]['pnl_r_adj'].mean()
    print(f"    {s:<8} ${p:>7.2f}   n={n:>3}  avg+slip={avg:>7.3f}")
print(f"  Più costosi (spread minore):")
for s,p in sym_price.tail(10).items():
    n = len(b[b['symbol']==s])
    avg = b[b['symbol']==s]['pnl_r_adj'].mean()
    print(f"    {s:<8} ${p:>7.2f}   n={n:>3}  avg+slip={avg:>7.3f}")

# ═══════════════════════════════════════════════════════════════════════════
# RIEPILOGO INSIGHT
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("RIEPILOGO — VARIABILI SIGNIFICATIVE")
print(SEP)

insights = []
# DoW
dow_s = b.groupby('dow')['pnl_r_adj'].mean()
best_dow  = DOW[dow_s.idxmax()]
worst_dow = DOW[dow_s.idxmin()]
insights.append(f"DoW migliore: {best_dow} ({dow_s.max():+.3f}R)  peggiore: {worst_dow} ({dow_s.min():+.3f}R)")

# Month
mon_s = b.groupby('month')['pnl_r_adj'].mean()
best_mon  = MON[mon_s.idxmax()]
worst_mon = MON[mon_s.idxmin()]
insights.append(f"Mese migliore: {best_mon} ({mon_s.max():+.3f}R)  peggiore: {worst_mon} ({mon_s.min():+.3f}R)")

# VIX
b_v_s = b[b['vix_band']!='N/A']
if len(b_v_s)>0:
    vix_s = b_v_s.groupby('vix_band')['pnl_r_adj'].mean()
    insights.append(f"VIX: {vix_s.idxmax()} migliore ({vix_s.max():+.3f}R)")

# Pre-PH
b_pp = b[b['preph_aligned']!='N/A']
if len(b_pp)>0:
    pp_s = b_pp.groupby('preph_aligned')['pnl_r_adj'].mean()
    insights.append(f"Pre-PH aligned={pp_s.get('aligned',0):+.3f}R  counter={pp_s.get('counter',0):+.3f}R")

# BTE
bte_s = b.groupby('bte_band')['pnl_r_adj'].mean()
best_bte = bte_s.idxmax()
insights.append(f"Bars-to-entry migliore: {best_bte} ({bte_s.max():+.3f}R)")

# PH slot
slot_s = b.groupby('ph_slot')['pnl_r_adj'].mean()
best_slot = slot_s.idxmax()
insights.append(f"Slot migliore: {best_slot.strip()} ({slot_s.max():+.3f}R)")

# Price
price_s = b.groupby('price_band')['pnl_r_adj'].mean()
best_price = price_s.idxmax()
insights.append(f"Fascia prezzo migliore: {best_price.strip()} ({price_s.max():+.3f}R)")

print()
for ins in insights:
    print(f"  → {ins}")

print(f"\n=== DONE ===\n")
