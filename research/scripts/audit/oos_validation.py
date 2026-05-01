#!/usr/bin/env python3
"""OOS stability check: slot, SPY movement, DoW, pre-PH trend, configs A-E."""
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

# ── Regime + SPY 5m ────────────────────────────────────────────────────────
print("Loading SPY 1d + 5m...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("""
    SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
    FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp
""")
spy_rows = cur.fetchall()
cur.execute("""
    SELECT timestamp, close::float
    FROM candles WHERE symbol='SPY' AND timeframe='5m' ORDER BY timestamp
""")
spy5_rows = cur.fetchall()
conn.close()

spy_df = pd.DataFrame(spy_rows, columns=['date','close'])
spy_df['ema50']  = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']    = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] >  2,'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2,'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

def get_regime(d):
    for i in range(1, 15):
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
        - np.where(df['outcome']=='stop', 0.05 / df['risk_pct'], 0.0))
    df['win'] = df['pnl_r_adj'] > 0
    return df

BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})

# ── SPY 5m index ────────────────────────────────────────────────────────────
print("Building SPY 5m index...", flush=True)
spy5 = pd.DataFrame(spy5_rows, columns=['ts','close'])
spy5['ts'] = pd.to_datetime(spy5['ts'], utc=True)
if TZ_ET:
    spy5['ts_et'] = spy5['ts'].dt.tz_convert(TZ_ET)
else:
    spy5['ts_et'] = spy5['ts']
spy5['date_et'] = spy5['ts_et'].apply(lambda x: x.date())
spy5['hour_et'] = spy5['ts_et'].dt.hour

spy5_ts_close = dict(zip(spy5['ts'], spy5['close']))   # exact-ts lookup

# first close of 14:xx per date → PH reference price
spy_ph14 = {}
# last close before 14:00 (9-13h) and first close of morning
spy_am_open  = {}
spy_am_close = {}   # last bar ≤13:59
for date, grp in spy5.groupby('date_et'):
    ph14 = grp[grp['hour_et']==14]
    if len(ph14) > 0:
        spy_ph14[date] = ph14.iloc[0]['close']
    am = grp[grp['hour_et'].between(9,13)]
    if len(am) > 0:
        spy_am_open[date]  = am.iloc[0]['close']
        spy_am_close[date] = am.iloc[-1]['close']

# ── Load + filter 5m ────────────────────────────────────────────────────────
print("Loading 5m dataset...", flush=True)
df5 = pd.read_csv('/app/data/val_5m_expanded.csv')
df5['ts']     = pd.to_datetime(df5['pattern_timestamp'], utc=True)
df5['_d']     = df5['ts'].apply(lambda x: x.date())
df5['regime'] = df5['_d'].apply(get_regime)
df5['year']   = df5['ts'].dt.year
if TZ_ET:
    df5['ts_et']   = df5['ts'].dt.tz_convert(TZ_ET)
    df5['hour_et'] = df5['ts_et'].dt.hour
    df5['min_et']  = df5['ts_et'].dt.minute
    df5['dow']     = df5['ts_et'].dt.dayofweek
else:
    df5['ts_et']   = df5['ts']
    df5['hour_et'] = (df5['ts'].dt.hour - 4) % 24
    df5['min_et']  = df5['ts'].dt.minute
    df5['dow']     = df5['ts'].dt.dayofweek

base5 = add_slip(df5[
    (df5['entry_filled']==True) &
    (df5['risk_pct']>=0.50) & (df5['risk_pct']<=2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE)) &
    (df5['pattern_name']!='engulfing_bullish') &
    regime_mask(df5)
].copy())

base = base5[base5['hour_et'].between(14,15)].copy()
print(f"Base PH: n={len(base):,}", flush=True)

# ── SPY PH return (14:00 ET → trade time) ───────────────────────────────────
print("Computing SPY features...", flush=True)

def spy_ph_ret(row):
    date  = row['ts_et'].date()
    ph14  = spy_ph14.get(date)
    if ph14 is None or ph14 == 0: return 0.0
    spy_now = spy5_ts_close.get(row['ts'])
    if spy_now is None: return 0.0
    return (spy_now - ph14) / ph14 * 100

def preph_trend(row):
    date = row['ts_et'].date()
    mo   = spy_am_open.get(date)
    mc   = spy_am_close.get(date)
    if mo is None or mc is None or mo == 0: return 0.0
    return (mc - mo) / mo * 100

base['spy_ph_ret']   = base.apply(spy_ph_ret, axis=1)
base['preph_trend']  = base.apply(preph_trend, axis=1)

# ── Derived flags ────────────────────────────────────────────────────────────
base['is_1530']     = (base['hour_et']==15) & (base['min_et']>=30)
base['is_1500']     = (base['hour_et']==15) & (base['min_et']< 30)
base['spy_moving']  = base['spy_ph_ret'].abs() > 0.3
base['preph_strong_down'] = base['preph_trend'] < -1.0

# ── Helpers ──────────────────────────────────────────────────────────────────
SEP = '═'*76

def yr_row(sub):
    rows = []
    for yr in [2024, 2025, 2026]:
        s = sub[sub['year']==yr]
        n = len(s)
        v = s['pnl_r_adj'].mean() if n >= 3 else float('nan')
        rows.append((n, v))
    vals = [v for (_,v) in rows if not np.isnan(v)]
    ok   = sum(v > 0 for v in vals)
    stab = 'SI' if (ok==len(vals) and len(vals)>=2) else ('PARZ' if ok>=2 else 'NO')
    return rows, stab

def print_test(label, sub):
    n   = len(sub)
    avg = sub['pnl_r_adj'].mean() if n >= 3 else float('nan')
    wr  = sub['win'].mean()*100    if n >= 3 else float('nan')
    rows, stab = yr_row(sub)
    r24, r25, r26 = rows
    def fv(nv, v): return f"{'  N/A':>7}" if np.isnan(v) else f"{v:>+7.3f}"
    print(f"  {label:<34}  n={n:>4}  avg={avg:>+6.3f}  WR={wr:>5.1f}%")
    print(f"    2024: {fv(*r24)} (n={r24[0]:>3})  "
          f"2025: {fv(*r25)} (n={r25[0]:>3})  "
          f"2026_OOS: {fv(*r26)} (n={r26[0]:>3})  [{stab}]")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("TEST 1 — SLOT ORARIO: 14:xx vs 15:00-15:29 vs 15:30-15:59")
print(SEP)
for lbl, msk in [
    ('14:00-14:59', base['hour_et']==14),
    ('15:00-15:29', base['is_1500']),
    ('15:30-15:59', base['is_1530']),
]:
    print()
    print_test(lbl, base[msk])

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("TEST 2 — SPY MOVEMENT FILTER  (|ret 14:00→trade| > 0.3%)")
print(SEP)
for lbl, msk in [
    ('SPY moving  |ret|>0.3%', base['spy_moving']),
    ('SPY flat    |ret|<0.3%', ~base['spy_moving']),
]:
    print()
    print_test(lbl, base[msk])

# ── Also test on 15:xx only (configs operate there)
print()
print("  — su 15:xx soltanto —")
b15 = base[base['hour_et']==15]
for lbl, msk in [
    ('15:xx + SPY moving', b15['spy_moving']),
    ('15:xx + SPY flat',   ~b15['spy_moving']),
]:
    print()
    print_test(lbl, b15[msk])

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("TEST 3 — GIORNO DELLA SETTIMANA  (su 15:xx)")
print(SEP)
for lbl, msk in [
    ('Lunedì',    b15['dow']==0),
    ('Mar-Gio',   b15['dow'].between(1,3)),
    ('Venerdì',   b15['dow']==4),
]:
    print()
    print_test(lbl, b15[msk])

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("TEST 4 — BEARISH × PRE-PH TREND FORTE  (su PH 14-16)")
print(SEP)
for lbl, msk in [
    ('bearish × pre-PH <-1% (forte ribasso)',
        (base['direction']=='bearish') & base['preph_strong_down']),
    ('bearish × pre-PH -1→0%',
        (base['direction']=='bearish') & base['preph_trend'].between(-1.0, 0.0)),
    ('bearish × pre-PH qualsiasi',
        base['direction']=='bearish'),
    ('bullish × pre-PH <-1%',
        (base['direction']=='bullish') & base['preph_strong_down']),
]:
    print()
    print_test(lbl, base[msk])

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("TEST 5 — CONFIGS ALPHA-EPSILON: stats + stabilità + €/anno")
print(SEP)

def lam(c, from_year=2024):
    sub = c[c['year']>=from_year]
    if len(sub) < 2: return 0.0
    span = (sub['ts'].max() - sub['ts'].min()).days / 30.44
    return len(sub) / max(span, 1.0)

cfgs = {
    'ALPHA':   base[base['hour_et']==15].copy(),
    'BETA':    base[base['is_1530']].copy(),
    'GAMMA':   base[(base['hour_et']==15) & (base['dow']!=0)].copy(),
    'DELTA':   base[(base['hour_et']==15) & base['spy_moving']].copy(),
    'EPSILON': base[base['is_1530'] & base['spy_moving']].copy(),
}

print(f"\n  {'Config':<10}  {'n':>5}  {'avg+sl':>8}  {'WR':>6}  {'2024':>8}(n)  {'2025':>8}(n)  {'2026':>8}(n)  {'λ/m':>5}  {'€/anno':>10}  Stab")
print('  '+'─'*105)

cfg_data = {}
for name, cfg in cfgs.items():
    if len(cfg) == 0:
        print(f"  {name}: n=0"); continue
    avg  = cfg['pnl_r_adj'].mean()
    wr   = cfg['win'].mean()*100
    l    = lam(cfg)
    eur  = l * 12 * avg * RISK_EUR
    rows, stab = yr_row(cfg)
    r24, r25, r26 = rows
    def fv(nv, v): return '   N/A' if np.isnan(v) else f"{v:>+6.3f}"
    print(f"  {name:<10}  {len(cfg):>5,}  {avg:>+8.3f}  {wr:>5.1f}%  "
          f"{fv(*r24)}({r24[0]:>3})  "
          f"{fv(*r25)}({r25[0]:>3})  "
          f"{fv(*r26)}({r26[0]:>3})  "
          f"{l:>5.1f}  {eur:>10,.0f}  {stab}")
    cfg_data[name] = (cfg['pnl_r_adj'].values, l)

# ── 1h baseline ──────────────────────────────────────────────────────────────
df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts']     = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d']     = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1['year']   = df1['ts'].dt.year
base1 = add_slip(df1[(df1['risk_pct']>=0.30) & regime_mask(df1)].copy())
lam_1h = lam(base1)
r_1h   = base1['pnl_r_adj'].values
print(f"\n  1h: n={len(base1):,}  λ/m={lam_1h:.1f}  avg_r={r_1h.mean():.3f}  WR={base1['win'].mean()*100:.1f}%")

# ── Monte Carlo ──────────────────────────────────────────────────────────────
RNG = np.random.default_rng(42)

def run_mc(r1h, l1h, r5m, l5m):
    r1 = np.asarray(r1h, dtype=float)
    r5 = np.asarray(r5m, dtype=float)
    results = np.empty(N_SIM)
    for s in range(N_SIM):
        cum = 0.0
        for m in range(N_MONTHS):
            n1 = int(RNG.poisson(l1h))
            if n1 > 0: cum += RNG.choice(r1, size=n1, replace=True).sum()
            if l5m > 0 and len(r5) > 0:
                n5 = int(RNG.poisson(l5m))
                if n5 > 0: cum += RNG.choice(r5, size=n5, replace=True).sum()
        results[s] = cum * RISK_EUR
    return (int(np.median(results)),
            int(np.percentile(results, 5)),
            round((results > 0).mean() * 100, 1))

print(f"\n{SEP}")
print(f"MONTE CARLO  ({N_SIM} sim × {N_MONTHS} mesi, €{RISK_EUR:,}/trade fisso)")
print(SEP)
print(f"\n  {'Scenario':<22}  {'T/anno':>7}  {'avg_r':>7}  {'Mediana':>9}  {'Worst5%':>9}  {'ProbP':>7}")
print('  '+'─'*70)

mc_scenarios = [('Solo 1h', np.array([]), 0.0)]
for name, (r5m, l5m) in cfg_data.items():
    mc_scenarios.append((f'1h+{name}', r5m, l5m))

for label, r5m, l5m in mc_scenarios:
    print(f"  {label}...", end='', flush=True)
    if l5m == 0 or len(r5m) == 0:
        tpy  = lam_1h * 12
        wavg = r_1h.mean()
    else:
        tpy  = (lam_1h + l5m) * 12
        nt   = len(r_1h) + len(r5m)
        wavg = (r_1h.mean()*len(r_1h) + r5m.mean()*len(r5m)) / nt
    med, w5, pp = run_mc(r_1h, lam_1h, r5m, l5m)
    print(f" ok")
    print(f"  {label:<22}  {tpy:>7.0f}  {wavg:>7.3f}  {med/1e3:>8.0f}k  {w5/1e3:>8.0f}k  {pp:>6.1f}%")

print("\n=== DONE ===")
