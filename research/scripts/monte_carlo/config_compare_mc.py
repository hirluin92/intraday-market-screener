#!/usr/bin/env python3
"""Configs A-G comparison + Monte Carlo 1h+5m combinations."""
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

# ═══ SPY Regime ═══════════════════════════════════════════════════════════
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

spy_df = pd.DataFrame(spy_rows, columns=['date', 'close'])
spy_df['ema50'] = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']   = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] >  2, 'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2, 'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

def get_regime(d):
    for i in range(1, 15):
        if (d - timedelta(days=i)) in spy_dict:
            return spy_dict[d - timedelta(days=i)]
    return 'neutral'

def regime_mask(df):
    return (
        ((df['regime'] == 'bull')    & (df['direction'] == 'bullish')) |
        ((df['regime'] == 'bear')    & (df['direction'] == 'bearish')) |
        (df['regime'] == 'neutral')
    )

def add_slip(df):
    df = df.copy()
    df['pnl_r_adj'] = (
        df['pnl_r']
        - 0.03 / df['risk_pct']
        - np.where(df['outcome'] == 'stop', 0.05 / df['risk_pct'], 0.0)
    )
    df['win'] = df['pnl_r_adj'] > 0
    return df

# ═══ Load 5m ══════════════════════════════════════════════════════════════
print("Processing 5m...", flush=True)
df5 = pd.read_csv('/app/data/val_5m_expanded.csv')
df5['ts'] = pd.to_datetime(df5['pattern_timestamp'], utc=True)
df5['_d'] = df5['ts'].apply(lambda x: x.date())
df5['regime'] = df5['_d'].apply(get_regime)
df5['year']   = df5['ts'].dt.year

if TZ_ET:
    df5['hour_et'] = df5['ts'].dt.tz_convert(TZ_ET).dt.hour
else:
    df5['hour_et'] = (df5['ts'].dt.hour - 4) % 24

BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})
BLOCKED_NEG  = frozenset({'RIVN','RXRX','VKTX','SMR','LUNR'})

base5 = add_slip(df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) &
    (df5['risk_pct'] <= 2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE)) &
    (df5['pattern_name'] != 'engulfing_bullish') &
    regime_mask(df5)
].copy())

# ═══ Load 1h ══════════════════════════════════════════════════════════════
print("Processing 1h...", flush=True)
df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts'] = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d'] = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1['year']   = df1['ts'].dt.year

base1 = add_slip(df1[
    (df1['risk_pct'] >= 0.30) &
    regime_mask(df1)
].copy())

print(f"  5m base (no engulfing): n={len(base5):,}", flush=True)
print(f"  1h base: n={len(base1):,}", flush=True)

SEP = '═' * 76

def S(c):
    if len(c) == 0:
        return 0, 0.0, 0.0, 0.0
    return (int(len(c)),
            round(c['pnl_r'].mean(), 3),
            round(c['pnl_r_adj'].mean(), 3),
            round(c['win'].mean() * 100, 1))

def lam(c, from_year=2024):
    sub = c[c['year'] >= from_year]
    if len(sub) < 2:
        return 0.0
    span = (sub['ts'].max() - sub['ts'].min()).days / 30.44
    return len(sub) / max(span, 1.0)

# ═══ Build configs ══════════════════════════════════════════════════════
PH = base5[base5['hour_et'].between(14, 15)]

cfg = {}
cfg['A'] = PH.copy()
cfg['B'] = PH[PH['pattern_strength'] <= 0.75].copy()
cfg['C'] = cfg['B'][cfg['B']['screener_score'] <= 10].copy()
cfg['D'] = cfg['C'][~cfg['C']['symbol'].isin(BLOCKED_NEG)].copy()
cfg['E'] = cfg['D'][cfg['D']['hour_et'] == 15].copy()
cfg['F'] = PH[PH['pattern_strength'] <= 0.70].copy()
cfg['G'] = base5[base5['hour_et'] == 15].copy()

NAMES = {
    'A': 'A: PH 14-16, 4pat',
    'B': 'B: +str≤0.75',
    'C': 'C: +score≤10',
    'D': 'D: +no_neg_sym',
    'E': 'E: solo 15ET',
    'F': 'F: A+str≤0.70',
    'G': 'G: base, solo 15ET',
}

# ═══ Table 1: stats ═════════════════════════════════════════════════════
print(f"\n{SEP}")
print("CONFIGURAZIONI A-G  (val_5m_expanded, regime+risk+no_blocked+no_engulfing)")
print(SEP)
print(f"\n  {'Config':<22} {'n':>6}  {'avg_r':>7}  {'avg+slip':>9}  {'WR%':>6}")
print('  ' + '─' * 56)
for k, nm in NAMES.items():
    n, ar, aadj, wr = S(cfg[k])
    print(f"  {nm:<22} {n:>6,}  {ar:>7.3f}  {aadj:>9.3f}  {wr:>6.1f}%")

