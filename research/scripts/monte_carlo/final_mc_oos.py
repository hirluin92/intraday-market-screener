#!/usr/bin/env python3
"""
VERIFICHE OOS FINALI — Pre paper trading
  1. Risk variabile (1h=1.5%/5m=0.5%) con edge degradation
  2. Gap filter OOS (escludere LONG su gap_up +1-2%)
  3. Monte Carlo DEFINITIVO — configurazione completa

Parametri:
  Capitale: €100,000  |  N_SIM: 5,000  |  N_MONTHS: 12
  1h: 47 simboli Yahoo, regime SPY, MIN_RISK=0.30%
  5m TRIPLO: 6 pattern, ALPHA(15:xx) + MIDDAY_F(11-14, at_extreme, BTE=1)
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

SEP  = '═' * 82
SEP2 = '─' * 82

CAPITAL      = 100_000.0
N_SIM        = 5_000
N_MONTHS     = 12
RISK_1H_BASE = 1_000.0   # 1% of 100k = €1,000/trade
RISK_5M_BASE = 1_000.0   # 1% of 100k
RISK_1H_OPT  = 1_500.0   # 1.5%
RISK_5M_OPT  =   500.0   # 0.5%
BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})
GOOD_PAT     = frozenset({'double_bottom','double_top',
                           'macd_divergence_bull','macd_divergence_bear',
                           'rsi_divergence_bull','rsi_divergence_bear'})

np.random.seed(42)

# ── DB ────────────────────────────────────────────────────────────────────────
print("Loading DB...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("""SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
               FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp""")
spy_1d = cur.fetchall()
cur.execute("""SELECT symbol, DATE(timestamp AT TIME ZONE 'UTC'),
                      open::float, high::float, low::float, close::float
               FROM candles WHERE timeframe='1d'""")
sym_1d_rows = cur.fetchall()
conn.close()

spy_df = pd.DataFrame(spy_1d, columns=['date','close'])
spy_df['ema50']  = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']    = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] >  2, 'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2, 'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

sym_1d_df = pd.DataFrame(sym_1d_rows, columns=['symbol','date','open','high','low','close'])
sym_1d_df = sym_1d_df.sort_values(['symbol','date'])
sym_1d_df['prev_close'] = sym_1d_df.groupby('symbol')['close'].shift(1)
sym_1d_df['gap_pct'] = (sym_1d_df['open'] - sym_1d_df['prev_close']) / sym_1d_df['prev_close'] * 100
sym_1d_dict = {(r['symbol'], r['date']): r for _, r in sym_1d_df.iterrows()}

def get_regime(d):
    for i in range(1, 15):
        v = spy_dict.get(d - timedelta(days=i))
        if v is not None: return v
    return 'neutral'

def regime_ok(row):
    reg = row['regime']; dir_ = row['direction']
    return (reg == 'neutral') or (reg == 'bull' and dir_ == 'bullish') or (reg == 'bear' and dir_ == 'bearish')

def add_slip(df):
    df = df.copy()
    df['pnl_r_adj'] = (df['pnl_r']
        - 0.03 / df['risk_pct']
        - np.where(df['outcome'] == 'stop', 0.05 / df['risk_pct'], 0.0))
    df['win'] = df['pnl_r_adj'] > 0
    return df

# ── 5m dataset ────────────────────────────────────────────────────────────────
print("Loading 5m...", flush=True)
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
    df5['hour_et'] = (df5['ts'].dt.hour - 4) % 24
    df5['min_et']  = df5['ts'].dt.minute

base6 = add_slip(df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE)) &
    (df5['pattern_name'].isin(GOOD_PAT)) &
    df5.apply(regime_ok, axis=1)
].copy())

alpha_b6  = base6[base6['hour_et'] == 15].copy()
midday_b6 = base6[base6['hour_et'].between(11, 14)].copy()

# ── at_extreme per MIDDAY_F (DB join) ────────────────────────────────────────
print("Fetching candle OHLC for at_extreme...", flush=True)
conn2 = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                         user='postgres', password='postgres')
cur2  = conn2.cursor()
cur2.execute("CREATE TEMP TABLE _tt (sym VARCHAR(20), ts TIMESTAMPTZ) ON COMMIT DELETE ROWS")
cur2.executemany("INSERT INTO _tt VALUES (%s,%s)",
                 [(r['symbol'], r['ts']) for _, r in midday_b6.iterrows()])
cur2.execute("""SELECT c.symbol, c.timestamp, c.high::float, c.low::float
                FROM candles c JOIN _tt t ON c.symbol=t.sym AND c.timestamp=t.ts
                WHERE c.timeframe='5m'""")
candle_data = {(sym, pd.Timestamp(ts)): (h, l)
               for sym, ts, h, l in cur2.fetchall()}
conn2.close()

c_low = []; c_high = []; d_high = []; d_low = []
for _, row in midday_b6.iterrows():
    cd = candle_data.get((row['symbol'], row['ts']), (np.nan, np.nan))
    sd = sym_1d_dict.get((row['symbol'], row['_d']), {})
    c_high.append(cd[0]); c_low.append(cd[1])
    d_high.append(sd.get('high', np.nan)); d_low.append(sd.get('low', np.nan))

midday_ext = midday_b6.copy()
midday_ext['c_low'] = c_low; midday_ext['c_high'] = c_high
midday_ext['d_low'] = d_low; midday_ext['d_high'] = d_high
day_range = midday_ext['d_high'] - midday_ext['d_low']
midday_ext['dist_extreme'] = np.where(
    midday_ext['direction'] == 'bullish',
    np.where(day_range > 0, (midday_ext['c_low'] - midday_ext['d_low']) / day_range, np.nan),
    np.where(day_range > 0, (midday_ext['d_high'] - midday_ext['c_high']) / day_range, np.nan))
midday_ext['at_extreme'] = midday_ext['dist_extreme'] < 0.10

mid_f = midday_ext[midday_ext['at_extreme'] & (midday_ext['bars_to_entry'] == 1)].copy()

triplo = pd.concat([alpha_b6, mid_f], ignore_index=True)
print(f"  ALPHA={len(alpha_b6)}, MIDDAY_F={len(mid_f)}, TRIPLO={len(triplo)}", flush=True)

# ── 1h dataset ────────────────────────────────────────────────────────────────
print("Loading 1h...", flush=True)
df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts']   = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d']   = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1['year'] = df1['ts'].dt.year
base1h = add_slip(df1[
    (df1['entry_filled'] == True) &
    (df1['risk_pct'] >= 0.30) &
    df1.apply(regime_ok, axis=1)
].copy())
print(f"  1h: {len(base1h)}", flush=True)

# ── Lambda computation (2024+ only, annualized) ───────────────────────────────
def compute_lambda(df, from_year=2024):
    sub = df[df['year'] >= from_year]
    if len(sub) < 2: return 0.0
    span = (sub['ts'].max() - sub['ts'].min()).days / 30.44
    return len(sub) / max(span, 1.0)

lam_1h     = compute_lambda(base1h)
lam_alpha  = compute_lambda(alpha_b6)
lam_midf   = compute_lambda(mid_f)
lam_triplo = lam_alpha + lam_midf

print(f"  λ/mese: 1h={lam_1h:.1f}  ALPHA={lam_alpha:.1f}  MIDDAY_F={lam_midf:.1f}  "
      f"TRIPLO={lam_triplo:.1f}", flush=True)

r_1h     = base1h['pnl_r_adj'].values
r_triplo = triplo['pnl_r_adj'].values
r_alpha  = alpha_b6['pnl_r_adj'].values

# ── Gap data for alpha ─────────────────────────────────────────────────────────
gaps = [sym_1d_dict.get((r['symbol'], r['_d']), {}).get('gap_pct', np.nan)
        for _, r in alpha_b6.iterrows()]
alpha_b6 = alpha_b6.copy()
alpha_b6['gap_pct'] = gaps

# ── MC engine ─────────────────────────────────────────────────────────────────
def run_mc(r_1h_v, lam_1h_v, r_5m_v, lam_5m_v,
           risk_1h, risk_5m, edge=1.0,
           n_sim=N_SIM, n_months=N_MONTHS, capital=CAPITAL):
    """
    Full Monte Carlo. Returns final P&L distribution + per-month paths.
    edge: scale factor on pnl (1.0=full, 0.5=half edge degraded).
    """
    r1 = r_1h_v * edge
    r5 = r_5m_v * edge
    final_pnl = np.zeros(n_sim)
    max_dds   = np.zeros(n_sim)
    monthly   = np.zeros((n_sim, n_months))

    for i in range(n_sim):
        eq   = capital
        peak = capital
        for m in range(n_months):
            m_pnl = 0.0
            n1 = np.random.poisson(lam_1h_v)
            if n1 > 0 and len(r1) > 0:
                idx = np.random.randint(0, len(r1), n1)
                m_pnl += risk_1h * r1[idx].sum()
            n5 = np.random.poisson(lam_5m_v)
            if n5 > 0 and len(r5) > 0:
                idx = np.random.randint(0, len(r5), n5)
                m_pnl += risk_5m * r5[idx].sum()
            eq += m_pnl
            monthly[i, m] = eq - capital   # cumulative P&L
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dds[i]:
                max_dds[i] = dd
        final_pnl[i] = eq - capital

    return {
        'median':   np.median(final_pnl),
        'p05':      np.percentile(final_pnl, 5),
        'p95':      np.percentile(final_pnl, 95),
        'p25':      np.percentile(final_pnl, 25),
        'p75':      np.percentile(final_pnl, 75),
        'prob_pos': (final_pnl > 0).mean(),
        'dd_p95':   np.percentile(max_dds, 95),
        'dd_p50':   np.median(max_dds),
        'monthly_med': np.median(monthly, axis=0),
        'monthly_p05': np.percentile(monthly, 5, axis=0),
        'monthly_p95': np.percentile(monthly, 95, axis=0),
    }

def fmt_eur(v): return f"€{v:>+9,.0f}"
def fmt_pct_d(v): return f"{v*100:>6.1f}%"

# ════════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("1. RISK VARIABILE — OOS CON EDGE DEGRADATION")
print(f"   1% uniforme vs 1h=1.5%/5m=0.5%  —  TRIPLO 5m + 1h")
print(SEP)

print(f"\n  λ: 1h={lam_1h:.1f}/m  TRIPLO-5m={lam_triplo:.1f}/m")
print(f"  r_1h:    mean={r_1h.mean():+.4f}R  std={r_1h.std():.4f}R  n={len(r_1h)}")
print(f"  r_triplo: mean={r_triplo.mean():+.4f}R  std={r_triplo.std():.4f}R  n={len(r_triplo)}")
print()

EDGES = [1.00, 0.75, 0.50, 0.25]
configs = [
    ("Uniforme 1%/1%",    RISK_1H_BASE, RISK_5M_BASE),
    ("Opt 1.5%/0.5%",     RISK_1H_OPT,  RISK_5M_OPT),
]

# Header
print(f"  {'Edge':>6}  {'Config':<22}  {'Mediana':>10}  {'Worst 5%':>10}  "
      f"{'DD p95':>8}  {'DD med':>8}  {'ProbP':>7}")
print("  " + "─" * 80)

results = {}
for edge in EDGES:
    for cfg_lbl, r1h_eur, r5m_eur in configs:
        key = (edge, cfg_lbl)
        res = run_mc(r_1h, lam_1h, r_triplo, lam_triplo,
                     r1h_eur, r5m_eur, edge=edge)
        results[key] = res
        edge_s = f"{edge*100:.0f}%" if edge < 1.0 else "100%"
        print(f"  {edge_s:>6}  {cfg_lbl:<22}  "
              f"{fmt_eur(res['median'])}  {fmt_eur(res['p05'])}  "
              f"{fmt_pct_d(res['dd_p95'])}  {fmt_pct_d(res['dd_p50'])}  "
              f"{res['prob_pos']*100:>6.1f}%")
    print()

# Safety check
print(f"\n  SAFETY CHECK — 1.5%/0.5% vs 1%/1%:")
for edge_label, edge in [("100%", 1.0), ("75%", 0.75), ("50%", 0.50), ("25%", 0.25)]:
    r_opt    = results[(edge, "Opt 1.5%/0.5%")]
    r_base   = results[(edge, "Uniforme 1%/1%")]
    dd_opt   = r_opt['dd_p95']
    dd_base  = r_base['dd_p95']
    flag = " ✓" if dd_opt < 0.20 else (" ⚠ DD>20%!" if dd_opt < 0.30 else " ✗ DD>30% PERICOLOSO")
    print(f"  Edge {edge_label}: DD p95 opt={dd_opt*100:.1f}%  base={dd_base*100:.1f}%  "
          f"Mediana opt={fmt_eur(r_opt['median'])}  base={fmt_eur(r_base['median'])}{flag}")

# ════════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("2. GAP FILTER — OOS: escludere LONG su gap_up +1% a +2%")
print(SEP)

print(f"\n  Dataset: ALPHA 5m (15:xx, base6, con gap data)")
print(f"  Filtro: rimuove trade LONG quando gap_pct ∈ (+1%, +2%)")
print()

alpha_gap = alpha_b6.dropna(subset=['gap_pct']).copy()
alpha_gap['is_filtered'] = (
    (alpha_gap['direction'] == 'bullish') &
    (alpha_gap['gap_pct'] > 1.0) &
    (alpha_gap['gap_pct'] <= 2.0)
)

removed = alpha_gap[alpha_gap['is_filtered']]
kept    = alpha_gap[~alpha_gap['is_filtered']]

print(f"  Trade totali ALPHA (con gap): {len(alpha_gap):,}")
print(f"  Trade rimossi dal filtro:    {len(removed):,} ({len(removed)/len(alpha_gap)*100:.1f}%)")
print(f"  Trade mantenuti:             {len(kept):,}")
print()

print(f"  {'Anno':<6}  {'n_rimossi':>9}  {'avg_rim':>9}  "
      f"{'WR_rim':>8}  {'avg_sistema':>12}  {'avg_senza_rim':>13}  Stabile?")
print("  " + "─" * 72)

all_stable = True
for yr in [2024, 2025, 2026]:
    sub_yr  = alpha_gap[alpha_gap['year'] == yr]
    rim_yr  = sub_yr[sub_yr['is_filtered']]
    kept_yr = sub_yr[~sub_yr['is_filtered']]
    n_rim   = len(rim_yr)
    if n_rim < 2:
        print(f"  {yr:<6}  {n_rim:>9}  (pochi dati)")
        continue
    avg_rim  = rim_yr['pnl_r_adj'].mean()
    wr_rim   = rim_yr['win'].mean() * 100
    avg_sys  = sub_yr['pnl_r_adj'].mean()  if len(sub_yr) >= 3 else float('nan')
    avg_kept = kept_yr['pnl_r_adj'].mean() if len(kept_yr) >= 3 else float('nan')
    stable   = avg_rim < 0
    if not stable: all_stable = False
    flag = "SI ✓" if stable else "NO ✗"
    avg_rim_s  = f"{avg_rim:>+9.3f}R" if not np.isnan(avg_rim) else f"{'N/A':>9}"
    avg_sys_s  = f"{avg_sys:>+9.3f}R" if not np.isnan(avg_sys) else f"{'N/A':>9}"
    avg_kept_s = f"{avg_kept:>+9.3f}R" if not np.isnan(avg_kept) else f"{'N/A':>9}"
    print(f"  {yr:<6}  {n_rim:>9}  {avg_rim_s}  "
          f"{wr_rim:>7.1f}%  {avg_sys_s}   {avg_kept_s}   {flag}")

verdict = "IMPLEMENTA il filtro" if all_stable else "NON implementare (instabile OOS)"
print(f"\n  VERDETTO: {verdict}")
print(f"  ('Stabile' = i trade rimossi sono negativi in quell'anno)")

# Delta performance con/senza filtro
avg_full = alpha_gap['pnl_r_adj'].mean()
avg_filt = kept['pnl_r_adj'].mean()
delta    = avg_filt - avg_full
print(f"\n  Impatto sul avg+slip ALPHA:")
print(f"    Senza filtro: {avg_full:+.4f}R (n={len(alpha_gap)})")
print(f"    Con filtro:   {avg_filt:+.4f}R (n={len(kept)})")
print(f"    Delta:        {delta:+.4f}R per trade")

# Decide which r_alpha to use for final MC
if all_stable and delta > 0:
    r_alpha_final = kept['pnl_r_adj'].values
    lam_alpha_final = compute_lambda(kept)
    print(f"\n  → Usando ALPHA filtrata per il MC finale (gap filter attivo)")
else:
    r_alpha_final = r_alpha
    lam_alpha_final = lam_alpha
    print(f"\n  → Usando ALPHA originale per il MC finale (gap filter NON attivo)")

r_5m_final   = np.concatenate([r_alpha_final, mid_f['pnl_r_adj'].values])
lam_5m_final = lam_alpha_final + lam_midf

# ════════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("3. MONTE CARLO DEFINITIVO FINALE")
print(f"   Capitale: €{CAPITAL:,.0f}  |  N_SIM: {N_SIM:,}  |  N_MONTHS: {N_MONTHS}")
print(f"   1h (1.5%): λ={lam_1h:.1f}/m  avg={r_1h.mean():+.4f}R  WR={base1h['win'].mean()*100:.1f}%")
print(f"   5m TRIPLO (0.5%): λ={lam_5m_final:.1f}/m  avg={r_5m_final.mean():+.4f}R  "
      f"WR={(r_5m_final>0).mean()*100:.1f}%")
print(SEP)

# ── 3a: Scenari principali ───────────────────────────────────────────────────
print(f"\n  3a. Scenari principali (edge 100%)")
print()
print(f"  {'Scenario':<40}  {'T/anno':>7}  {'avg_r':>7}  "
      f"{'Mediana':>10}  {'Worst 5%':>10}  {'DD p95':>8}  {'ProbP':>7}")
print("  " + "─" * 90)

scenarios_main = [
    ("1h solo (1%)",
     r_1h, lam_1h, np.array([0.0]), 0.0, RISK_1H_BASE, 0.0),
    ("5m TRIPLO solo (1%)",
     np.array([0.0]), 0.0, r_5m_final, lam_5m_final, 0.0, RISK_1H_BASE),
    ("1h(1%) + 5m TRIPLO(1%) uniforme",
     r_1h, lam_1h, r_5m_final, lam_5m_final, RISK_1H_BASE, RISK_1H_BASE),
    ("1h(1.5%) + 5m TRIPLO(0.5%) OTTIMALE",
     r_1h, lam_1h, r_5m_final, lam_5m_final, RISK_1H_OPT, RISK_5M_OPT),
    ("1h(2%) + 5m TRIPLO(0.5%)",
     r_1h, lam_1h, r_5m_final, lam_5m_final, RISK_1H_BASE*2, RISK_5M_OPT),
]
main_results = {}
for lbl, r1, l1, r5, l5, eur1, eur5 in scenarios_main:
    res = run_mc(r1, l1, r5, l5, eur1, eur5, edge=1.0)
    main_results[lbl] = res
    t_anno = (l1 + l5) * 12
    avg_r_comb = (r1.mean()*l1 + r5.mean()*l5) / max(l1+l5, 0.01)
    print(f"  {lbl:<40}  {t_anno:>7.0f}  {avg_r_comb:>+6.3f}R  "
          f"{fmt_eur(res['median'])}  {fmt_eur(res['p05'])}  "
          f"{fmt_pct_d(res['dd_p95'])}  {res['prob_pos']*100:>6.1f}%")

# ── 3b: Edge degradation per scenario ottimale ───────────────────────────────
print(f"\n  3b. Edge degradation — Config OTTIMALE (1h=1.5%/5m=0.5%)")
print()
print(f"  {'Edge':>6}  {'Mediana':>10}  {'Worst 5%':>10}  {'P25':>10}  "
      f"{'P75':>10}  {'DD p95':>8}  {'DD med':>8}  {'ProbP':>7}")
print("  " + "─" * 82)

edge_results_opt = {}
for edge in [1.00, 0.75, 0.50, 0.25, 0.10]:
    res = run_mc(r_1h, lam_1h, r_5m_final, lam_5m_final,
                 RISK_1H_OPT, RISK_5M_OPT, edge=edge)
    edge_results_opt[edge] = res
    edge_s = f"{edge*100:.0f}%"
    flag = ""
    if edge == 0.25:
        flag = " ← STRESS TEST"
    elif edge == 0.10:
        flag = " ← WORST CASE"
    print(f"  {edge_s:>6}  {fmt_eur(res['median'])}  {fmt_eur(res['p05'])}  "
          f"{fmt_eur(res['p25'])}  {fmt_eur(res['p75'])}  "
          f"{fmt_pct_d(res['dd_p95'])}  {fmt_pct_d(res['dd_p50'])}  "
          f"{res['prob_pos']*100:>6.1f}%{flag}")

# ── 3c: Edge degradation uniforme per confronto ──────────────────────────────
print(f"\n  3c. Edge degradation — Config BASE (1%/1%) per confronto")
print()
print(f"  {'Edge':>6}  {'Mediana':>10}  {'Worst 5%':>10}  {'DD p95':>8}  {'ProbP':>7}")
print("  " + "─" * 50)
for edge in [1.00, 0.75, 0.50, 0.25, 0.10]:
    res = run_mc(r_1h, lam_1h, r_5m_final, lam_5m_final,
                 RISK_1H_BASE, RISK_5M_BASE, edge=edge)
    edge_s = f"{edge*100:.0f}%"
    print(f"  {edge_s:>6}  {fmt_eur(res['median'])}  {fmt_eur(res['p05'])}  "
          f"{fmt_pct_d(res['dd_p95'])}  {res['prob_pos']*100:>6.1f}%")

# ── 3d: Equity mensile per config ottimale (100% edge) ───────────────────────
print(f"\n  3d. Equity mensile — Config OTTIMALE (edge=100%)")
print()
opt_100 = edge_results_opt[1.00]
print(f"  {'Mese':>5}  {'Mediana cumul':>14}  {'P5 cumul':>10}  {'P95 cumul':>10}  "
      f"{'Mediana %':>10}  {'P5 %':>8}")
print("  " + "─" * 62)
for m in range(N_MONTHS):
    med = opt_100['monthly_med'][m]
    p5  = opt_100['monthly_p05'][m]
    p95 = opt_100['monthly_p95'][m]
    pct_med = med / CAPITAL * 100
    pct_p5  = p5  / CAPITAL * 100
    print(f"  {m+1:>5}  {med:>+13,.0f}€  {p5:>+9,.0f}€  {p95:>+9,.0f}€  "
          f"  {pct_med:>+8.1f}%  {pct_p5:>+6.1f}%")

# ── 3e: Confronto scenari OOS 2024/2025/2026 ─────────────────────────────────
print(f"\n  3e. OOS stability: performance 1h + ALPHA 5m per anno")
print()
print(f"  {'Anno':<6}  {'1h n':>5}  {'1h avg':>8}  {'1h WR':>7}  "
      f"{'ALPHA n':>7}  {'ALPHA avg':>10}  {'TRIPLO n':>8}  {'TRIPLO avg':>11}")
print("  " + "─" * 72)
for yr in [2024, 2025, 2026]:
    s1 = base1h[base1h['year'] == yr]
    sa = alpha_b6[alpha_b6['year'] == yr]
    st = triplo[triplo['year'] == yr]
    n1 = len(s1); na = len(sa); nt = len(st)
    a1   = f"{s1['pnl_r_adj'].mean():>+7.3f}R"  if n1 >= 3 else "   N/A "
    wr1  = f"{s1['win'].mean()*100:>5.1f}%"      if n1 >= 3 else "  N/A"
    aa   = f"{sa['pnl_r_adj'].mean():>+8.3f}R"  if na >= 3 else "    N/A "
    at   = f"{st['pnl_r_adj'].mean():>+9.3f}R"  if nt >= 3 else "     N/A "
    print(f"  {yr:<6}  {n1:>5}  {a1}  {wr1}  {na:>7}  {aa}   {nt:>8}  {at}")

# ── SUMMARY FINALE ────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("SINTESI DEFINITIVA — NUMERI FINALI DEL SISTEMA")
print(SEP)

opt = edge_results_opt[1.00]
s25 = edge_results_opt[0.25]
s50 = edge_results_opt[0.50]

print(f"""
  CONFIGURAZIONE PRODUZIONE (1h=1.5%, 5m=0.5%):
  ─────────────────────────────────────────────
  Trade/anno:   1h={lam_1h*12:.0f}  |  5m TRIPLO={lam_5m_final*12:.0f}  |  TOTALE={(lam_1h+lam_5m_final)*12:.0f}
  avg_r:        1h={r_1h.mean():+.4f}R  |  5m={r_5m_final.mean():+.4f}R

  EDGE 100% (attuale):
    Mediana 12m:  {fmt_eur(opt['median'])}  (+{opt['median']/CAPITAL*100:.1f}%)
    Worst 5%:     {fmt_eur(opt['p05'])}  ({opt['p05']/CAPITAL*100:.1f}%)
    Best 5%:      {fmt_eur(opt['p95'])}  (+{opt['p95']/CAPITAL*100:.1f}%)
    DD p95:       {opt['dd_p95']*100:.1f}% del picco
    ProbPositivo: {opt['prob_pos']*100:.1f}%

  EDGE 50% (edge dimezzato, stress test realistico):
    Mediana 12m:  {fmt_eur(s50['median'])}  ({s50['median']/CAPITAL*100:.1f}%)
    Worst 5%:     {fmt_eur(s50['p05'])}  ({s50['p05']/CAPITAL*100:.1f}%)
    DD p95:       {s50['dd_p95']*100:.1f}%
    ProbPositivo: {s50['prob_pos']*100:.1f}%

  EDGE 25% (quasi edge-free, safety floor):
    Mediana 12m:  {fmt_eur(s25['median'])}  ({s25['median']/CAPITAL*100:.1f}%)
    Worst 5%:     {fmt_eur(s25['p05'])}  ({s25['p05']/CAPITAL*100:.1f}%)
    DD p95:       {s25['dd_p95']*100:.1f}%
    ProbPositivo: {s25['prob_pos']*100:.1f}%

  SAFETY RULES DA IMPLEMENTARE:
    1. Stop mensile: -8% equity → pausa 1 settimana
    2. Stop settimanale: -4% → revisione segnali
    3. DD > 15% dal picco → ridurre risk a 0.5%/0.25% fino a recupero
    4. Paper trading: prime 4-6 settimane con metà risk (0.75%/0.25%)
""")

print(f"{SEP}")
print("DONE — final_mc_oos.py")
print(SEP)
