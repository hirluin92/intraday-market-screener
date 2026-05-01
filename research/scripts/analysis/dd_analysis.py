#!/usr/bin/env python3
"""Trade-level drawdown analysis per le top config 5m + 1h."""
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

# ── Regime (same as before) ────────────────────────────────────────────────
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

BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})

print("Loading data...", flush=True)
df5 = pd.read_csv('/app/data/val_5m_expanded.csv')
df5['ts']     = pd.to_datetime(df5['pattern_timestamp'], utc=True)
df5['_d']     = df5['ts'].apply(lambda x: x.date())
df5['regime'] = df5['_d'].apply(get_regime)
df5['year']   = df5['ts'].dt.year
if TZ_ET:
    df5['hour_et'] = df5['ts'].dt.tz_convert(TZ_ET).dt.hour
else:
    df5['hour_et'] = (df5['ts'].dt.hour - 4) % 24

base5 = add_slip(df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE)) &
    (df5['pattern_name'] != 'engulfing_bullish') &
    regime_mask(df5)
].copy())

df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts']     = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d']     = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1['year']   = df1['ts'].dt.year
base1 = add_slip(df1[(df1['risk_pct'] >= 0.30) & regime_mask(df1)].copy())

PH   = base5[base5['hour_et'].between(14, 15)]
H15  = base5[base5['hour_et'] == 15]

cfg = {
    'A': PH.copy(),
    'G': H15.copy(),
    'F': PH[PH['pattern_strength'] <= 0.70].copy(),
    'B': PH[PH['pattern_strength'] <= 0.75].copy(),
}

def lam(c, from_year=2024):
    sub = c[c['year'] >= from_year]
    if len(sub) < 3:
        return 0.0
    span = (sub['ts'].max() - sub['ts'].min()).days / 30.44
    return len(sub) / max(span, 1.0)

lam_1h = lam(base1)
r_1h   = base1['pnl_r_adj'].values

SEP = '═' * 76

# ── Trade-level MC with proper drawdown ────────────────────────────────────
def run_mc_trade(r1h, l1h, r5m, l5m, label=""):
    r1 = np.asarray(r1h, dtype=float)
    r5 = np.asarray(r5m, dtype=float)
    has5 = l5m > 0 and len(r5) > 0

    finals  = np.empty(N_SIM)
    max_dds = np.empty(N_SIM)
    max_str = np.empty(N_SIM, dtype=int)   # max consecutive losses

    for s in range(N_SIM):
        # Draw total annual trades per leg
        n1 = int(RNG.poisson(l1h * N_MONTHS))
        n5 = int(RNG.poisson(l5m * N_MONTHS)) if has5 else 0

        parts = []
        if n1 > 0:
            parts.append(RNG.choice(r1, size=n1, replace=True))
        if n5 > 0:
            parts.append(RNG.choice(r5, size=n5, replace=True))

        if not parts:
            finals[s] = 0.0; max_dds[s] = 0.0; max_str[s] = 0
            continue

        rets = np.concatenate(parts)
        RNG.shuffle(rets)            # random interleaving of 1h and 5m
        rets_eur = rets * RISK_EUR

        cum = np.concatenate([[0.0], np.cumsum(rets_eur)])
        finals[s] = cum[-1]

        # Max drawdown from peak
        peak = np.maximum.accumulate(cum)
        max_dds[s] = np.max(peak - cum)

        # Max consecutive losses
        losses = rets < 0
        streak = max_run = cur_run = 0
        for lv in losses:
            if lv:
                cur_run += 1
                if cur_run > max_run:
                    max_run = cur_run
            else:
                cur_run = 0
        max_str[s] = max_run

    return {
        'label':    label,
        'med':      int(np.median(finals)),
        'w5':       int(np.percentile(finals, 5)),
        'pp':       round((finals > 0).mean() * 100, 1),
        'dd_med':   int(np.median(max_dds)),
        'dd_w5':    int(np.percentile(max_dds, 95)),   # worst 5% DD
        'streak_med': int(np.median(max_str)),
        'streak_95':  int(np.percentile(max_str, 95)),
        'n_trades': int(np.mean(np.array([int(RNG.poisson((l1h+l5m)*N_MONTHS)) for _ in range(100)]))),
    }

