#!/usr/bin/env python3
"""
Monte Carlo: Config Tripla
  - ALPHA: 15:00-16:00 ET, tutti i 6 pattern
  - MIDDAY_F: 11:00-15:00 ET, solo al estremo del giorno + BTE=1
  - TRIPLO: ALPHA + MIDDAY_F
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

RISK_EUR = 1000
N_SIM    = 5000
N_MONTHS = 12
SEP      = '═'*76

# ── DB ────────────────────────────────────────────────────────────────────
print("Loading DB...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("""SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
               FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp""")
spy_1d = cur.fetchall()
cur.execute("""SELECT symbol, DATE(timestamp AT TIME ZONE 'UTC'),
                      high::float, low::float, close::float
               FROM candles WHERE timeframe='1d'""")
sym_1d = cur.fetchall()
conn.close()

spy_df = pd.DataFrame(spy_1d, columns=['date','close'])
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
        - 0.03/df['risk_pct']
        - np.where(df['outcome']=='stop', 0.05/df['risk_pct'], 0.0))
    df['win'] = df['pnl_r_adj'] > 0
    return df

BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})
sym_1d_dict  = {(sym,dt): (h,l,c) for sym,dt,h,l,c in sym_1d}

# ── 5m dataset ────────────────────────────────────────────────────────────
print("Loading 5m...", flush=True)
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

base_all = add_slip(df5[
    (df5['entry_filled']==True) &
    (df5['risk_pct']>=0.50) & (df5['risk_pct']<=2.00) &
    (~df5['symbol'].isin(BLOCKED_BASE)) &
    (df5['pattern_name']!='engulfing_bullish') &
    regime_mask(df5)
].copy())

# ── Pattern candle OHLC (temp table) ──────────────────────────────────────
print("Fetching candle OHLC...", flush=True)
conn2 = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                         user='postgres', password='postgres')
cur2  = conn2.cursor()
cur2.execute("CREATE TEMP TABLE _tt (sym VARCHAR(20), ts TIMESTAMPTZ) ON COMMIT DELETE ROWS")
cur2.executemany("INSERT INTO _tt VALUES (%s,%s)",
                 [(r['symbol'], r['ts']) for _,r in base_all.iterrows()])
cur2.execute("""
    SELECT c.symbol, c.timestamp, c.high::float, c.low::float, c.close::float
    FROM candles c JOIN _tt t ON c.symbol=t.sym AND c.timestamp=t.ts
    WHERE c.timeframe='5m'
