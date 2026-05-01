#!/usr/bin/env python3
"""ANALISI COMPLETA 5m — 15 parti. val_5m_expanded.csv + filtri strutturali."""
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

# ═══════════════════════════════════════════════════════════════════════════
# LOAD & REGIME
# ═══════════════════════════════════════════════════════════════════════════
print("Loading data...", flush=True)
df = pd.read_csv('/app/data/val_5m_expanded.csv')

conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener', user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("""
    SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
    FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp
""")
spy_rows = cur.fetchall()

# Volume query for Part 11 — sample 3000 trades
print("Querying volume sample...", flush=True)
vol_sample_ids = df[df['entry_filled'] == True].sample(min(3000, df['entry_filled'].sum()), random_state=42)['opportunity_id'].tolist()

# Build opportunity → (symbol, ts) map for volume lookup
opp_map = df[df['opportunity_id'].isin(vol_sample_ids)][['opportunity_id','symbol','pattern_timestamp']].copy()
vol_data = {}
for _, row in opp_map.iterrows():
    ts_val = pd.to_datetime(row['pattern_timestamp'], utc=True)
    cur.execute("""
        SELECT volume::float FROM candles
        WHERE symbol=%s AND timeframe='5m' AND timestamp=%s LIMIT 1
    """, (row['symbol'], ts_val))
    res = cur.fetchone()
    if res and res[0] is not None:
        vol_data[row['opportunity_id']] = res[0]

conn.close()
print(f"Volume fetched for {len(vol_data)} trades", flush=True)

# ─── Regime ───────────────────────────────────────────────────────────────
spy_df = pd.DataFrame(spy_rows, columns=['date', 'close'])
spy_df['ema50'] = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct'] = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] > 2, 'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2, 'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

def get_regime(d) -> str:
    for i in range(1, 15):
        if (d - timedelta(days=i)) in spy_dict:
            return spy_dict[d - timedelta(days=i)]
    return 'neutral'

print("Parsing timestamps & computing regime...", flush=True)
df['ts'] = pd.to_datetime(df['pattern_timestamp'], utc=True)
df['_date'] = df['ts'].apply(lambda x: x.date())
df['regime'] = df['_date'].apply(get_regime)

if TZ_ET:
    df['ts_et'] = df['ts'].dt.tz_convert(TZ_ET)
    df['hour_et'] = df['ts_et'].dt.hour
    df['minute_et'] = df['ts_et'].dt.minute
else:
    df['hour_et'] = (df['ts'].dt.hour - 4) % 24
    df['minute_et'] = df['ts'].dt.minute

df['slot_et'] = df['hour_et'] * 100 + (df['minute_et'] // 30) * 30

# ═══════════════════════════════════════════════════════════════════════════
# STRUCTURAL FILTERS
# ═══════════════════════════════════════════════════════════════════════════
BLOCKED = {'SPY', 'AAPL', 'MSFT', 'GOOGL', 'WMT', 'DELL'}

# Regime filter: BULL→solo bullish, BEAR→solo bearish, NEUTRAL→entrambe
regime_ok = (
    ((df['regime'] == 'bull') & (df['direction'] == 'bullish')) |
    ((df['regime'] == 'bear') & (df['direction'] == 'bearish')) |
    (df['regime'] == 'neutral')
)

d = df[
    (df['entry_filled'] == True) &
    (df['risk_pct'] >= 0.50) &
    (df['risk_pct'] <= 2.00) &
    (~df['symbol'].isin(BLOCKED)) &
    regime_ok
].copy()

# Slippage: entry_slip = -0.03/risk_pct; stop_slip = -0.05/risk_pct (solo su stop)
d['pnl_r_adj'] = (
    d['pnl_r']
    - 0.03 / d['risk_pct']
    - np.where(d['outcome'] == 'stop', 0.05 / d['risk_pct'], 0.0)
)
d['win'] = d['pnl_r_adj'] > 0
d['year'] = d['ts'].dt.year
d['quarter'] = d['ts'].dt.to_period('Q').astype(str)

# Risk bands
risk_bins = [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.01]
risk_labels = ['0.50-0.75', '0.75-1.00', '1.00-1.25', '1.25-1.50', '1.50-1.75', '1.75-2.00']
d['risk_band'] = pd.cut(d['risk_pct'], bins=risk_bins, labels=risk_labels, right=False)

SEP = '═' * 78


def S(g):
    n = len(g)
    wr = g['win'].mean() * 100
    avg = g['pnl_r_adj'].mean()
    med = g['pnl_r_adj'].median()
    return pd.Series({'n': int(n), 'WR%': round(wr, 1), 'avg_r': round(avg, 3), 'med_r': round(med, 3)})


def T(df_):
    return df_.to_string(float_format=lambda x: f'{x:.3f}', index=False)


print(f"\n{SEP}")
print(f"DATASET DOPO FILTRI STRUTTURALI")
print(f"  n={len(d):,}  WR={d['win'].mean()*100:.1f}%  avg_r={d['pnl_r_adj'].mean():.3f}R  med_r={d['pnl_r_adj'].median():.3f}R")
print(f"  Anni: {sorted(d['year'].unique().tolist())}")
print(f"  Regime: {d['regime'].value_counts().to_dict()}")
print(f"  Simboli: {d['symbol'].nunique()}  Pattern: {d['pattern_name'].nunique()}")
print(SEP)

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 0 — STABILITÀ TEMPORALE
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 0 — STABILITÀ TEMPORALE")
print(SEP)

print("\n[0a] Per Anno:")
t = d.groupby('year').apply(S).reset_index()
print(T(t))

print("\n[0b] Per Trimestre:")
t = d.groupby('quarter').apply(S).reset_index()
print(T(t))

print("\n[0c] Per Regime (senza filtro regime):")
t = d.groupby('regime').apply(S).reset_index()
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 1 — TUTTI I PATTERN
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 1 — TUTTI I PATTERN (sorted by avg_r+slip)")
print(SEP)

print("\n[1a] Pattern × Direction:")
t = d.groupby(['pattern_name', 'direction']).apply(S).reset_index()
t = t.sort_values('avg_r', ascending=False)
print(T(t))

print("\n[1b] Pattern aggregato (tutte le direzioni):")
t = d.groupby('pattern_name').apply(S).reset_index()
t = t.sort_values('avg_r', ascending=False)
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 2 — REGIME × PATTERN × DIRECTION
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 2 — REGIME × PATTERN × DIRECTION (n>=10)")
print(SEP)

t = d.groupby(['regime', 'pattern_name', 'direction']).apply(S).reset_index()
t = t[t['n'] >= 10].sort_values(['regime', 'avg_r'], ascending=[True, False])
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 3 — SLOT 30min ET
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3 — GRANULARITÀ 30min (9:30-16:00 ET)")
print(SEP)

t = d.groupby('slot_et').apply(S).reset_index()
t['time_ET'] = t['slot_et'].apply(lambda x: f"{x//100:02d}:{x%100:02d}")
t = t.sort_values('slot_et')[['time_ET', 'n', 'WR%', 'avg_r', 'med_r']]
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 4 — SIMBOLI (n>=20)
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 4 — SIMBOLI (n>=20)")
print(SEP)

t = d.groupby('symbol').apply(S).reset_index()
t = t[t['n'] >= 20].sort_values('avg_r', ascending=False)
print(f"\nTop 15 (avg_r più alto):")
print(T(t.head(15)))
print(f"\nBottom 15 (avg_r più basso):")
print(T(t.tail(15)))
print(f"\nTotale simboli con n>=20: {len(t)}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 5 — FASCE RISK_PCT
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 5 — FASCE RISK_PCT (0.50–2.00%)")
print(SEP)

t = d.groupby('risk_band', observed=True).apply(S).reset_index()
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 6 — SCREENER SCORE
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 6 — SCREENER SCORE")
print(SEP)

t = d.groupby('screener_score').apply(S).reset_index()
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 7 — CONFLUENZA
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 7 — CONFLUENZA (pattern per stesso simbolo/timestamp)")
print(SEP)

conf_counts = d.groupby(['symbol', 'ts']).size().reset_index(name='n_conf')
d = d.merge(conf_counts, on=['symbol', 'ts'], how='left')
d['confluenza'] = d['n_conf'].clip(upper=3).astype(int).map({1: '1', 2: '2', 3: '3+'})

t = d.groupby('confluenza').apply(S).reset_index()
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 8 — PATTERN STRENGTH
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 8 — PATTERN STRENGTH BANDS")
print(SEP)

sbins = [0.54, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.92]
slabels = ['0.54-0.60', '0.60-0.65', '0.65-0.70', '0.70-0.75', '0.75-0.80', '0.80-0.85', '0.85-0.92']
d['str_band'] = pd.cut(d['pattern_strength'], bins=sbins, labels=slabels, right=False)
t = d.groupby('str_band', observed=True).apply(S).reset_index()
print(T(t))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 9 — ORA ET × REGIME
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 9 — ORA ET × REGIME (n>=10)")
print(SEP)

t = d.groupby(['hour_et', 'regime']).apply(S).reset_index()
t = t[t['n'] >= 10].sort_values(['hour_et', 'regime'])
print(T(t))

print("\n[9b] Solo ore 14-16 ET per regime:")
t2 = d[d['hour_et'].between(14, 15)].groupby(['hour_et', 'regime']).apply(S).reset_index()
print(T(t2))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 10 — OOS 2026 vs IS
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 10 — OOS 2026 vs IS (2023-2025)")
print(SEP)

d['period'] = d['year'].apply(lambda y: 'OOS_2026' if y >= 2026 else f'IS_{y}')
t = d.groupby('period').apply(S).reset_index()
print(T(t))

print("\n[10b] IS aggregato vs OOS:")
d['is_oos'] = d['year'] >= 2026
t2 = d.groupby('is_oos').apply(S).reset_index()
t2['label'] = t2['is_oos'].map({False: 'IS_2023-2025', True: 'OOS_2026'})
print(T(t2[['label', 'n', 'WR%', 'avg_r', 'med_r']]))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 11 — VOLUME (campione DB)
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 11 — VOLUME (quartili su campione DB)")
print(SEP)

if vol_data:
    d['volume'] = d['opportunity_id'].map(vol_data)
    sample_v = d[d['volume'].notna()].copy()
    sample_v['vol_q'] = pd.qcut(sample_v['volume'], q=4, labels=['Q1_low', 'Q2', 'Q3', 'Q4_high'],
                                 duplicates='drop')
    t = sample_v.groupby('vol_q', observed=True).apply(S).reset_index()
    print(T(t))
    print(f"\n(campione n={len(sample_v):,} su {len(d):,} trades filtrati)")

    # Volume threshold: above median
    med_vol = sample_v['volume'].median()
    sample_v['high_vol'] = sample_v['volume'] >= med_vol
    t2 = sample_v.groupby('high_vol').apply(S).reset_index()
    t2['label'] = t2['high_vol'].map({False: 'low_vol (< mediana)', True: 'high_vol (>= mediana)'})
    print(f"\n[11b] Volume above/below mediana ({med_vol:,.0f}):")
    print(T(t2[['label', 'n', 'WR%', 'avg_r', 'med_r']]))
else:
    print("Nessun dato volume trovato nel DB")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 12 — GAP/ORE APERTURA
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 12 — ORE APERTURA vs INTRADAY")
print(SEP)

d['open_window'] = d['hour_et'].apply(lambda h: (
    'open_30min (9:30-9:59)' if h == 9
    else ('open_60min (10:00-10:59)' if h == 10
          else ('mid (11-13)' if 11 <= h <= 13
                else ('power (14-15)' if 14 <= h <= 15
                      else 'close (16+)')))
))
t = d.groupby('open_window').apply(S).reset_index()
print(T(t))

print("\n[12b] Per ora ET (tutte):")
t2 = d.groupby('hour_et').apply(S).reset_index()
print(T(t2))

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 13 — SEGNALI SIMULTANEI
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 13 — SEGNALI SIMULTANEI (n trade stesso timestamp)")
print(SEP)

simul_counts = d.groupby('ts').size().reset_index(name='n_simul')
d = d.merge(simul_counts, on='ts', how='left')
d['simul_band'] = pd.cut(
    d['n_simul'], bins=[0, 1, 3, 10, 1000],
    labels=['solo (1)', 'piccolo (2-3)', 'medio (4-10)', 'grande (11+)']
)
t = d.groupby('simul_band', observed=True).apply(S).reset_index()
print(T(t))

print("\n[13b] Distribuzione n_simul per timestamp:")
sim_dist = d['n_simul'].value_counts().sort_index()
for v, c in sim_dist.items():
    if v <= 20:
        print(f"  n_simul={v:3d}: {c:6,} timestamps")
print(f"  n_simul>20:   {(d['n_simul']>20).sum():6,} timestamps")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 14 — OTTIMIZZAZIONE TP
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 14 — OTTIMIZZAZIONE TP (MFE proxy)")
print(SEP)

# Current TP1=2R, TP2=3.5R (confirmed from dataset stats earlier)
# For single-TP simulation at target X:
#   pnl_r >= X means TP hit (outcome=tp1 if pnl_r~2R, tp2 if pnl_r~3.5R)
#   outcome=stop → -1R
#   We use a threshold on pnl_r to simulate

print("[14a] Simulazione TP singolo (tutti gli outcome incluso timeout):")
print(f"  Nota: timeout → assume BE (0R) se TP non raggiunto")
print()
print(f"  {'TP_R':<6} {'n_hit':<7} {'n_stop':<7} {'n_timeout':<10} {'WR%':<7} {'avg_R_sim':<10} vs_current")

# Baseline (current TP1=2R, no split — no timeout counted as win)
baseline_pnl = d['pnl_r_adj'].copy()
baseline_avg = baseline_pnl.mean()

for tp_r in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5]:
    # Hit if pnl_r (before slip) >= tp_r - tolerance
    tol = 0.05
    hit = (d['pnl_r'] >= tp_r - tol)
    stop_mask = (d['outcome'] == 'stop')
    n_hit = hit.sum()
    n_stop_val = stop_mask.sum()
    n_timeout = (d['outcome'] == 'timeout').sum()
    n = len(d)

    sim_pnl = np.where(hit,
                       tp_r - 0.03 / d['risk_pct'],
                       np.where(stop_mask,
                                -1.0 - 0.03 / d['risk_pct'] - 0.05 / d['risk_pct'],
                                -0.03 / d['risk_pct']))  # timeout → entry slip only
    avg_sim = sim_pnl.mean()
    wr_sim = (sim_pnl > 0).mean() * 100
    diff = avg_sim - baseline_avg
    print(f"  {tp_r:<6.1f} {n_hit:<7,} {n_stop_val:<7,} {n_timeout:<10,} {wr_sim:<7.1f} {avg_sim:<10.3f} ({diff:+.3f})")

print(f"\n  baseline avg_r={baseline_avg:.3f}R  (TP1=2R, TP2=3.5R, timeout=0)")

print("\n[14b] Strategia split: 50% exit TP1, 50% trail a TP2:")
# tp2 hit → 0.5*2R + 0.5*3.5R = 2.75R
# tp1 hit, tp2 not → 0.5*2R + 0.5*0R = 1.0R (BE sul residuo)
# stop → -1R
# timeout → 0R
split_pnl = np.where(
    d['outcome'] == 'tp2',
    2.75,
    np.where(d['outcome'] == 'tp1',
             1.0,
             np.where(d['outcome'] == 'stop', -1.0, 0.0))
) - 0.03 / d['risk_pct'].values - np.where(d['outcome'] == 'stop', 0.05 / d['risk_pct'].values, 0.0)

print(f"  avg_R = {split_pnl.mean():.3f}  WR% = {(split_pnl > 0).mean()*100:.1f}%  n={len(split_pnl):,}")
print(f"  vs baseline: {split_pnl.mean() - baseline_avg:+.3f}R")

print("\n[14c] Outcome breakdown (con slip):")
t = d.groupby('outcome').apply(S).reset_index()
print(T(t))

print("\n[14d] TP1/TP2 ratio per regime e per ora:")
tp1_mask = d['outcome'] == 'tp1'
tp2_mask = d['outcome'] == 'tp2'
for regime_val in ['bull', 'neutral', 'bear']:
    r = d[d['regime'] == regime_val]
    n_r = len(r)
    if n_r < 10:
        continue
    t1 = (r['outcome'] == 'tp1').sum()
    t2 = (r['outcome'] == 'tp2').sum()
    st = (r['outcome'] == 'stop').sum()
    to = (r['outcome'] == 'timeout').sum()
    print(f"  {regime_val:<8}: tp1={t1/n_r*100:.1f}% tp2={t2/n_r*100:.1f}% stop={st/n_r*100:.1f}% timeout={to/n_r*100:.1f}%  (n={n_r:,})")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 15 — OTTIMIZZAZIONE STOP
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 15 — OTTIMIZZAZIONE STOP (MAE proxy)")
print(SEP)

print("[15a] Outcome % per fascia risk_pct (ampiezza stop):")
stop_pct = d.groupby('risk_band', observed=True)['outcome'].value_counts(normalize=True).mul(100).round(1)
stop_tbl = stop_pct.unstack(fill_value=0.0)
for col in ['stop', 'tp1', 'tp2', 'timeout']:
    if col not in stop_tbl.columns:
        stop_tbl[col] = 0.0
print(stop_tbl[['stop', 'tp1', 'tp2', 'timeout']].to_string())

print("\n[15b] Velocità stop (bars_to_exit per outcome=stop):")
stop_df = d[d['outcome'] == 'stop'].copy()
stop_bins2 = [0, 2, 5, 15, 30, 1000]
stop_lbl2 = ['1-2bar', '3-5bar', '6-15bar', '16-30bar', '31+bar']
stop_df['bars_band'] = pd.cut(stop_df['bars_to_exit'], bins=stop_bins2, labels=stop_lbl2)
bv = stop_df['bars_band'].value_counts().sort_index()
n_stop_total = len(stop_df)
for lbl, cnt in bv.items():
    print(f"  {lbl:<12}: {cnt:6,}  ({cnt/n_stop_total*100:.1f}%)")
print(f"  Mediana bars: {stop_df['bars_to_exit'].median():.1f}")

print("\n[15c] Bars to exit per fascia risk_pct (stop outcome only):")
stop_df2 = d[d['outcome'] == 'stop'].copy()
stop_df2['risk_band'] = pd.cut(stop_df2['risk_pct'], bins=risk_bins, labels=risk_labels, right=False)
t = stop_df2.groupby('risk_band', observed=True)['bars_to_exit'].agg(['mean', 'median', 'count']).round(1)
print(t.to_string())

print("\n[15d] Trailing stop a BE simulato (muovi stop a BE dopo +1R):")
# Approssimazione: se un trade colpisce stop dopo >N bars, prob che sia andato +1R prima
# Proxy: stop lenti (>10 bars) più propensi a essere salvati da trailing BE
late_stops = stop_df[stop_df['bars_to_exit'] > 10]
pct_late = len(late_stops) / len(stop_df) * 100
print(f"  Stop dopo >10 bars: {len(late_stops):,} ({pct_late:.1f}% degli stop)")
print(f"  Assumendo ~50% di questi siano 'recuperabili' con trailing BE:")
saved_n = int(len(late_stops) * 0.50)
saved_r_gain = saved_n * 1.0  # da -1R a 0R = guadagna 1R per trade
new_total_r = d['pnl_r_adj'].sum() + saved_r_gain
new_avg = new_total_r / len(d)
print(f"  +{saved_n} trades da -1R a 0R → avg_r da {d['pnl_r_adj'].mean():.3f} a {new_avg:.3f}R")

print("\n[15e] Sensitivity: stop moltiplicatore ATR (proxy: risk_pct come stop width):")
print("  (Analisi qualitativa — stop più stretto = risk_pct basso)")
for band in ['0.50-0.75', '0.75-1.00', '1.00-1.25', '1.25-1.50', '1.50-1.75', '1.75-2.00']:
    subset = d[d['risk_band'] == band]
    if len(subset) < 10:
        continue
    stop_pct_val = (subset['outcome'] == 'stop').mean() * 100
    tp2_pct_val = (subset['outcome'] == 'tp2').mean() * 100
    avg_r_val = subset['pnl_r_adj'].mean()
    n_val = len(subset)
    print(f"  {band}: n={n_val:5,}  stop%={stop_pct_val:.1f}  tp2%={tp2_pct_val:.1f}  avg_r={avg_r_val:.3f}")

# ═══════════════════════════════════════════════════════════════════════════
# RIEPILOGO FINALE
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("RIEPILOGO FINALE — METRICHE CHIAVE 5m")
print(SEP)

n_total = len(d)
wr = d['win'].mean() * 100
avg_r = d['pnl_r_adj'].mean()
med_r = d['pnl_r_adj'].median()

print(f"\n  Dataset: n={n_total:,}  WR={wr:.1f}%  avg_r={avg_r:.3f}R  med_r={med_r:.3f}R")
print(f"  Anni: {sorted(d['year'].unique().tolist())}")
print(f"  Range: {d['ts'].min().date()} → {d['ts'].max().date()}")

# Best/worst hours
hr_s = d.groupby('hour_et').apply(S)
best_h = hr_s['avg_r'].idxmax()
worst_h = hr_s['avg_r'].idxmin()
print(f"\n  Ora migliore:  {best_h:02d}:xx ET  avg_r={hr_s.loc[best_h,'avg_r']:.3f}  n={hr_s.loc[best_h,'n']}")
print(f"  Ora peggiore: {worst_h:02d}:xx ET  avg_r={hr_s.loc[worst_h,'avg_r']:.3f}  n={hr_s.loc[worst_h,'n']}")

# Best/worst patterns
pat_s = d.groupby('pattern_name').apply(S)
best_p = pat_s['avg_r'].idxmax()
worst_p = pat_s['avg_r'].idxmin()
print(f"\n  Pattern migliore: {best_p}  avg_r={pat_s.loc[best_p,'avg_r']:.3f}  n={pat_s.loc[best_p,'n']}")
print(f"  Pattern peggiore: {worst_p}  avg_r={pat_s.loc[worst_p,'avg_r']:.3f}  n={pat_s.loc[worst_p,'n']}")

# OOS 2026
oos = d[d['year'] >= 2026]
print(f"\n  OOS 2026: n={len(oos):,}  WR={oos['win'].mean()*100:.1f}%  avg_r={oos['pnl_r_adj'].mean():.3f}R")

# PowerHours (14-16 ET)
ph = d[d['hour_et'].between(14, 15)]
print(f"  Power Hours 14-16 ET: n={len(ph):,}  WR={ph['win'].mean()*100:.1f}%  avg_r={ph['pnl_r_adj'].mean():.3f}R")

print(f"\n=== ANALISI COMPLETA 5m DONE ===\n")
