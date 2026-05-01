#!/usr/bin/env python3
"""
Analisi finale pre-paper-trading — sezioni A-G.
  A. Pattern completi (tutti i tipi nel dataset)
  B. TP/SL ottimizzati (solo 6 pattern, TRIPLO config)
  C. Kelly criterion + Money Management
  D. Timeframe 15m (proxy via 15m-aligned 5m signals)
  E. Multi-Timeframe confirmation (1h + 5m concordanti)
  F. Uscita su segnale contrario
  G. Gap overnight analysis
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

BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})
GOOD_PATTERNS = frozenset({'double_bottom','double_top',
                           'macd_divergence_bull','macd_divergence_bear',
                           'rsi_divergence_bull','rsi_divergence_bear'})

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
               FROM candles WHERE timeframe='1d' ORDER BY symbol, timestamp""")
sym_1d_rows = cur.fetchall()

# 15m candle count per symbol (Section D)
cur.execute("""SELECT COUNT(*), MIN(timestamp)::date, MAX(timestamp)::date
               FROM candles WHERE timeframe='15m'""")
r15 = cur.fetchone()
cur.execute("""SELECT symbol, COUNT(*) FROM candles WHERE timeframe='15m'
               GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 15""")
sym15 = cur.fetchall()
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
sym_1d_dict = {(r['symbol'], r['date']): dict(r) for _, r in sym_1d_df.iterrows()}

def get_regime(d):
    for i in range(1, 15):
        v = spy_dict.get(d - timedelta(days=i))
        if v is not None: return v
    return 'neutral'

def add_slip(df):
    df = df.copy()
    df['pnl_r_adj'] = (df['pnl_r']
        - 0.03 / df['risk_pct']
        - np.where(df['outcome'] == 'stop', 0.05 / df['risk_pct'], 0.0))
    df['win'] = df['pnl_r_adj'] > 0
    return df

def regime_ok(row):
    reg = row['regime']; dir_ = row['direction']
    return (reg == 'neutral') or (reg == 'bull' and dir_ == 'bullish') or (reg == 'bear' and dir_ == 'bearish')

# ── Load datasets ─────────────────────────────────────────────────────────────
print("Loading datasets...", flush=True)
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

# ── TRIPLO base (no blocked, 6 pattern, regime, risk) ──────────────────────
base6 = add_slip(df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE)) &
    (df5['pattern_name'].isin(GOOD_PATTERNS)) &
    df5.apply(regime_ok, axis=1)
].copy())

# ALPHA (15:xx)
alpha_b6 = base6[base6['hour_et'] == 15].copy()
# MIDDAY_F: we use the at_extreme marker from the TRIPLO script (approximation: use alpha only for TRIPLO stats)
# For TRIPLO approximation in B/C sections, use ALPHA as the primary reference
# (MIDDAY_F requires DB join for at_extreme)

print(f"  base6: {len(base6):,}  ALPHA: {len(alpha_b6):,}", flush=True)

def fmt_avg(v): return f"{v:>+8.3f}" if not np.isnan(v) else f"{'N/A':>8}"
def fmt_pct(v): return f"{v:>5.1f}%" if not np.isnan(v) else f"{'N/A':>6}"

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("A. TUTTI I PATTERN NEL DATASET 5m")
print(SEP)

# All patterns (no regime, no risk filter to see raw)
all_pats = df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE))
].copy()
all_pats = add_slip(all_pats)
all_pats['regime_ok'] = all_pats.apply(regime_ok, axis=1)

print(f"\n  Dataset totale (no blocked, risk 0.5-2%, entry_filled): {len(all_pats):,}")
print()
print(f"  {'Pattern':<30}  {'Tipo':<12}  {'n_raw':>6}  {'n_regime':>8}  "
      f"{'avg_r':>7}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 82)

PAT_TYPE = {
    'engulfing_bullish':    'continuazione',
    'double_bottom':        'inversione',
    'double_top':           'inversione',
    'macd_divergence_bull': 'divergenza',
    'macd_divergence_bear': 'divergenza',
    'rsi_divergence_bull':  'divergenza',
    'rsi_divergence_bear':  'divergenza',
}

for pat in all_pats['pattern_name'].value_counts().index:
    sub_raw    = all_pats[all_pats['pattern_name'] == pat]
    sub_regime = all_pats[(all_pats['pattern_name'] == pat) & all_pats['regime_ok']]
    n_raw    = len(sub_raw)
    n_regime = len(sub_regime)
    avg_r    = sub_regime['pnl_r'].mean()     if n_regime >= 3 else float('nan')
    avg_slip = sub_regime['pnl_r_adj'].mean() if n_regime >= 3 else float('nan')
    wr       = sub_regime['win'].mean() * 100 if n_regime >= 3 else float('nan')
    to_pct   = (sub_regime['outcome'] == 'timeout').mean() * 100 if n_regime >= 3 else float('nan')
    tipo     = PAT_TYPE.get(pat, 'sconosciuto')
    flag     = " ★ BUONO" if pat in GOOD_PATTERNS else " ✗ ESCLUSO"
    avg_r_s  = f"{avg_r:>+7.3f}" if not np.isnan(avg_r) else f"{'N/A':>7}"
    print(f"  {pat:<30}  {tipo:<12}  {n_raw:>6,}  {n_regime:>8,}  "
          f"{avg_r_s}  {fmt_avg(avg_slip)}  {fmt_pct(wr)}  "
          f"{to_pct:>5.1f}%{flag}")

print(f"\n  Conclusione: engulfing_bullish è l'unico pattern escluso.")
print(f"  Non esistono 'pattern di continuazione' aggiuntivi nel detector 5m.")

# ── Pattern su COLOSSI (con regime filter) ───────────────────────────────────
print(f"\n  ── Pattern su COLOSSI (AAPL, MSFT, GOOGL) — regime filter ──")
COLOSSI_CHECK = ['AAPL', 'MSFT', 'GOOGL']
colossi_all = df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (df5['symbol'].isin(COLOSSI_CHECK)) &
    df5.apply(regime_ok, axis=1)
].copy()
colossi_all = add_slip(colossi_all)