print(f"\n{SEP}")
print(f"DRAWDOWN TRADE-LEVEL  ({N_SIM} sim, €{RISK_EUR:,}/trade, 12 mesi)")
print(f"(simulation interleave casuale 1h+5m trades per equity curve realistica)")
print(SEP)

scenarios = [
    ('Solo 1h',    np.array([]), 0.0),
    ('1h + A',     cfg['A']['pnl_r_adj'].values, lam(cfg['A'])),
    ('1h + B',     cfg['B']['pnl_r_adj'].values, lam(cfg['B'])),
    ('1h + F',     cfg['F']['pnl_r_adj'].values, lam(cfg['F'])),
    ('1h + G',     cfg['G']['pnl_r_adj'].values, lam(cfg['G'])),
]

print(f"\n  {'Scenario':<14}  {'T/anno':>7}  {'Med_12m':>9}  {'W5_12m':>9}  {'DD_med':>8}  {'DD_w95':>8}  {'Calmar':>7}  {'Streak95':>9}")
print('  ' + '─' * 80)

results = []
for label, r5m, l5m in scenarios:
    print(f"  {label}...", flush=True, end='')
    res = run_mc_trade(r_1h, lam_1h, r5m, l5m, label=label)
    res['lam5'] = l5m
    results.append(res)
    tpy = (lam_1h + l5m) * 12
    calmar = res['med'] / res['dd_med'] if res['dd_med'] > 0 else float('inf')
    calmar_s = f"{calmar:.2f}" if calmar != float('inf') else "∞"
    print(f" done")
    print(f"  {label:<14}  {tpy:>7.0f}  {res['med']/1e3:>8.0f}k  {res['w5']/1e3:>8.0f}k  {res['dd_med']/1e3:>6.0f}k  {res['dd_w5']/1e3:>6.0f}k  {calmar_s:>7}  {res['streak_95']:>9}")

# ── Consecutive loss analysis ──────────────────────────────────────────────
print(f"\n{SEP}")
print("ANALISI PERDITE CONSECUTIVE — distribuzione streak")
print(SEP)

for label, r5m, l5m in scenarios:
    r_combo = np.concatenate([r_1h, r5m]) if len(r5m) > 0 else r_1h
    wr = (r_combo > 0).mean() * 100
    p_loss = 1 - (r_combo > 0).mean()
    # Expected max losing streak in N trades (analytic approx)
    tpy = (lam_1h + l5m) * 12
    # E[max consecutive failures in N Bernoulli(p)] ≈ log(N*p_loss) / log(1/p_loss)
    if p_loss > 0 and tpy > 0:
        exp_streak = np.log(tpy * p_loss) / np.log(1.0 / p_loss)
    else:
        exp_streak = 0
    streak_loss_eur = exp_streak * 1.3 * RISK_EUR  # avg loss ≈ -1.3R
    print(f"  {label:<14}: WR={wr:.1f}%  p_loss={p_loss:.3f}  T/anno={tpy:.0f}")
    print(f"              Streak attesa={exp_streak:.1f}  €DD da streak={streak_loss_eur:,.0f}")

# ── Summary ────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("NOTE INTERPRETATIVE")
print(SEP)
print("""
  DD mensile = 0k (nelle sim precedenti) perché:
  - 1h: 97 trade/mese × avg_r=+0.975 → E[€/mese] = +€94k, σ ≈ €12k
  - P(mese negativo) ≈ P(Z < -94k/12k) = P(Z < -7.8) ≈ 0.0000001

  DD trade-level è più realistico:
  - Include le oscillazioni intra-mese trade per trade
  - La streak analysis mostra il rischio di perdite consecutive

  CALMAR RATIO = Profitto_annuo / DD_max
  - > 3.0 = eccellente
  - 1.0-3.0 = buono
  - < 1.0 = da migliorare
""")
print("=== DONE ===")
