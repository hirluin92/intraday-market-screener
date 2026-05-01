#!/usr/bin/env python3
"""CONFRONTO COMPLETO A-M + Monte Carlo 1h+5m con drawdown."""
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
RNG      = np.random.default_rng(42)

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
spy_df['ema50']  = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']    = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] >  2, 'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2, 'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

def get_regime(d):
    for i in range(1, 15):
        v = spy_dict.get(d - timedelta(days=i))
        if v is not None:
            return v
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

# ═══ 5m base ══════════════════════════════════════════════════════════════
print("Processing 5m...", flush=True)
df5 = pd.read_csv('/app/data/val_5m_expanded.csv')
df5['ts']     = pd.to_datetime(df5['pattern_timestamp'], utc=True)
df5['_d']     = df5['ts'].apply(lambda x: x.date())
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

# ═══ 1h base ══════════════════════════════════════════════════════════════
print("Processing 1h...", flush=True)
df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts']     = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d']     = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1['year']   = df1['ts'].dt.year

base1 = add_slip(df1[
    (df1['risk_pct'] >= 0.30) &
    regime_mask(df1)
].copy())

print(f"  5m n={len(base5):,}  1h n={len(base1):,}", flush=True)

# ═══ Helper: lambda/month using 2024+ data ═══════════════════════════════
def lam(c, from_year=2024):
    sub = c[c['year'] >= from_year]
    if len(sub) < 3:
        return 0.0
    span = (sub['ts'].max() - sub['ts'].min()).days / 30.44
    return len(sub) / max(span, 1.0)

def S(c):
    if len(c) == 0:
        return 0, 0.0, 0.0, 0.0
    return (len(c),
            round(c['pnl_r'].mean(), 3),
            round(c['pnl_r_adj'].mean(), 3),
            round(c['win'].mean() * 100, 1))

# ═══ Build all configs ════════════════════════════════════════════════════
PH   = base5[base5['hour_et'].between(14, 15)]
H15  = base5[base5['hour_et'] == 15]

cfg = {}
cfg['A'] = PH.copy()
cfg['B'] = PH[PH['pattern_strength'] <= 0.75].copy()
cfg['C'] = cfg['B'][cfg['B']['screener_score'] <= 10].copy()
cfg['D'] = cfg['C'][~cfg['C']['symbol'].isin(BLOCKED_NEG)].copy()
cfg['E'] = cfg['D'][cfg['D']['hour_et'] == 15].copy()
cfg['F'] = PH[PH['pattern_strength'] <= 0.70].copy()
cfg['G'] = H15.copy()
# New configs
cfg['H'] = PH[PH['screener_score'] <= 10].copy()                         # 14-16, solo score
cfg['I'] = H15[H15['screener_score'] <= 10].copy()                       # 15ET + score
cfg['J'] = PH[~PH['symbol'].isin(BLOCKED_NEG)].copy()                   # 14-16, no neg sym
cfg['K'] = H15[~H15['symbol'].isin(BLOCKED_NEG)].copy()                 # 15ET, no neg sym
cfg['L'] = PH[PH['regime'].isin(['bear', 'neutral'])].copy()            # 14-16, no BULL
cfg['M'] = H15[H15['regime'].isin(['bear', 'neutral'])].copy()          # 15ET, no BULL

NAMES = {
    'A': '14-16, 4pat base',
    'B': '14-16, +str≤0.75',
    'C': '14-16, +str+score≤10',
    'D': '14-16, +str+score+noNeg',
    'E': '15ET,  +str+score+noNeg',
    'F': '14-16, +str≤0.70',
    'G': '15ET,  base',
    'H': '14-16, solo score≤10',
    'I': '15ET,  solo score≤10',
    'J': '14-16, no neg sym',
    'K': '15ET,  no neg sym',
    'L': '14-16, solo BEAR+NEUTRAL',
    'M': '15ET,  solo BEAR+NEUTRAL',
}

SEP = '═' * 80

# ═══════════════════════════════════════════════════════════════════════════
# SEZIONE 1 — Config singole
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SEZIONE 1 — CONFIG 5m SINGOLE A-M")
print(SEP)
print(f"\n  {'Cfg':<3}  {'Descrizione':<28}  {'n':>5}  {'avg_r':>6}  {'avg+slip':>8}  {'WR%':>5}  {'λ/m':>5}  {'T/anno':>6}  {'€/anno':>9}")
print('  ' + '─' * 84)