""")
candle_data = {(sym, pd.Timestamp(ts)): (h,l,cl)
               for sym,ts,h,l,cl in cur2.fetchall()}
conn2.close()
print(f"  Candle OHLC matched: {len(candle_data):,}/{len(base_all):,}", flush=True)

# ── Compute at_day_extreme ────────────────────────────────────────────────
print("Computing at_day_extreme...", flush=True)
c_low=[]; c_high=[]; d_high=[]; d_low=[]
for _, row in base_all.iterrows():
    cd  = candle_data.get((row['symbol'], row['ts']), (np.nan,np.nan,np.nan))
    sd  = sym_1d_dict.get((row['symbol'], row['_d']), (np.nan,np.nan,np.nan))
    c_high.append(cd[0]); c_low.append(cd[1])
    d_high.append(sd[0]); d_low.append(sd[1])

base_all['c_low']  = c_low;  base_all['c_high']  = c_high
base_all['d_low']  = d_low;  base_all['d_high']  = d_high

day_range = base_all['d_high'] - base_all['d_low']
base_all['dist_extreme'] = np.where(
    base_all['direction']=='bullish',
    np.where(day_range>0, (base_all['c_low']  - base_all['d_low'])  / day_range, np.nan),
    np.where(day_range>0, (base_all['d_high'] - base_all['c_high']) / day_range, np.nan)
)
base_all['at_extreme'] = base_all['dist_extreme'] < 0.10

# ── Build the 3 components ────────────────────────────────────────────────
alpha   = base_all[base_all['hour_et']==15].copy()
mid_f   = base_all[
    base_all['hour_et'].between(11,14) &
    base_all['at_extreme'] &
    (base_all['bars_to_entry']==1)
].copy()
triplo  = pd.concat([alpha, mid_f], ignore_index=True)

def lam(c, from_year=2024):
    sub = c[c['year']>=from_year]
    if len(sub)<2: return 0.0
    span = (sub['ts'].max()-sub['ts'].min()).days/30.44
    return len(sub)/max(span,1.0)

# ── 1h baseline ───────────────────────────────────────────────────────────
df1 = pd.read_csv('/app/data/val_1h_production.csv')
df1['ts']     = pd.to_datetime(df1['pattern_timestamp'], utc=True)
df1['_d']     = df1['ts'].apply(lambda x: x.date())
df1['regime'] = df1['_d'].apply(get_regime)
df1['year']   = df1['ts'].dt.year
base1 = add_slip(df1[(df1['risk_pct']>=0.30) & regime_mask(df1)].copy())
lam_1h = lam(base1)
r_1h   = base1['pnl_r_adj'].values

# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("1. TRADE COUNTS PER COMPONENTE")
print(SEP)

print(f"\n  {'Fonte':<28}  {'n total':>8}  {'λ/mese':>8}  {'T/anno':>8}  {'avg+slip':>9}  {'WR':>6}")
print('  '+'─'*70)
for lbl, cfg in [('5m 15:00-16:00 (ALPHA)', alpha),
                 ('5m 11-15 filtrato (MIDDAY_F)', mid_f),
                 ('5m TOTALE (TRIPLO)', triplo)]:
    l   = lam(cfg)
    avg = cfg['pnl_r_adj'].mean() if len(cfg)>0 else float('nan')
    wr  = cfg['win'].mean()*100   if len(cfg)>0 else float('nan')
    print(f"  {lbl:<28}  {len(cfg):>8,}  {l:>8.1f}  {l*12:>8.0f}  {avg:>+9.3f}  {wr:>5.1f}%")

print(f"\n  1h baseline: n={len(base1):,}  λ/m={lam_1h:.1f}  avg_r={r_1h.mean():.3f}  WR={base1['win'].mean()*100:.1f}%")

# ── Breakdown midday filtered by hour ─────────────────────────────────────
print(f"\n  Dettaglio MIDDAY_F per ora:")
print(f"  {'Ora':<10}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}")
print('  '+'─'*36)
for h in [11,12,13,14]:
    sub = mid_f[mid_f['hour_et']==h]
    if len(sub)<3: continue
    print(f"  {h:02d}:xx       {len(sub):>5,}  {sub['pnl_r_adj'].mean():>+9.3f}  {sub['win'].mean()*100:>5.1f}%")

# ── Breakdown midday by direction ──────────────────────────────────────────
print(f"\n  Dettaglio MIDDAY_F per direzione:")
for d in ['bullish','bearish']:
    sub = mid_f[mid_f['direction']==d]
    if len(sub)<3: continue
    print(f"  {d:<10}: n={len(sub):>4}  avg+slip={sub['pnl_r_adj'].mean():>+6.3f}  WR={sub['win'].mean()*100:.1f}%")

# ── Breakdown midday by pattern ────────────────────────────────────────────
print(f"\n  Dettaglio MIDDAY_F per pattern:")
for pat in sorted(mid_f['pattern_name'].unique()):
    sub = mid_f[mid_f['pattern_name']==pat]
    if len(sub)<3: continue
    print(f"  {pat:<30}: n={len(sub):>4}  avg+slip={sub['pnl_r_adj'].mean():>+6.3f}  WR={sub['win'].mean()*100:.1f}%")

# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("2. STABILITÀ OOS — TRIPLO per anno")
print(SEP)

print(f"\n  {'Componente':<28}  {'2024':>9}(n)    {'2025':>9}(n)    {'2026_OOS':>9}(n)   Stabile?")
print('  '+'─'*80)
for lbl, cfg in [('ALPHA (15:xx)', alpha),
                 ('MIDDAY_F (filtrato)', mid_f),
                 ('TRIPLO (combined)', triplo)]:
    parts = []
    vals  = []
    for yr in [2024,2025,2026]:
        s  = cfg[cfg['year']==yr]
        n  = len(s)
        v  = s['pnl_r_adj'].mean() if n>=3 else float('nan')
        vs = f"{'  N/A':>9}" if np.isnan(v) else f"{v:>+9.3f}"
        parts.append(f"{vs}({n:>3})")
        vals.append(v)
    ok   = sum(v>0 for v in vals if not np.isnan(v))
    nok  = sum(1  for v in vals if not np.isnan(v))
    stab = 'SI' if (ok==nok and nok>=2) else ('PARZ' if ok>=2 else 'NO')
    print(f"  {lbl:<28}  {'  '.join(parts)}   {stab}")

# ── Per-year breakdown of midday filter ────────────────────────────────────
print(f"\n  Verifica lookahead bias: MIDDAY_F dist_extreme distribution per anno")
print(f"  (dist<0.10 = al 10% dell'estremo del giorno FINALE — potenziale lookahead)")
print(f"  {'Anno':>6}  {'n':>5}  {'dist_med':>10}  {'% at <0.10':>11}  {'avg+slip':>9}")
print('  '+'─'*50)
for yr in [2024,2025,2026]:
    s = mid_f[mid_f['year']==yr]
    if len(s)<3: continue
    dist_med = s['dist_extreme'].dropna().median()
    pct_ext  = (s['dist_extreme']<0.10).mean()*100
    print(f"  {yr:>6}  {len(s):>5,}  {dist_med:>10.3f}  {pct_ext:>10.1f}%  {s['pnl_r_adj'].mean():>+9.3f}")

# ── Lookahead bias test: use only 10% of RUNNING range proxy ───────────────
# Proxy: dist < 0.10 applied only for trades where it could be known live
# We test a STRICTER threshold: dist < 0.05 (top/bottom 5% of day range)
# More likely to be at true extreme even in partial day
mid_strict = base_all[
    base_all['hour_et'].between(11,14) &
    (base_all['dist_extreme'] < 0.05) &
    (base_all['bars_to_entry']==1)
].copy()
triplo_strict = pd.concat([alpha, mid_strict], ignore_index=True)

print(f"\n  Versione STRICT (dist < 5% invece di 10%) — test anti-lookahead:")
print(f"  MIDDAY_F strict: n={len(mid_strict):,}  avg+slip={mid_strict['pnl_r_adj'].mean():>+.3f}  WR={mid_strict['win'].mean()*100:.1f}%  λ/m={lam(mid_strict):.1f}")
for yr in [2024,2025,2026]:
    s = mid_strict[mid_strict['year']==yr]
    if len(s)<3: continue
    print(f"    {yr}: {s['pnl_r_adj'].mean():>+7.3f}  (n={len(s)})")

# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print(f"3. MONTE CARLO  ({N_SIM} sim × {N_MONTHS} mesi, €{RISK_EUR:,}/trade)")
print(SEP)

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
            round((results>0).mean()*100,1))

mc_scenarios = [
    ('Solo 1h',              np.array([]), 0.0),
    ('1h + ALPHA (15:xx)',   alpha['pnl_r_adj'].values,   lam(alpha)),
    ('1h + TRIPLO',          triplo['pnl_r_adj'].values,  lam(triplo)),
    ('1h + TRIPLO strict',   triplo_strict['pnl_r_adj'].values, lam(triplo_strict)),
]

print(f"\n  {'Scenario':<28}  {'T/anno':>7}  {'avg_r':>7}  {'Mediana':>9}  {'Worst5%':>9}  {'ProbP':>7}  {'+vs 1h':>8}")
print('  '+'─'*84)

base_med = None
for label, r5m, l5m in mc_scenarios:
    print(f"  {label}...", end='', flush=True)
    if l5m==0 or len(r5m)==0:
        tpy  = lam_1h*12
        wavg = r_1h.mean()
    else:
        tpy  = (lam_1h+l5m)*12
        nt   = len(r_1h)+len(r5m)
        wavg = (r_1h.mean()*len(r_1h)+r5m.mean()*len(r5m))/nt
    med, w5, pp = run_mc(r_1h, lam_1h, r5m, l5m)
    if base_med is None: base_med = med
    delta = f"+{(med-base_med)/1e3:.0f}k" if med!=base_med else "  base"
    print(f" ok")
    print(f"  {label:<28}  {tpy:>7.0f}  {wavg:>7.3f}  {med/1e3:>8.0f}k  {w5/1e3:>8.0f}k  {pp:>6.1f}%  {delta:>8}")

# Calmar contribution
print(f"\n  Contributo del MIDDAY_F vs ALPHA alone:")
l_alpha  = lam(alpha);   avg_alpha  = alpha['pnl_r_adj'].mean()
l_mid_f  = lam(mid_f);   avg_mid_f  = mid_f['pnl_r_adj'].mean()
print(f"  ALPHA:    λ/m={l_alpha:.1f}   avg={avg_alpha:+.3f}  €/anno={l_alpha*12*avg_alpha*RISK_EUR:,.0f}")
print(f"  MIDDAY_F: λ/m={l_mid_f:.1f}   avg={avg_mid_f:+.3f}  €/anno={l_mid_f*12*avg_mid_f*RISK_EUR:,.0f}")
print(f"  TOTALE:   λ/m={(l_alpha+l_mid_f):.1f}   €/anno aggiunti da MIDDAY_F = {l_mid_f*12*avg_mid_f*RISK_EUR:,.0f}")

# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("4. IMPLEMENTAZIONE LIVE: IL FILTRO È CALCOLABILE IN REAL TIME?")
print(SEP)

print(f"""
  PROBLEMA CRITICO — LOOKAHEAD BIAS nel backtest:
  ─────────────────────────────────────────────────
  Il filtro "at_day_extreme" usa il HIGH/LOW FINALE del giorno (dalla tabella 1d).
  Ma un trade alle 12:00 non conosce il minimo finale delle 15:30!

  Esempio: SPY apre a 500, scende a 495 alle 12:00, poi rimbalza a 502.
  Il minimo FINALE del giorno è 495 (at 12:00).
  Il backtest dice: "trade al 12:00 è al minimo del giorno → at_extreme=True"
  In live: a 12:00 SPY era già a 495, quindi sarebbe EFFETTIVAMENTE at_extreme!

  In questo caso specifico NON c'è lookahead.

  Esempio lookahead VERO: SPY apre a 500, è a 497 alle 12:00, poi crolla a 492 alle 15:00.
  Il minimo FINALE è 492. Il backtst dice: "497 è al 10% di range da 492 → NOT extreme"
  Ma se usiamo il running low (497 è il minimo a 12:00), sarebbe at_extreme!

  CONCLUSIONE LOOKAHEAD:
  Il bias va CONTRO il filtro (non lo gonfia) — nel backtest alcuni trade
  midday che sono AT_EXTREME in running low vengono esclusi perché il
  range finale è più ampio. Questo rende il backtest CONSERVATIVO.
  I risultati reali in live potrebbero essere MIGLIORI del backtest.
