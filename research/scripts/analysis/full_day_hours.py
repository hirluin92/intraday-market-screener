#!/usr/bin/env python3
"""Full-day hour analysis without engulfing — are 11-14 ET positive with good patterns?"""
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

RISK_EUR = 1000
N_SIM    = 5000
N_MONTHS = 12

# ── Regime ─────────────────────────────────────────────────────────────────
print("Loading SPY regime...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("""
    SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
    FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp
""")
spy_rows = cur.fetchall()
conn.close()

spy_df = pd.DataFrame(spy_rows, columns=['date','close'])
spy_df['ema50']  = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']    = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] >  2,'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2,'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

def get_regime(d):
    for i in range(1,15):
        v = spy_dict.get(d - timedelta(days=i))
        if v is not None: return v
    return 'neutral'

def regime_mask(df):
    return (
        ((df['regime']=='bull') & (df['direction']=='bullish')) |
        ((df['regime']=='bear') & (df['direction']=='bearish')) |
        (df['regime']=='neutral')
    )

def add_slip(df):
    df = df.copy()
    df['pnl_r_adj'] = (df['pnl_r']
        - 0.03 / df['risk_pct']
        - np.where(df['outcome']=='stop', 0.05/df['risk_pct'], 0.0))
    df['win'] = df['pnl_r_adj'] > 0
    return df

BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})

# ── Load — NO hour filter, NO engulfing ─────────────────────────────────────
print("Loading 5m (no hour filter, no engulfing)...", flush=True)
df5 = pd.read_csv('/app/data/val_5m_expanded.csv')
df5['ts']     = pd.to_datetime(df5['pattern_timestamp'], utc=True)
df5['_d']     = df5['ts'].apply(lambda x: x.date())
df5['regime'] = df5['_d'].apply(get_regime)
df5['year']   = df5['ts'].dt.year
if TZ_ET:
    df5['ts_et']   = df5['ts'].dt.tz_convert(TZ_ET)
    df5['hour_et'] = df5['ts_et'].dt.hour
    df5['min_et']  = df5['ts_et'].dt.minute
else:
    df5['ts_et']   = df5['ts']
    df5['hour_et'] = (df5['ts'].dt.hour - 4) % 24
    df5['min_et']  = df5['ts'].dt.minute

# Full structural filter — NO hour filter — NO engulfing
base_all = add_slip(df5[
    (df5['entry_filled']==True) &
    (df5['risk_pct']>=0.50) & (df5['risk_pct']<=2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE)) &
    (df5['pattern_name']!='engulfing_bullish') &
    regime_mask(df5)
].copy())

print(f"Full dataset (no engulfing, no hour filter): n={len(base_all):,}", flush=True)

# ── 30-min slot label ────────────────────────────────────────────────────────
def slot_label(row):
    h = int(row['hour_et'])
    m = int(row['min_et'])
    half = 0 if m < 30 else 30
    return f"{h:02d}:{half:02d}"

base_all['slot'] = base_all.apply(slot_label, axis=1)

# Ordered slots covering 9:30 to 15:59
ALL_SLOTS = [
    '09:30','10:00','10:30',
    '11:00','11:30',
    '12:00','12:30',
    '13:00','13:30',
    '14:00','14:30',
    '15:00','15:30',
]

SEP = '═'*76

# ── TABLE 1 — per-slot stats full dataset ───────────────────────────────────
print(f"\n{SEP}")
print("ANALISI ORE COMPLETA — 6 pattern (no engulfing), tutti i fix strutturali")
print("(NO hour filter — mostra tutto il giorno)")
print(SEP)
print(f"\n  {'Slot ET':<14}  {'n':>5}  {'avg_r':>8}  {'avg+slip':>9}  {'WR%':>6}  {'segno':>6}")
print('  '+'─'*58)

slot_positive = []   # collect slots with avg+slip > 0
for sl in ALL_SLOTS:
    sub = base_all[base_all['slot']==sl]
    n   = len(sub)
    if n == 0:
        print(f"  {sl}              {'0':>5}   {'—':>8}   {'—':>9}  {'—':>6}")
        continue
    ar   = sub['pnl_r'].mean()
    aadj = sub['pnl_r_adj'].mean()
    wr   = sub['win'].mean()*100
    sign = '✓+' if aadj > 0 else '✗-'
    print(f"  {sl:<14}  {n:>5,}  {ar:>+8.3f}  {aadj:>+9.3f}  {wr:>5.1f}%  {sign:>6}")
    if aadj > 0:
        slot_positive.append(sl)

print(f"\n  Slot positivi (avg+slip > 0): {slot_positive}")

# Also show full-day aggregates for comparison
ph_mask = base_all['hour_et'].between(14,15)
all_mask = pd.Series(True, index=base_all.index)
lh_mask  = base_all['hour_et']==15
h1530_mask = (base_all['hour_et']==15) & (base_all['min_et']>=30)

print(f"\n  {'Aggregato':<20}  {'n':>5}  {'avg_r':>8}  {'avg+slip':>9}  {'WR%':>6}")
print('  '+'─'*52)
for lbl, msk in [
    ('TUTTO il giorno',    all_mask),
    ('PH 14-16 ET',        ph_mask),
    ('Last Hour 15-16 ET', lh_mask),
    ('15:30-15:59',        h1530_mask),
]:
    sub = base_all[msk]
    ar   = sub['pnl_r'].mean()
    aadj = sub['pnl_r_adj'].mean()
    wr   = sub['win'].mean()*100
    print(f"  {lbl:<20}  {len(sub):>5,}  {ar:>+8.3f}  {aadj:>+9.3f}  {wr:>5.1f}%")

# ── TABLE 2 — year-by-year per slot (OOS check) ─────────────────────────────
print(f"\n{SEP}")
print("OOS PER SLOT — stabilità annuale (solo slot con avg+slip > 0)")
print(SEP)
print(f"\n  {'Slot ET':<14}  {'2024':>9}(n)   {'2025':>9}(n)   {'2026_OOS':>9}(n)  Stabile?")
print('  '+'─'*72)

oos_positive = []  # slots stable across all years
for sl in ALL_SLOTS:
    sub  = base_all[base_all['slot']==sl]
    n    = len(sub)
    vals = []
    row_parts = []
    for yr in [2024, 2025, 2026]:
        s = sub[sub['year']==yr]
        nyr = len(s)
        v   = s['pnl_r_adj'].mean() if nyr >= 3 else float('nan')
        vals.append(v)
        vstr = f"{'  N/A':>9}" if np.isnan(v) else f"{v:>+9.3f}"
        row_parts.append(f"{vstr}({nyr:>3})")
    ok   = sum(v > 0 for v in vals if not np.isnan(v))
    nok  = sum(1 for v in vals if not np.isnan(v))
    stab = 'SI' if (ok==nok and nok>=2) else ('PARZ' if ok>=2 else 'NO')
    if stab == 'SI':
        oos_positive.append(sl)
    print(f"  {sl:<14}  {'  '.join(row_parts)}  {stab}")

print(f"\n  Slot OOS-stabili (SI in tutti gli anni): {oos_positive}")

# ── TABLE 3 — pattern breakdown per fascia oraria ────────────────────────────
print(f"\n{SEP}")
print("PATTERN × FASCIA ORARIA  (avg+slip)")
print("Fascia A=09:30-11:00, B=11:00-14:00, C=14:00-15:00, D=15:00-16:00")
print(SEP)

def fascia(row):
    h = row['hour_et']
    m = row['min_et']
    if h == 9 and m >= 30: return 'A 09:30-11'
    if h == 10: return 'A 09:30-11'
    if h in [11,12,13]: return 'B 11-14'
    if h == 14: return 'C 14-15'
    if h == 15: return 'D 15-16'
    return 'other'

base_all['fascia'] = base_all.apply(fascia, axis=1)

patterns = sorted(base_all['pattern_name'].unique())
fascmap  = ['A 09:30-11','B 11-14','C 14-15','D 15-16']

print(f"\n  {'Pattern':<30}  {'A 09:30-11':>12}  {'B 11-14':>10}  {'C 14-15':>10}  {'D 15-16':>10}")
print('  '+'─'*76)
for pat in patterns:
    parts = []
    for fs in fascmap:
        sub = base_all[(base_all['pattern_name']==pat) & (base_all['fascia']==fs)]
        if len(sub) < 5:
            parts.append(f"{'  —':>12}" if fs==fascmap[0] else f"{'—':>10}")
        else:
            v = sub['pnl_r_adj'].mean()
            s = f"{v:>+9.3f}(n={len(sub):>3})"
            parts.append(f"{s:>12}" if fs==fascmap[0] else f"{v:>+10.3f}")
    print(f"  {pat:<30}  {'  '.join(parts)}")

# ── Totale per fascia ─────────────────────────────────────────────────────────
print()
for fs in fascmap:
    sub = base_all[base_all['fascia']==fs]
    if len(sub)==0: continue
    print(f"  TOTALE {fs:<12}: n={len(sub):>5,}  avg+slip={sub['pnl_r_adj'].mean():>+7.3f}  WR={sub['win'].mean()*100:.1f}%")

# ── Monte Carlo ──────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print(f"MONTE CARLO  ({N_SIM} sim × {N_MONTHS} mesi, €{RISK_EUR:,}/trade)")
print(SEP)

def lam(c, from_year=2024):
    sub = c[c['year']>=from_year]
    if len(sub)<2: return 0.0
    span = (sub['ts'].max()-sub['ts'].min()).days/30.44
    return len(sub)/max(span,1.0)

# Load 1h
df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts']     = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d']     = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1['year']   = df1['ts'].dt.year
base1 = add_slip(df1[(df1['risk_pct']>=0.30) & regime_mask(df1)].copy())
lam_1h = lam(base1)
r_1h   = base1['pnl_r_adj'].values

# Build scenario datasets
alpha_data   = base_all[base_all['hour_et']==15]                       # ALPHA: 15:xx
beta_data    = base_all[(base_all['hour_et']==15)&(base_all['min_et']>=30)]  # BETA: 15:30+

# "all positive slots" = OOS-stable slots
if oos_positive:
    allpos_data = base_all[base_all['slot'].isin(oos_positive)]
else:
    allpos_data = base_all[base_all['hour_et'].between(14,15)]

# "all positive avg+slip" = all slots > 0 (regardless of OOS stability)
if slot_positive:
    allpos_avg_data = base_all[base_all['slot'].isin(slot_positive)]
else:
    allpos_avg_data = base_all[all_mask]

# Full day (all slots, all hours — no hour filter)
full_data = base_all.copy()

RNG = np.random.default_rng(42)

def run_mc(r1h, l1h, r5m, l5m):
    r1 = np.asarray(r1h, dtype=float)
    r5 = np.asarray(r5m, dtype=float)
    results = np.empty(N_SIM)
    for s in range(N_SIM):
        cum = 0.0
        for m in range(N_MONTHS):
            n1 = int(RNG.poisson(l1h))
            if n1>0: cum += RNG.choice(r1,size=n1,replace=True).sum()
            if l5m>0 and len(r5)>0:
                n5 = int(RNG.poisson(l5m))
                if n5>0: cum += RNG.choice(r5,size=n5,replace=True).sum()
        results[s] = cum * RISK_EUR
    return (int(np.median(results)),
            int(np.percentile(results,5)),
            round((results>0).mean()*100, 1))

scenarios_5m = [
    ('Solo 15:00-16:00 (ALPHA)',    alpha_data),
    ('Solo 15:30-15:59 (BETA)',     beta_data),
    ('Slot OOS-stabili',            allpos_data),
    ('Slot avg+slip>0',             allpos_avg_data),
    ('Tutto il giorno (no engulf)', full_data),
]

print(f"\n  {'Scenario 5m':<32}  {'n':>5}  {'avg+sl':>7}  {'WR':>6}  {'λ/m':>5}  {'€/anno':>10}")
print('  '+'─'*74)
for lbl, cfg in scenarios_5m:
    if len(cfg)==0: continue
    l  = lam(cfg)
    av = cfg['pnl_r_adj'].mean()
    wr = cfg['win'].mean()*100
    print(f"  {lbl:<32}  {len(cfg):>5,}  {av:>+7.3f}  {wr:>5.1f}%  {l:>5.1f}  {l*12*av*RISK_EUR:>10,.0f}")

print(f"\n  1h: n={len(base1):,}  λ/m={lam_1h:.1f}  avg_r={r_1h.mean():.3f}  WR={base1['win'].mean()*100:.1f}%")

print(f"\n  {'Scenario MC':<38}  {'T/anno':>7}  {'avg_r':>7}  {'Mediana':>9}  {'Worst5%':>9}  {'ProbP':>7}")
print('  '+'─'*80)

mc_rows = [('Solo 1h', np.array([]), 0.0)]
for lbl, cfg in scenarios_5m:
    if len(cfg)==0: continue
    mc_rows.append((f'1h + {lbl[:20]}', cfg['pnl_r_adj'].values, lam(cfg)))

for label, r5m, l5m in mc_rows:
    print(f"  {label}...", end='', flush=True)
    if l5m==0 or len(r5m)==0:
        tpy  = lam_1h*12
        wavg = r_1h.mean()
    else:
        tpy  = (lam_1h+l5m)*12
        nt   = len(r_1h)+len(r5m)
        wavg = (r_1h.mean()*len(r_1h)+r5m.mean()*len(r5m))/nt
    med, w5, pp = run_mc(r_1h, lam_1h, r5m, l5m)
    print(f" ok")
    print(f"  {label:<38}  {tpy:>7.0f}  {wavg:>7.3f}  {med/1e3:>8.0f}k  {w5/1e3:>8.0f}k  {pp:>6.1f}%")

print("\n=== DONE ===")