rank_rows = []
for k, nm in NAMES.items():
    n, ar, aadj, wr = S(cfg[k])
    l = lam(cfg[k])
    tpy = l * 12
    eur = tpy * aadj * RISK_EUR
    rank_rows.append((k, nm, n, ar, aadj, wr, l, tpy, eur))
    print(f"  {k:<3}  {nm:<28}  {n:>5,}  {ar:>6.3f}  {aadj:>8.3f}  {wr:>5.1f}%  {l:>5.1f}  {tpy:>6.0f}  {eur:>9,.0f}")

# ═══════════════════════════════════════════════════════════════════════════
# SEZIONE 2 — Stabilità OOS (tutte le config)
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SEZIONE 2 — STABILITÀ ANNUALE avg_r+slip")
print(SEP)
print(f"\n  {'Cfg':<3}  {'Desc':<28}  {'n_24':>5}  {'2024':>7}  {'n_25':>5}  {'2025':>7}  {'n_26':>5}  {'2026':>7}  {'Stab':>5}")
print('  ' + '─' * 84)

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
    ok = sum(v > 0 for v in vals if not pd.isna(v))
    stab = 'SI' if ok == 3 else ('PAR' if ok == 2 else 'NO')
    def f(v): return f"{v:>+7.3f}" if not pd.isna(v) else "    N/A"
    print(f"  {k:<3}  {nm:<28}  {row[0]:>5,}  {f(row[1])}  {row[2]:>5,}  {f(row[3])}  {row[4]:>5,}  {f(row[5])}  {stab:>5}")

# ═══════════════════════════════════════════════════════════════════════════
# MONTE CARLO
# ═══════════════════════════════════════════════════════════════════════════
def run_mc(r1h, l1h, r5m, l5m):
    r1 = np.asarray(r1h, dtype=float)
    r5 = np.asarray(r5m, dtype=float)
    has5 = l5m > 0 and len(r5) > 0

    c1_mat = RNG.poisson(l1h, size=(N_SIM, N_MONTHS))
    c5_mat = RNG.poisson(l5m, size=(N_SIM, N_MONTHS)) if has5 else None

    finals  = np.empty(N_SIM)
    max_dds = np.empty(N_SIM)

    for s in range(N_SIM):
        monthly = np.zeros(N_MONTHS)
        for m in range(N_MONTHS):
            n1 = int(c1_mat[s, m])
            if n1 > 0:
                monthly[m] += RNG.choice(r1, size=n1, replace=True).sum()
            if has5:
                n5 = int(c5_mat[s, m])
                if n5 > 0:
                    monthly[m] += RNG.choice(r5, size=n5, replace=True).sum()

        cum = np.concatenate([[0.0], np.cumsum(monthly)]) * RISK_EUR
        finals[s] = cum[-1]
        peak = np.maximum.accumulate(cum)
        max_dds[s] = np.max(peak - cum)

    return {
        'med':    int(np.median(finals)),
        'w5':     int(np.percentile(finals, 5)),
        'pp':     round((finals > 0).mean() * 100, 1),
        'dd_med': int(np.median(max_dds)),
        'dd_w95': int(np.percentile(max_dds, 95)),
    }

print(f"\n{SEP}")
print(f"SEZIONE 3 — MONTE CARLO 1h + ogni config  ({N_SIM} sim, €{RISK_EUR:,}/trade, 12 mesi)")
print(SEP)

lam_1h = lam(base1)
r_1h   = base1['pnl_r_adj'].values

print(f"\n  1h: n={len(base1):,}  λ/m={lam_1h:.1f}  avg_r={r_1h.mean():.3f}  WR={base1['win'].mean()*100:.1f}%")
print()

# Solo 1h baseline
print(f"  Computing Solo 1h...", flush=True, end='')
solo_res = run_mc(r_1h, lam_1h, np.array([]), 0.0)
print(f" done")

MC_SCENARIOS = ['A','B','C','D','E','F','G','H','I','J','K','L','M']
mc_res = {}