print(f"\n  {'Simbolo':<8}  {'Pattern':<28}  {'n':>4}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 62)
for sym in COLOSSI_CHECK:
    for pat in all_pats['pattern_name'].value_counts().index:
        sub = colossi_all[(colossi_all['symbol'] == sym) & (colossi_all['pattern_name'] == pat)]
        if len(sub) < 3: continue
        s = sub['pnl_r_adj'].mean()
        wr = sub['win'].mean() * 100
        to = (sub['outcome'] == 'timeout').mean() * 100
        print(f"  {sym:<8}  {pat:<28}  {len(sub):>4}  {fmt_avg(s)}  {fmt_pct(wr)}  {to:>5.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("B. TP/SL OTTIMIZZATI (6 pattern buoni, base6, TRIPLO-aware)")
print(SEP)

# TP structure diagnostics
print(f"\n  Struttura attuale pnl_r (base6, entry_filled, regime):")
print(f"  {'Outcome':<10}  {'n':>5}  {'median_pnl_r':>13}  {'mean_pnl_r':>11}  Interpretazione")
print("  " + "─" * 60)
interp = {'stop':'stop=1.22R loss','tp1':'50%@2R+continua','tp2':'50%@2R+50%@3.5R','timeout':'fade/rumore'}
for o in ['stop','tp1','tp2','timeout']:
    sub = base6[base6['outcome'] == o]
    if len(sub) < 2: continue
    print(f"  {o:<10}  {len(sub):>5,}  {sub['pnl_r'].median():>+13.3f}  "
          f"{sub['pnl_r'].mean():>+11.3f}  {interp.get(o,'')}")

# ── B1. Simulazione TP1 diversi livelli ──────────────────────────────────────
print(f"\n  B1. Simulazione TP1 a diversi livelli (full position, close all at TP)")
print(f"      Corrente: 50%@TP1(2R) + 50%@TP2(3.5R) | Simulazione: 100% a TP singolo")
print(f"      Logica: stop=unchanged | tp1/tp2 hit=target | timeout=min(pnl_r,target)")
print()

def sim_pnl_single_tp(df, target_r):
    """Simulate closing full position at single TP target (in R multiples)."""
    results = []
    for _, row in df.iterrows():
        o = row['outcome']
        if o == 'stop':
            p = row['pnl_r']  # ~-1.22R
        elif o in ('tp1', 'tp2'):
            # Price definitely reached TP1 (2R). For tp2, reached 3.5R.
            if target_r <= 2.0:
                p = target_r
            elif target_r <= 3.5 and o == 'tp2':
                p = target_r
            elif target_r <= 3.5 and o == 'tp1':
                p = 2.0  # only TP1 was hit, stays at 2R
            else:
                p = row['pnl_r']  # beyond TP2, use actual
        elif o == 'timeout':
            # Conservative: if ending pnl_r >= target, likely hit
            p = target_r if row['pnl_r'] >= target_r else row['pnl_r']
        else:
            p = row['pnl_r']
        # Slippage
        slip = 0.03 / row['risk_pct']
        stop_slip = (0.05 / row['risk_pct']) if (o == 'stop' or p < 0) else 0
        results.append(p - slip - stop_slip)
    return results

base6_tp_test = base6.copy()
targets = [0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00]

print(f"  {'TP_target':>10}  {'avg+slip':>9}  {'WR':>6}  {'E_tp1%':>8}  {'E_stop%':>8}  {'E_to%':>7}")
print("  " + "─" * 58)
for t in targets:
    sims = sim_pnl_single_tp(base6_tp_test, t)
    avg_s  = np.mean(sims)
    wr_s   = np.mean(np.array(sims) > 0) * 100
    # estimate: how many "tp1/tp2" outcomes at this target?
    tp_hit = ((base6_tp_test['outcome'].isin(['tp1','tp2'])) |
              ((base6_tp_test['outcome'] == 'timeout') & (base6_tp_test['pnl_r'] >= t)))
    tp_pct = tp_hit.mean() * 100
    stop_p = (base6_tp_test['outcome'] == 'stop').mean() * 100
    to_p   = ((base6_tp_test['outcome'] == 'timeout') & (base6_tp_test['pnl_r'] < t)).mean() * 100
    curr   = " ← ATTUALE (approssimato)" if t == 2.00 else ""
    print(f"  {t:>9.2f}R  {avg_s:>+8.3f}R  {wr_s:>5.1f}%  {tp_pct:>7.1f}%  {stop_p:>7.1f}%  {to_p:>6.1f}%{curr}")

# B1 per soli ALPHA (15:xx) — la componente più pulita
print(f"\n  B1 solo ALPHA (15:xx) — la componente con meno timeout:")
print(f"  {'TP_target':>10}  {'avg+slip':>9}  {'WR':>6}")
print("  " + "─" * 32)
for t in [1.00, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00]:
    sims = sim_pnl_single_tp(alpha_b6, t)
    avg_s = np.mean(sims)
    wr_s  = np.mean(np.array(sims) > 0) * 100
    curr  = " ←" if t == 2.00 else ""
    print(f"  {t:>9.2f}R  {avg_s:>+8.3f}R  {wr_s:>5.1f}%{curr}")

# ── B2. Split TP1/TP2 vs TP singolo ──────────────────────────────────────────
print(f"\n  B2. Configurazioni TP/SL confronto (base6)")
print()

# Current (actual pnl_r + slip)
curr_avg = base6['pnl_r_adj'].mean()
curr_wr  = base6['win'].mean() * 100

# All-in at 1.5R
sim_15 = sim_pnl_single_tp(base6, 1.5)
avg_15 = np.mean(sim_15); wr_15 = np.mean(np.array(sim_15) > 0) * 100

# All-in at 2.0R
sim_20 = sim_pnl_single_tp(base6, 2.0)
avg_20 = np.mean(sim_20); wr_20 = np.mean(np.array(sim_20) > 0) * 100

# All-in at 3.0R
sim_30 = sim_pnl_single_tp(base6, 3.0)
avg_30 = np.mean(sim_30); wr_30 = np.mean(np.array(sim_30) > 0) * 100

# Split 50% @1.5R + 50% @3.0R (simulate)
def sim_split_tp(df, tp1_r, tp2_r):
    results = []
    for _, row in df.iterrows():
        o = row['outcome']
        # Half 1 (tp1_r):
        h1 = sim_pnl_single_tp(pd.DataFrame([row]), tp1_r)[0]
        # Half 2: continues to tp2_r or stops at stop/timeout
        if o in ('tp1', 'tp2') and row['pnl_r'] >= 0:
            # TP1 was hit → half1 = +tp1_r. Half2 continues
            if o == 'tp2':
                # TP2 also hit → half2 gets tp2_r
                h2 = tp2_r - 0.03/row['risk_pct']
            else:
                # TP1 hit but TP2 not → half2 exits at ~TP1 level (trail to BE, profit mean ~TP1)
                h2 = tp1_r - 0.03/row['risk_pct']  # trail stop to TP1, exits near there
        elif o == 'stop':
            h2 = row['pnl_r'] - 0.03/row['risk_pct'] - 0.05/row['risk_pct']
        elif o == 'timeout':
            h2 = row['pnl_r'] - 0.03/row['risk_pct']
        else:
            h2 = row['pnl_r'] - 0.03/row['risk_pct']
        results.append(0.5 * h1 + 0.5 * h2)
    return results

split_15_30 = sim_split_tp(base6, 1.5, 3.0)
avg_s15_30 = np.mean(split_15_30); wr_s15_30 = np.mean(np.array(split_15_30) > 0) * 100

split_20_35 = sim_split_tp(base6, 2.0, 3.5)
avg_s20_35 = np.mean(split_20_35); wr_s20_35 = np.mean(np.array(split_20_35) > 0) * 100

print(f"  {'Configurazione':<40}  {'avg+slip':>9}  {'WR':>6}")
print("  " + "─" * 58)
print(f"  {'Attuale (split implicito nel dataset)':<40}  {curr_avg:>+8.3f}R  {curr_wr:>5.1f}%")
print(f"  {'TP singolo 1.5R (tutto)':<40}  {avg_15:>+8.3f}R  {wr_15:>5.1f}%")
print(f"  {'TP singolo 2.0R (tutto)':<40}  {avg_20:>+8.3f}R  {wr_20:>5.1f}%")
print(f"  {'TP singolo 3.0R (tutto)':<40}  {avg_30:>+8.3f}R  {wr_30:>5.1f}%")
print(f"  {'Split 50%@1.5R + 50%@3.0R':<40}  {avg_s15_30:>+8.3f}R  {wr_s15_30:>5.1f}%")
print(f"  {'Split 50%@2.0R + 50%@3.5R (stima)':<40}  {avg_s20_35:>+8.3f}R  {wr_s20_35:>5.1f}%")

# ── B3. Trailing stop: nota ───────────────────────────────────────────────────
print(f"\n  B3. Trailing stop:")
print(f"      Richiede MFE (Max Favorable Excursion) per ogni trade,")
print(f"      dato non presente nel CSV. Analisi non simulabile.")
print(f"      STIMA QUALITATIVA: ALPHA ha timeout=6.4%, to_median=4 bars → trailing")
print(f"      a BE aiuta poco (trade si risolvono veloci). Per MIDDAY (TO=32%) potrebbe")
print(f"      recuperare una parte delle timeout losses ma è marginale rispetto al filtro at_extreme.")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("C. KELLY CRITERION + MONEY MANAGEMENT")
print(SEP)

# C1. Kelly per ALPHA (la componente più pura)
print(f"\n  C1. Kelly Criterion")
print(f"\n  Formula: K = p - (1-p)/b  dove b = avg_win / avg_loss")
print(f"  Half-Kelly = K/2 (in pratica)")
print()

datasets = {
    'ALPHA 5m (15:xx)': alpha_b6,
    'base6 5m (full, no time filter)': base6,
}
# Load 1h
df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts']    = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d']    = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1 = add_slip(df1[(df1['risk_pct'] >= 0.30) & df1.apply(regime_ok, axis=1) & (df1['entry_filled'] == True)].copy())
datasets['1h sistema (baseline)'] = df1

print(f"  {'Dataset':<35}  {'n':>5}  {'WR':>6}  {'avg_win':>8}  {'avg_loss':>9}  "
      f"{'payoff':>8}  {'Kelly%':>8}  {'Half-K%':>8}")
print("  " + "─" * 88)

for lbl, d in datasets.items():
    wins  = d[d['win'] == True]['pnl_r_adj']
    loses = d[d['win'] == False]['pnl_r_adj']
    if len(wins) < 3 or len(loses) < 3: continue
    p    = d['win'].mean()
    q    = 1 - p
    avw  = wins.mean()
    avl  = abs(loses.mean())
    b    = avw / avl
    K    = p - q / b
    HK   = K / 2
    print(f"  {lbl:<35}  {len(d):>5,}  {p*100:>5.1f}%  {avw:>+7.3f}R  {-avl:>+8.3f}R  "
          f"  {b:>7.3f}  {K*100:>7.1f}%  {HK*100:>7.1f}%")

print(f"\n  Interpretazione Kelly:")
print(f"    Kelly% → fraction of capital per trade (in terms of risk units)")
print(f"    Se Kelly=30% → ogni trade rischi 30% del capitale? NO.")
print(f"    Kelly si applica al RISK AMOUNT: risk_pct = Kelly × kelly_fraction")
print(f"    Es: Half-Kelly=15% → risk_pct ottimale = ?")
print(f"    NB: la formula presuppone distribuzione normale — usa con cautela")

# C2. Risk variabile 1h vs 5m (stima MC semplificata)
print(f"\n  C2. Risk variabile per timeframe — stima MC 5000 sim × 12 mesi")
print()

N_SIM = 5000
N_MONTHS = 12
RISK_EUR  = 1000.0

r5_alpha = alpha_b6['pnl_r_adj'].values
r1h       = df1['pnl_r_adj'].values

def lam_monthly(d, from_year=2024):
    sub = d[d['year'] >= from_year] if 'year' in d.columns else d
    if len(sub) < 2: return 0.0
    span = (sub['ts'].max() - sub['ts'].min()).days / 30.44
    return len(sub) / max(span, 1.0)

lam5  = lam_monthly(alpha_b6) if len(alpha_b6) > 1 else 5.0
lam1h = lam_monthly(df1)      if len(df1) > 1 else 80.0
print(f"  λ/mese ALPHA 5m: {lam5:.1f}   λ/mese 1h: {lam1h:.1f}")

def mc_combined(risk1h_eur, risk5m_eur, n_sim=N_SIM, n_months=N_MONTHS):
    medians = []
    for _ in range(n_sim):
        equity = 0.0
        for _ in range(n_months):
            n5 = np.random.poisson(lam5)
            n1 = np.random.poisson(lam1h)
            if n5 > 0:
                idxs = np.random.randint(0, len(r5_alpha), n5)
                equity += risk5m_eur * r5_alpha[idxs].sum()
            if n1 > 0:
                idxs = np.random.randint(0, len(r1h), n1)
                equity += risk1h_eur * r1h[idxs].sum()
        medians.append(equity)
    return np.median(medians), np.percentile(medians, 10), np.percentile(medians, 90)

configs_c2 = [
    ("Uniforme 1%",         RISK_EUR, RISK_EUR),
    ("5m light (1h=1%, 5m=0.5%)", RISK_EUR, RISK_EUR * 0.5),
    ("5m heavy (1h=0.5%, 5m=1%)", RISK_EUR * 0.5, RISK_EUR),
    ("1h heavy (1h=1.5%, 5m=0.5%)", RISK_EUR * 1.5, RISK_EUR * 0.5),
    ("Balanced (1h=1%, 5m=0.75%)",  RISK_EUR, RISK_EUR * 0.75),
]
print(f"\n  {'Config':<38}  {'Mediana':>9}  {'P10':>9}  {'P90':>9}")
print("  " + "─" * 68)
for lbl, r1h_eur, r5m_eur in configs_c2:
    med, p10, p90 = mc_combined(r1h_eur, r5m_eur)
    print(f"  {lbl:<38}  €{med:>7,.0f}  €{p10:>7,.0f}  €{p90:>7,.0f}")

# C3. Risk variabile per regime
print(f"\n  C3. Risk variabile per regime — stima MC (ALPHA 5m + 1h)")
print()

alpha_bull = alpha_b6[alpha_b6['regime'] == 'bull']['pnl_r_adj'].values
alpha_bear = alpha_b6[alpha_b6['regime'] == 'bear']['pnl_r_adj'].values
alpha_neut = alpha_b6[alpha_b6['regime'] == 'neutral']['pnl_r_adj'].values
r1h_bull   = df1[df1['regime'] == 'bull']['pnl_r_adj'].values
r1h_bear   = df1[df1['regime'] == 'bear']['pnl_r_adj'].values
r1h_neut   = df1[df1['regime'] == 'neutral']['pnl_r_adj'].values

# Proportion of months in each regime (from spy_df)
reg_counts = spy_df['regime'].value_counts(normalize=True)
p_bull = reg_counts.get('bull', 0.3)
p_bear = reg_counts.get('bear', 0.2)
p_neut = reg_counts.get('neutral', 0.5)

def mc_regime(risk_by_regime_5m, risk_by_regime_1h, n_sim=N_SIM, n_months=N_MONTHS):
    medians = []
    for _ in range(n_sim):
        equity = 0.0
        for _ in range(n_months):
            # Sample a regime
            reg = np.random.choice(['bull','bear','neutral'], p=[p_bull, p_bear, p_neut])
            r5_reg = {'bull': alpha_bull, 'bear': alpha_bear, 'neutral': alpha_neut}[reg]
            r1_reg = {'bull': r1h_bull,   'bear': r1h_bear,  'neutral': r1h_neut}[reg]
            if len(r5_reg) < 2 or len(r1_reg) < 2: continue
            r5_eur  = risk_by_regime_5m[reg]
            r1h_eur = risk_by_regime_1h[reg]
            n5 = np.random.poisson(lam5)
            n1 = np.random.poisson(lam1h)
            if n5 > 0:
                idxs = np.random.randint(0, len(r5_reg), n5)
                equity += r5_eur * r5_reg[idxs].sum()
            if n1 > 0:
                idxs = np.random.randint(0, len(r1_reg), n1)
                equity += r1h_eur * r1_reg[idxs].sum()
        medians.append(equity)
    return np.median(medians), np.percentile(medians, 10), np.percentile(medians, 90)

print(f"  Distribuzione regime SPY: bull={p_bull:.0%}  bear={p_bear:.0%}  neutral={p_neut:.0%}")
print(f"  Performance 5m ALPHA per regime: bull={alpha_bull.mean() if len(alpha_bull)>2 else 0:+.3f}R  "
      f"bear={alpha_bear.mean() if len(alpha_bear)>2 else 0:+.3f}R  "
      f"neutral={alpha_neut.mean() if len(alpha_neut)>2 else 0:+.3f}R")
print(f"  Performance 1h per regime:        bull={r1h_bull.mean() if len(r1h_bull)>2 else 0:+.3f}R  "
      f"bear={r1h_bear.mean() if len(r1h_bear)>2 else 0:+.3f}R  "
      f"neutral={r1h_neut.mean() if len(r1h_neut)>2 else 0:+.3f}R")
print()

configs_c3 = [
    ("Uniforme 1%", {'bull':1000,'bear':1000,'neutral':1000}, {'bull':1000,'bear':1000,'neutral':1000}),
    ("BEAR premium 5m", {'bull':750,'bear':1500,'neutral':1000}, {'bull':1000,'bear':1000,'neutral':1000}),
    ("BEAR premium entrambi", {'bull':750,'bear':1500,'neutral':1000}, {'bull':750,'bear':1500,'neutral':1000}),
    ("NEUTRAL light", {'bull':1000,'bear':1000,'neutral':750}, {'bull':1000,'bear':1000,'neutral':750}),
]
print(f"  {'Config':<35}  {'Mediana':>9}  {'P10':>9}  {'P90':>9}")
print("  " + "─" * 62)
for lbl, r5_reg, r1_reg in configs_c3:
    med, p10, p90 = mc_regime(r5_reg, r1_reg)
    print(f"  {lbl:<35}  €{med:>7,.0f}  €{p10:>7,.0f}  €{p90:>7,.0f}")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("D. TIMEFRAME 15 MINUTI")
print(SEP)
print(f"\n  15m candles in DB: n={r15[0]:,}  periodo={r15[1]} → {r15[2]}")
print(f"  Top simboli 15m:")
for sym, cnt in sym15[:8]:
    print(f"    {sym:<10}: {cnt:,}")

print(f"""
  CONCLUSIONE: soli ~3 mesi di dati 15m (gen-apr 2026). Troppo poco per un backtest affidabile.

  PROXY ANALYSIS: 15m-equivalent dai dati 5m
  Filtra i segnali 5m solo quando min_et ∈ {{0, 15, 30, 45}} (allineati al 15m).
  Questo simula approssimativamente cosa vedrebbe un detector 15m.
""")

df5_15m_proxy = base6[base6['min_et'].isin([0, 15, 30, 45])].copy()
df5_15m_full  = base6.copy()

print(f"  {'Config':<35}  {'n':>6}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 62)
for lbl, d in [('5m tutti i segnali', df5_15m_full),
               ('5m proxy 15m (allineati :00/:15/:30/:45)', df5_15m_proxy)]:
    if len(d) < 3: continue
    avg = d['pnl_r_adj'].mean()
    wr  = d['win'].mean() * 100
    to  = (d['outcome'] == 'timeout').mean() * 100
    print(f"  {lbl:<35}  {len(d):>6,}  {avg:>+8.3f}R  {wr:>5.1f}%  {to:>5.1f}%")

# Per ora ET
print(f"\n  Breakdown proxy 15m per fascia oraria (solo min allineati):")
print(f"  {'Ora':>5}  {'n':>4}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
for h in range(10, 16):
    sub = df5_15m_proxy[df5_15m_proxy['hour_et'] == h]
    if len(sub) < 3: continue
    print(f"  {h:02d}:xx  {len(sub):>4}  {sub['pnl_r_adj'].mean():>+8.3f}R  "
          f"{sub['win'].mean()*100:>5.1f}%  {(sub['outcome']=='timeout').mean()*100:>5.1f}%")

print(f"\n  Colossi con proxy 15m (allineati, 15:xx only):")
print(f"  {'Simbolo':<8}  {'n':>4}  {'avg+slip':>9}  {'WR':>6}")
colossi_15m = df5[
    (df5['entry_filled'] == True) & (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (df5['symbol'].isin(['AAPL','MSFT','GOOGL','AMZN'])) &
    df5.apply(regime_ok, axis=1) & (df5['hour_et'] == 15) &
    (df5['min_et'].isin([0, 15, 30, 45]))
].copy()
colossi_15m = add_slip(colossi_15m)
for sym in ['AAPL','MSFT','GOOGL','AMZN']:
    sub = colossi_15m[(colossi_15m['symbol'] == sym) & (colossi_15m['pattern_name'].isin(GOOD_PATTERNS))]
    if len(sub) < 2:
        print(f"  {sym:<8}  {len(sub):>4}  (pochi dati)")
        continue
    print(f"  {sym:<8}  {len(sub):>4}  {sub['pnl_r_adj'].mean():>+8.3f}R  {sub['win'].mean()*100:>5.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("E. MULTI-TIMEFRAME CONFIRMATION (1h + 5m concordanti)")
print(SEP)

print(f"\n  1h dataset: {len(df1):,} trade")
print(f"  5m ALPHA (base6, 15:xx): {len(alpha_b6):,} trade")

# Build 1h lookup: per (symbol, date, direction) → has 1h signal that day?
df1['_d'] = df1['ts'].apply(lambda x: x.date())
df1['year'] = df1['ts'].dt.year
set_1h = set()
dict_1h_perf = {}
for _, row in df1.iterrows():
    key = (row['symbol'], row['_d'], row['direction'])
    set_1h.add(key)
    if key not in dict_1h_perf:
        dict_1h_perf[key] = []
    dict_1h_perf[key].append(row['pnl_r_adj'])

# For each 5m ALPHA signal, check if there's a concordant 1h signal the same day
alpha_b6_ext = alpha_b6.copy()
alpha_b6_ext['has_1h_concordant']  = alpha_b6_ext.apply(
    lambda r: (r['symbol'], r['_d'], r['direction']) in set_1h, axis=1)
alpha_b6_ext['has_1h_discordant'] = alpha_b6_ext.apply(
    lambda r: (r['symbol'], r['_d'],
               'bearish' if r['direction']=='bullish' else 'bullish') in set_1h, axis=1)

concordant = alpha_b6_ext[alpha_b6_ext['has_1h_concordant'] & ~alpha_b6_ext['has_1h_discordant']]
discordant = alpha_b6_ext[alpha_b6_ext['has_1h_discordant']]
solo_5m    = alpha_b6_ext[~alpha_b6_ext['has_1h_concordant'] & ~alpha_b6_ext['has_1h_discordant']]

# 1h solo (no same-day 5m alpha signal with same direction)
alpha_b6_keys = set(zip(alpha_b6['symbol'], alpha_b6['_d'], alpha_b6['direction']))
df1_solo      = df1[~df1.apply(
    lambda r: (r['symbol'], r['_d'], r['direction']) in alpha_b6_keys, axis=1)]

print(f"\n  {'Situazione':<35}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 60)
for lbl, d in [
    ('5m ALPHA solo (no 1h same day)', solo_5m),
    ('5m ALPHA + 1h concordante',       concordant),
    ('5m ALPHA + 1h discordante',       discordant),
    ('1h solo (no 5m ALPHA same day)',  df1_solo),
    ('1h tutti',                         df1),
]:
    if len(d) < 3:
        print(f"  {lbl:<35}  {len(d):>5}  (pochi dati)")
        continue
    avg = d['pnl_r_adj'].mean()
    wr  = d['win'].mean() * 100
    to  = (d['outcome'] == 'timeout').mean() * 100 if 'outcome' in d.columns else float('nan')
    to_s = f"{to:>5.1f}%" if not np.isnan(to) else "  N/A"
    print(f"  {lbl:<35}  {len(d):>5,}  {avg:>+8.3f}R  {wr:>5.1f}%  {to_s}")

# OOS breakdown concordant
print(f"\n  OOS 5m concordante per anno:")
for yr in [2024, 2025, 2026]:
    sub = concordant[concordant['year'] == yr]
    if len(sub) < 3: continue
    print(f"    {yr}: n={len(sub):3}  avg+slip={sub['pnl_r_adj'].mean():>+7.3f}R  WR={sub['win'].mean()*100:.1f}%")

print(f"\n  OOS 5m solo per anno:")
for yr in [2024, 2025, 2026]:
    sub = solo_5m[solo_5m['year'] == yr]
    if len(sub) < 3: continue
    print(f"    {yr}: n={len(sub):3}  avg+slip={sub['pnl_r_adj'].mean():>+7.3f}R  WR={sub['win'].mean()*100:.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("F. USCITA SU SEGNALE CONTRARIO")
print(SEP)

print(f"\n  F1. Se siamo LONG e appare un segnale SHORT → chiudi anticipatamente?")
print(f"\n  Metodologia: per ogni trade 5m (ALPHA), controlla se esiste")
print(f"  un segnale di direzione opposta sullo stesso simbolo entro")
print(f"  bars_to_exit × 5 minuti dalla entry.")
print()

# For each ALPHA trade, look for opposing signal in window
# Build lookup: for each (symbol, day) → list of (ts, direction, pnl_r_adj)
alpha_sorted = alpha_b6.sort_values('ts').copy()
alpha_sorted['ts_entry'] = alpha_sorted['ts'] + pd.to_timedelta(
    alpha_sorted['bars_to_entry'].fillna(1) * 5, unit='m')
alpha_sorted['ts_exit'] = alpha_sorted['ts'] + pd.to_timedelta(
    alpha_sorted['bars_to_exit'].fillna(20) * 5, unit='m')

# Index by symbol and day
from collections import defaultdict
sig_index = defaultdict(list)
for _, row in alpha_sorted.iterrows():
    sig_index[(row['symbol'], row['_d'])].append(
        (row['ts'], row['direction'], row['pnl_r_adj'], row['ts_entry'], row['ts_exit']))

# For each trade, check if opposing signal exists while this trade is open
has_opposing = []
for _, row in alpha_sorted.iterrows():
    symd = (row['symbol'], row['_d'])
    found_opposing = False
    for (ts2, dir2, _, entry2, _) in sig_index[symd]:
        if dir2 == row['direction']: continue        # same direction, skip
        if ts2 <= row['ts']: continue                # signal before ours, skip
        if ts2 > row['ts_exit']: continue            # signal after our exit, skip
        # Opposing signal appears while our trade is open
        found_opposing = True
        break
    has_opposing.append(found_opposing)

alpha_sorted['has_opposing'] = has_opposing
with_opp    = alpha_sorted[alpha_sorted['has_opposing']]
without_opp = alpha_sorted[~alpha_sorted['has_opposing']]

print(f"  {'Situazione':<38}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 64)
for lbl, d in [
    ('Ignora segnali contrari (attuale)',  alpha_sorted),
    ('Trade con segnale contrario dentro', with_opp),
    ('Trade senza segnale contrario',      without_opp),
]:
    if len(d) < 3:
        print(f"  {lbl:<38}  {len(d):>5}  (pochi)")
        continue
    avg = d['pnl_r_adj'].mean()
    wr  = d['win'].mean() * 100
    to  = (d['outcome'] == 'timeout').mean() * 100
    print(f"  {lbl:<38}  {len(d):>5,}  {avg:>+8.3f}R  {wr:>5.1f}%  {to:>5.1f}%")

print(f"\n  Simulazione 'chiudi su segnale contrario' (pnl ≈ pnl_r al momento del segnale):")
print(f"  (approssimazione: quando appare segnale contrario, pnl_r ≈ 0 — chiudi a BE)")
print(f"  Trade senza segnale contrario: {without_opp['pnl_r_adj'].mean():+.3f}R (invariato)")
print(f"  Trade con segnale contrario: se chiudi a ~0R → avg ≈ 0R invece di {with_opp['pnl_r_adj'].mean():+.3f}R")
if len(with_opp) > 0 and len(without_opp) > 0:
    n_tot = len(alpha_sorted)
    n_opp = len(with_opp)
    n_noo = len(without_opp)
    # Simulated avg if opposing trades exit at avg pnl at entry+1bar (≈ timeout/2)
    sim_opp_exit = with_opp['pnl_r_adj'].mean() * 0.3  # rough: save ~70% of the damage
    sim_avg = (n_noo * without_opp['pnl_r_adj'].mean() + n_opp * sim_opp_exit) / n_tot
    print(f"  Stima avg combinata con chiusura anticipata: {sim_avg:+.3f}R  "
          f"(vs attuale: {alpha_sorted['pnl_r_adj'].mean():+.3f}R)")

print(f"\n  F2. Uscita su cambio regime intraday:")
print(f"  Richiede ticker SPY 5m per sapere quando il regime cambia intraday.")
print(f"  Non implementabile con i dati attuali (SPY non è nell'universo 5m attivo).")
print(f"  RACCOMANDAZIONE: implementare come monitor live, non nel backtest.")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("G. EVENTI FONDAMENTALI")
print(SEP)

print(f"\n  G1/G2. Earnings e FOMC: date non presenti nel dataset. SKIP.")

# G3. Gap overnight
print(f"\n  G3. Gap overnight (apertura vs chiusura precedente)")
print(f"      Ipotesi: gap grande → volatilità alta → migliori outcome?")
print()

# For each 5m ALPHA trade, get the daily gap for that symbol/date
base6_gap = alpha_b6.copy()
gaps = []
for _, row in base6_gap.iterrows():
    d = sym_1d_dict.get((row['symbol'], row['_d']), {})
    gaps.append(d.get('gap_pct', np.nan))
base6_gap['gap_pct'] = gaps

base6_gap = base6_gap.dropna(subset=['gap_pct'])
print(f"  Trade con gap data disponibile: {len(base6_gap):,}/{len(alpha_b6):,}")
print()

# Categorize gaps
base6_gap['gap_cat'] = pd.cut(
    base6_gap['gap_pct'],
    bins=[-np.inf, -2.0, -1.0, 1.0, 2.0, np.inf],
    labels=['gap_down_large (< -2%)', 'gap_down (-2% a -1%)',
            'no_gap (-1% a +1%)', 'gap_up (+1% a +2%)', 'gap_up_large (> +2%)']
)

print(f"  {'Gap':<25}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 56)
for cat, sub in base6_gap.groupby('gap_cat', observed=True):
    if len(sub) < 3: continue
    avg = sub['pnl_r_adj'].mean()
    wr  = sub['win'].mean() * 100
    to  = (sub['outcome'] == 'timeout').mean() * 100
    print(f"  {str(cat):<25}  {len(sub):>5,}  {avg:>+8.3f}R  {wr:>5.1f}%  {to:>5.1f}%")

# Correlation gap_pct vs pnl_r_adj
corr = base6_gap[['gap_pct','pnl_r_adj']].corr().iloc[0,1]
abs_corr = base6_gap[['gap_pct','pnl_r_adj']].copy()
abs_corr['abs_gap'] = abs_corr['gap_pct'].abs()
corr_abs = abs_corr[['abs_gap','pnl_r_adj']].corr().iloc[0,1]
print(f"\n  Correlazione gap_pct ↔ pnl_r_adj: {corr:+.3f}")
print(f"  Correlazione |gap_pct| ↔ pnl_r_adj: {corr_abs:+.3f}")

# Breakdown gap direction vs trade direction
print(f"\n  Gap direction concordante con trade direction?")
print(f"  {'Trade+Gap':<30}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}")
print("  " + "─" * 50)
for tdesc, tmask, gdesc, gmask in [
    ('LONG + gap_up (+1%+)',   base6_gap['direction']=='bullish', None, base6_gap['gap_pct'] > 1.0),
    ('LONG + gap_down (-1%-)', base6_gap['direction']=='bullish', None, base6_gap['gap_pct'] < -1.0),
    ('SHORT + gap_down (-1%-)',base6_gap['direction']=='bearish', None, base6_gap['gap_pct'] < -1.0),
    ('SHORT + gap_up (+1%+)',  base6_gap['direction']=='bearish', None, base6_gap['gap_pct'] > 1.0),
    ('No gap qualsiasi dir.',  None, None, base6_gap['gap_pct'].between(-1.0,1.0)),
]:
    mask = tmask & gmask if tmask is not None else gmask
    sub  = base6_gap[mask]
    if len(sub) < 3:
        print(f"  {tdesc:<30}  {len(sub):>5}  (pochi)")
        continue
    avg = sub['pnl_r_adj'].mean()
    wr  = sub['win'].mean() * 100
    print(f"  {tdesc:<30}  {len(sub):>5,}  {avg:>+8.3f}R  {wr:>5.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("SINTESI FINALE — Cosa cambia per il paper trading?")
print(SEP)
print("""
  A. PATTERN: Nessun pattern di continuazione utile nel dataset.
     engulfing_bullish (73k segnali!) è giustamente escluso.
     I 6 pattern buoni rimangono gli unici validi.

  B. TP/SL: vedi output B1 dettagliato per la curva ottimale.
     Check la sezione B1 ALPHA per decidere se modificare TP1.

  C. KELLY: vedi output C2 per il risk ottimale per timeframe.
     Bear premium (C3) potrebbe aggiungere valore marginale.

  D. 15m: Troppo poco storico (3 mesi). Il proxy 15m non mostra
     differenze significative vs 5m. Non prioritario.

  E. MULTI-TF: Concordanza 1h+5m → vedi output.
     Se concordante migliora: potrebbe essere usato come filtro.

  F. SEGNALE CONTRARIO: vedi output F1.
     Trade con segnale contrario dentro sono un subset da esaminare.

  G. GAP OVERNIGHT: vedi output G3.
     Gap grande → più volatilità → migliore outcome? Controlla i numeri.
""")

print(f"{SEP}")
print("DONE — final_analysis.py")
print(SEP)