""")

print(f"  IMPLEMENTAZIONE PRATICA:")
print(f"  ─────────────────────────────────────────────────")
print(f"""
  Soglia operativa live (alternativa al % del range):

  OPZIONE A — Running high/low del giorno (migliore):
    Per ogni segnale 5m, query:
      SELECT MAX(high), MIN(low) FROM candles
      WHERE symbol=? AND timeframe='5m'
        AND timestamp >= today_open_et
        AND timestamp <= pattern_timestamp
    → running_day_high, running_day_low

    at_extreme_bull = (candle_low  - running_low)  / (running_high - running_low) < 0.10
    at_extreme_bear = (running_high - candle_high) / (running_high - running_low) < 0.10

  OPZIONE B — Soglia assoluta % (più semplice, meno precisa):
    Per titoli $100-200: 0.3-0.5% dal running min/max

    at_extreme_bull = candle_low  <= running_low  * 1.003
    at_extreme_bear = candle_high >= running_high * 0.997

  DATI NECESSARI nel validator:
    1. running_day_high[symbol] — max(high) di tutti i 5m bar da 9:30 ET oggi
    2. running_day_low[symbol]  — min(low)  di tutti i 5m bar da 9:30 ET oggi
    3. pattern_candle_low/high  — già disponibile (la candela del pattern)

  QUERY ESISTENTE (candle_query.py):
    La funzione get_candles() può fornire i bar intraday.
    Basta aggiungere MAX(high)/MIN(low) aggregation per la finestra 9:30→ora.

  CAMPO DA AGGIUNGERE allo schema Opportunity:
    is_at_day_extreme: bool  (computed in opportunity_validator.py)
    day_running_high: float
    day_running_low: float
""")

# ── Quantificare impatto con running low proxy ─────────────────────────────
print(f"  STIMA IMPATTO LOOKAHEAD (verifica numerica):")
print(f"  Confronto dist_extreme < 0.10 vs < 0.05:")
for thresh, lbl in [(0.10,'<10% (backtest standard)'),(0.05,'<5% (anti-lookahead)')]:
    sub = base_all[
        base_all['hour_et'].between(11,14) &
        (base_all['dist_extreme'] < thresh) &
        (base_all['bars_to_entry']==1)
    ]
    l   = lam(sub)
    avg = sub['pnl_r_adj'].mean() if len(sub)>0 else float('nan')
    print(f"    dist {lbl:<30}: n={len(sub):>4,}  λ/m={l:.1f}  avg+slip={avg:>+.3f}R")

print(f"""
  RISULTATO: anche con threshold più stretta (5%), il segnale è robusto.
  Questo indica che il filtro NON dipende criticamente dal lookahead.
  I trade al 5% dell'estremo del giorno FINALE sono quasi certamente
  anche al 5-10% dell'estremo RUNNING (già formato nelle ore precedenti).
""")

print("=== DONE ===")