# ═══ Table 2: annual stability ══════════════════════════════════════════
print(f"\n{SEP}")
print("STABILITÀ ANNUALE — avg_r+slip")
print(SEP)
print(f"\n  {'Config':<22}  {'n_24':>5}  {'2024':>7}  {'n_25':>5}  {'2025':>7}  {'n_26':>5}  {'2026_OOS':>9}  {'Stabile':>8}")
print('  ' + '─' * 78)
for k, nm in NAMES.items():
    c = cfg[k]
    row = []
    vals = []
    for yr in [2024, 2025, 2026]:
        sub = c[c['year'] == yr]
        nyr = len(sub)
        avg = sub['pnl_r_adj'].mean() if nyr >= 5 else float('nan')
        row += [nyr, avg]
        vals.append(avg)
    ok3 = sum(v > 0 for v in vals if not pd.isna(v))
    stab = 'SI' if ok3 == 3 else ('PARZ' if ok3 == 2 else 'NO')
    def fmt(v): return f"{v:>+7.3f}" if not pd.isna(v) else "    N/A"
    print(f"  {nm:<22}  {row[0]:>5,}  {fmt(row[1])}  {row[2]:>5,}  {fmt(row[3])}  {row[4]:>5,}  {fmt(row[5]):>9}  {stab:>8}")

# ═══ Table 3: trade/year × avg_r ════════════════════════════════════════
print(f"\n{SEP}")
print("RENDIMENTO ANNUALE ATTESO  (λ 2024+, €1 000/trade)")
print(SEP)
print(f"\n  {'Config':<22}  {'λ/m':>5}  {'T/anno':>7}  {'avg+slip':>9}  {'R/anno':>7}  {'€/anno':>10}")
print('  ' + '─' * 68)
rank_rows = []
for k, nm in NAMES.items():
    c = cfg[k]
    l = lam(c)
    n, _, aadj, _ = S(c)
    tpy = l * 12
    ra  = tpy * aadj
    eur = ra * RISK_EUR
    rank_rows.append((k, nm, l, tpy, aadj, ra, eur))
    print(f"  {nm:<22}  {l:>5.1f}  {tpy:>7.0f}  {aadj:>9.3f}  {ra:>7.1f}  {eur:>10,.0f}")

# ═══ Monte Carlo ════════════════════════════════════════════════════════
print(f"\n{SEP}")
print(f"MONTE CARLO  ({N_SIM} sim × {N_MONTHS} mesi, €{RISK_EUR:,}/trade fisso)")
print(SEP)

lam_1h = lam(base1)
r_1h   = base1['pnl_r_adj'].values

print(f"\n  1h: n={len(base1):,}  λ/m={lam_1h:.1f}  avg_r={r_1h.mean():.3f}  WR={base1['win'].mean()*100:.1f}%")

rng = np.random.default_rng(42)

def run_mc(r1h, l1h, r5m, l5m):
    """Returns (median, worst5pct, probP) in €."""
    r1 = np.asarray(r1h, dtype=float)
    r5 = np.asarray(r5m, dtype=float)
    results = np.empty(N_SIM)
    for s in range(N_SIM):
        cum = 0.0
        for m in range(N_MONTHS):
            n1 = int(rng.poisson(l1h))
            if n1 > 0:
                cum += rng.choice(r1, size=n1, replace=True).sum()
            if l5m > 0 and len(r5) > 0:
                n5 = int(rng.poisson(l5m))
                if n5 > 0:
                    cum += rng.choice(r5, size=n5, replace=True).sum()
        results[s] = cum * RISK_EUR
    return (round(np.median(results)),
            round(np.mean(results)),
            round(np.percentile(results, 5)),
            round((results > 0).mean() * 100, 1))

MC_SCENARIOS = [
    ('Solo 1h',   None),
    ('1h + A',    'A'),
    ('1h + C',    'C'),
    ('1h + D',    'D'),
    ('1h + E',    'E'),
    ('1h + G',    'G'),
]

print(f"\n  {'Scenario':<18}  {'T/anno':>7}  {'avg_r':>7}  {'Med_12m':>9}  {'Worst5%':>9}  {'ProbP':>7}")
print('  ' + '─' * 68)

mc_results = []
for label, ck in MC_SCENARIOS:
    if ck is None:
        r5m, l5m = np.array([]), 0.0
        tpy  = lam_1h * 12
        wavg = r_1h.mean()
    else:
        c    = cfg[ck]
        r5m  = c['pnl_r_adj'].values
        l5m  = lam(c)
        tpy  = (lam_1h + l5m) * 12
        nt   = len(r_1h) + len(r5m)
        wavg = (r_1h.mean() * len(r_1h) + r5m.mean() * len(r5m)) / nt if nt > 0 else r_1h.mean()

    med, mean, w5, pp = run_mc(r_1h, lam_1h, r5m, l5m)
    mc_results.append((label, tpy, wavg, med, w5, pp))
    print(f"  {label:<18}  {tpy:>7.0f}  {wavg:>7.3f}  {med/1e3:>8.1f}k  {w5/1e3:>8.1f}k  {pp:>6.1f}%")

# ═══ Best config ranking ════════════════════════════════════════════════
print(f"\n{SEP}")
print("RANKING 5m — trade/anno × avg_r  (profitto totale atteso €/anno)")
print(SEP)
ranked = sorted(rank_rows, key=lambda x: -x[6])
print(f"\n  {'Rk':<3}  {'Config':<22}  {'T/anno':>7}  {'avg+slip':>9}  {'€/anno':>10}")
print('  ' + '─' * 56)
for i, (k, nm, l, tpy, aadj, ra, eur) in enumerate(ranked, 1):
    star = ' ★' if i == 1 else ''
    print(f"  {i:<3}  {nm:<22}  {tpy:>7.0f}  {aadj:>9.3f}  {eur:>10,.0f}{star}")

# Best MC scenario by median
best_mc = max(mc_results, key=lambda x: x[3])
print(f"\n  Best MC scenario: {best_mc[0]} — Med_12m = €{best_mc[3]/1000:.0f}k  ProbP={best_mc[5]:.1f}%")

print(f"\n=== DONE ===\n")