for k in MC_SCENARIOS:
    print(f"  Computing 1h+{k}...", flush=True, end='')
    c = cfg[k]
    r5 = c['pnl_r_adj'].values
    l5 = lam(c)
    mc_res[k] = run_mc(r_1h, lam_1h, r5, l5)
    mc_res[k]['lam5'] = l5
    mc_res[k]['tpy']  = (lam_1h + l5) * 12
    # weighted avg_r
    nt = len(r_1h) + len(r5)
    mc_res[k]['wavg'] = (r_1h.mean() * len(r_1h) + r5.mean() * len(r5)) / nt if nt > 0 else r_1h.mean()
    print(f" done")

print()
print(f"\n  {'Scenario':<16}  {'T/anno':>6}  {'avg_r':>6}  {'Mediana':>9}  {'Worst5%':>9}  {'ProbP':>6}  {'DD_med':>8}  {'DD_w95':>8}")
print('  ' + '─' * 82)

solo_tpy  = lam_1h * 12
solo_wavg = r_1h.mean()
print(f"  {'Solo 1h':<16}  {solo_tpy:>6.0f}  {solo_wavg:>6.3f}  {solo_res['med']/1e3:>8.0f}k  {solo_res['w5']/1e3:>8.0f}k  {solo_res['pp']:>5.1f}%  {solo_res['dd_med']/1e3:>6.0f}k  {solo_res['dd_w95']/1e3:>6.0f}k")

mc_table = []
for k in MC_SCENARIOS:
    r = mc_res[k]
    lbl = f"1h + {k}"
    print(f"  {lbl:<16}  {r['tpy']:>6.0f}  {r['wavg']:>6.3f}  {r['med']/1e3:>8.0f}k  {r['w5']/1e3:>8.0f}k  {r['pp']:>5.1f}%  {r['dd_med']/1e3:>6.0f}k  {r['dd_w95']/1e3:>6.0f}k")
    mc_table.append((k, r['tpy'], r['wavg'], r['med'], r['w5'], r['pp'], r['dd_med'], r['dd_w95']))

# ═══════════════════════════════════════════════════════════════════════════
# SEZIONE 4 — Trade-off volume vs qualità
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SEZIONE 4 — TRADE-OFF VOLUME vs QUALITÀ  (5m solo)")
print(SEP)
print(f"\n  {'Cfg':<3}  {'Desc':<28}  {'€/anno':>9}  {'DD_w95':>8}  {'P/DD':>6}  {'T/anno':>6}  {'avg+slip':>8}")
print('  ' + '─' * 70)

ratio_rows = []
for k, nm, n, ar, aadj, wr, l, tpy, eur in rank_rows:
    r = mc_res[k]
    dd95 = r['dd_w95']
    # P/DD = profitto annuo 5m / DD from combined MC
    # Use 5m-only annual profit vs combined DD as rough ratio
    ratio = eur / dd95 if dd95 > 0 else 0
    ratio_rows.append((k, nm, eur, dd95, ratio, tpy, aadj))

ratio_rows_s = sorted(ratio_rows, key=lambda x: -x[2])
for k, nm, eur, dd95, ratio, tpy, aadj in ratio_rows_s:
    print(f"  {k:<3}  {nm:<28}  {eur:>9,.0f}  {dd95/1e3:>6.0f}k  {ratio:>6.2f}  {tpy:>6.0f}  {aadj:>8.3f}")

# ═══════════════════════════════════════════════════════════════════════════
# SEZIONE 5 — Ranking finale multi-criterio
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SEZIONE 5 — RANKING FINALE MULTI-CRITERIO")
print(SEP)

# Score: (1) Mediana MC combinato, (2) ProbP, (3) Worst5%, (4) Stabilità
# Normalize each metric to [0,1] and combine
meds    = np.array([r['med']    for _, r in [(k, mc_res[k]) for k in MC_SCENARIOS]], dtype=float)
w5s     = np.array([r['w5']     for _, r in [(k, mc_res[k]) for k in MC_SCENARIOS]], dtype=float)
pps     = np.array([r['pp']     for _, r in [(k, mc_res[k]) for k in MC_SCENARIOS]], dtype=float)
dd_w95s = np.array([r['dd_w95'] for _, r in [(k, mc_res[k]) for k in MC_SCENARIOS]], dtype=float)

def norm(arr):
    mn, mx = arr.min(), arr.max()
    return (arr - mn) / (mx - mn) if mx > mn else np.ones_like(arr) * 0.5

# Stability score from Sezione 2
def stab_score(k):
    c = cfg[k]
    scores = []
    for yr in [2024, 2025, 2026]:
        sub = c[c['year'] == yr]
        if len(sub) >= 5:
            scores.append(1 if sub['pnl_r_adj'].mean() > 0 else 0)
    return sum(scores) / max(len(scores), 1)

stab_arr = np.array([stab_score(k) for k in MC_SCENARIOS])

# Weights: median 40%, stability 25%, worst5% 20%, low-DD 15%
score = (0.40 * norm(meds) +
         0.25 * stab_arr +
         0.20 * norm(w5s) +
         0.15 * norm(-dd_w95s))  # lower DD = better

ranked = sorted(zip(MC_SCENARIOS, score), key=lambda x: -x[1])

print(f"\n  {'Rk':<3}  {'Cfg':<3}  {'Desc':<28}  {'Score':>6}  {'Med_MC':>9}  {'Worst5%':>9}  {'Stab':>5}  {'Filtri'}")
print('  ' + '─' * 86)

complexity = {
    'A': '1 (solo ore)',
    'B': '2 (ore+str)',
    'C': '3 (ore+str+score)',
    'D': '4 (ore+str+score+sym)',
    'E': '4 (ore+str+score+sym)',
    'F': '2 (ore+str_stretto)',
    'G': '1 (solo ore)',
    'H': '2 (ore+score)',
    'I': '2 (ore+score)',
    'J': '2 (ore+sym)',
    'K': '2 (ore+sym)',
    'L': '2 (ore+regime_stretto)',
    'M': '2 (ore+regime_stretto)',
}

for rank, (k, sc) in enumerate(ranked, 1):
    r = mc_res[k]
    nm = NAMES[k]
    sv = stab_score(k)
    stab_lbl = 'SI' if sv >= 1.0 else ('PAR' if sv >= 0.67 else 'NO')
    star = ' ★' if rank <= 3 else ''
    print(f"  {rank:<3}  {k:<3}  {nm:<28}  {sc:>6.3f}  {r['med']/1e3:>8.0f}k  {r['w5']/1e3:>8.0f}k  {stab_lbl:>5}  {complexity[k]}{star}")

print(f"\n  Nota: Score = 0.40×(mediana) + 0.25×(stabilità) + 0.20×(worst5%) + 0.15×(−DD)")

# ═══ Summary tabellare ══════════════════════════════════════════════════
print(f"\n{SEP}")
print("RIEPILOGO — tutti i numeri in una tabella")
print(SEP)
print(f"\n  {'Cfg':<3}  {'T/anno':>6}  {'avg+slip':>8}  {'€5m/anno':>9}  {'Med_combo':>10}  {'W5_combo':>10}  {'ProbP':>6}  {'DD_med':>7}  {'Stab':>5}")
print('  ' + '─' * 84)

# Solo 1h row
print(f"  {'1h':<3}  {solo_tpy:>6.0f}  {solo_wavg:>8.3f}  {'(base)':>9}  {solo_res['med']/1e3:>9.0f}k  {solo_res['w5']/1e3:>9.0f}k  {solo_res['pp']:>5.1f}%  {solo_res['dd_med']/1e3:>5.0f}k  {'─':>5}")

for k, nm, n, ar, aadj, wr, l, tpy5, eur in rank_rows:
    r = mc_res[k]
    sv = stab_score(k)
    stab_lbl = 'SI' if sv >= 1.0 else ('PAR' if sv >= 0.67 else 'NO')
    print(f"  {k:<3}  {tpy5:>6.0f}  {aadj:>8.3f}  {eur:>9,.0f}  {r['med']/1e3:>9.0f}k  {r['w5']/1e3:>9.0f}k  {r['pp']:>5.1f}%  {r['dd_med']/1e3:>5.0f}k  {stab_lbl:>5}")

print(f"\n=== DONE ===\n")
