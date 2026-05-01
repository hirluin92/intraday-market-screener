#!/usr/bin/env python3
"""
Analisi approfondita: perché AAPL, MSFT, GOOGL, AMZN falliscono?
Confronto con top performers SMCI, COIN, PLTR, HOOD.

Parti:
  1. Diagnosi per colosso (pattern, ora, regime)
  2. Perché falliscono (efficienza, ATR%, slippage, timeout)
  3. Esiste un config per farli funzionare?
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

COLOSSI   = ['AAPL', 'MSFT', 'GOOGL', 'AMZN']
TOP_PERFS = ['SMCI', 'COIN', 'PLTR', 'HOOD']
ALL_FOCUS = COLOSSI + TOP_PERFS

# ── DB ────────────────────────────────────────────────────────────────────────
print("Loading DB...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()

cur.execute("""
    SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
    FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp
""")
spy_1d = cur.fetchall()

# 1d OHLC per ATR% e regime
cur.execute("""
    SELECT symbol, DATE(timestamp AT TIME ZONE 'UTC'),
           open::float, high::float, low::float, close::float
    FROM candles WHERE timeframe='1d'
      AND symbol = ANY(%s)
    ORDER BY symbol, timestamp
""", (ALL_FOCUS,))
sym_1d_rows = cur.fetchall()
conn.close()

# Regime SPY
spy_df = pd.DataFrame(spy_1d, columns=['date', 'close'])
spy_df['ema50']  = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']    = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime'] = 'neutral'
spy_df.loc[spy_df['pct'] >  2, 'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2, 'regime'] = 'bear'
spy_dict = dict(zip(spy_df['date'], spy_df['regime']))

def get_regime(d):
    for i in range(1, 15):
        v = spy_dict.get(d - timedelta(days=i))
        if v is not None: return v
    return 'neutral'

# ATR% per simbolo (daily true range / close * 100)
sym_1d_df = pd.DataFrame(sym_1d_rows, columns=['symbol','date','open','high','low','close'])
sym_1d_df = sym_1d_df.sort_values(['symbol','date'])
sym_1d_df['prev_close'] = sym_1d_df.groupby('symbol')['close'].shift(1)
sym_1d_df['tr'] = sym_1d_df.apply(lambda r: max(
    r['high'] - r['low'],
    abs(r['high'] - r['prev_close']) if not np.isnan(r['prev_close']) else 0,
    abs(r['low']  - r['prev_close']) if not np.isnan(r['prev_close']) else 0
), axis=1)
sym_1d_df['atr_pct'] = sym_1d_df['tr'] / sym_1d_df['close'] * 100

atr_by_sym = sym_1d_df.groupby('symbol')['atr_pct'].mean()

# range% giornaliero medio (high-low)/close
sym_1d_df['range_pct'] = (sym_1d_df['high'] - sym_1d_df['low']) / sym_1d_df['close'] * 100
range_by_sym = sym_1d_df.groupby('symbol')['range_pct'].mean()

# Close medio (per contesto)
close_by_sym = sym_1d_df.groupby('symbol')['close'].mean()

# ── Load 5m ───────────────────────────────────────────────────────────────────
print("Loading val_5m_expanded.csv...", flush=True)
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

def add_slip(df):
    df = df.copy()
    df['pnl_r_adj'] = (df['pnl_r']
        - 0.03 / df['risk_pct']
        - np.where(df['outcome'] == 'stop', 0.05 / df['risk_pct'], 0.0))
    df['win']     = df['pnl_r_adj'] > 0
    df['timeout'] = df['outcome'] == 'timeout'
    df['hit_tp2'] = df['outcome'] == 'tp2'
    df['hit_tp1'] = df['outcome'].isin(['tp1', 'tp2'])
    df['is_stop'] = df['outcome'] == 'stop'
    return df

def regime_ok(row):
    reg = row['regime']; dir_ = row['direction']
    return (reg == 'neutral') or (reg == 'bull' and dir_ == 'bullish') or (reg == 'bear' and dir_ == 'bearish')

# ── Dataset base: entry_filled, risk 0.5-2%, no engulfing, regime ────────────
base = add_slip(df5[
    (df5['entry_filled'] == True) &
    (df5['risk_pct'] >= 0.50) & (df5['risk_pct'] <= 2.00) &
    (df5['pattern_name'] != 'engulfing_bullish') &
    df5.apply(regime_ok, axis=1) &
    df5['symbol'].isin(ALL_FOCUS)
].copy())

print(f"  Dataset focus ({', '.join(ALL_FOCUS)}): {len(base):,} trade", flush=True)

def stats(df, label=""):
    n = len(df)
    if n < 3: return None
    avg   = df['pnl_r_adj'].mean()
    wr    = df['win'].mean() * 100
    to_pct = df['timeout'].mean() * 100
    tp2_pct = df['hit_tp2'].mean() * 100
    stop_pct = df['is_stop'].mean() * 100
    bars   = df['bars_to_exit'].median() if 'bars_to_exit' in df.columns else np.nan
    riskp  = df['risk_pct'].mean()
    return dict(n=n, avg=avg, wr=wr, to_pct=to_pct, tp2_pct=tp2_pct,
                stop_pct=stop_pct, bars=bars, riskp=riskp)

def fmt_avg(v): return f"{v:>+8.3f}" if not np.isnan(v) else f"{'N/A':>8}"
def fmt_pct(v): return f"{v:>5.1f}%" if not np.isnan(v) else f"{'N/A':>6}"

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 1A — OVERVIEW: colossi vs top performers")
print("  Base: entry_filled, risk 0.5-2%, no engulfing, regime filter, NO filtro orario")
print(SEP)

print(f"\n  {'Simbolo':<8}  {'n':>5}  {'avg_r':>7}  {'avg+slip':>9}  {'WR':>6}  "
      f"{'TO%':>6}  {'TP2%':>5}  {'Stop%':>6}  {'MedianBars':>10}  {'AvgRisk%':>9}")
print("  " + "─" * 80)

for sym in ALL_FOCUS:
    sub = base[base['symbol'] == sym]
    if len(sub) < 3:
        print(f"  {sym:<8}  < 3 trade")
        continue
    avg_r = sub['pnl_r'].mean()
    s = stats(sub)
    marker = " ◀ COLOSS" if sym in COLOSSI else " ◀ TOP"
    print(f"  {sym:<8}  {s['n']:>5,}  {avg_r:>+7.3f}  {fmt_avg(s['avg'])}  {fmt_pct(s['wr'])}  "
          f"{s['to_pct']:>5.1f}%  {s['tp2_pct']:>4.1f}%  {s['stop_pct']:>5.1f}%  "
          f"{s['bars']:>9.1f}  {s['riskp']:>8.2f}%{marker}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 1B — BREAKDOWN PER PATTERN (ogni colosso)")
print(SEP)

PATTERNS = ['double_bottom','double_top','macd_divergence_bull','macd_divergence_bear',
            'rsi_divergence_bull','rsi_divergence_bear']

for sym in COLOSSI:
    sub = base[base['symbol'] == sym]
    print(f"\n  ─── {sym} (n_tot={len(sub)}) ───")
    print(f"  {'Pattern':<28}  {'n':>4}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}  {'TP2%':>5}  {'Bars':>5}")
    for pat in PATTERNS:
        sp = sub[sub['pattern_name'] == pat]
        if len(sp) < 2: continue
        s = stats(sp)
        print(f"  {pat:<28}  {s['n']:>4}  {fmt_avg(s['avg'])}  "
              f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%  {s['tp2_pct']:>4.1f}%  "
              f"{s['bars']:>4.0f}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 1C — BREAKDOWN PER ORA ET (ogni colosso)")
print(SEP)

for sym in COLOSSI:
    sub = base[base['symbol'] == sym]
    print(f"\n  ─── {sym} ───")
    print(f"  {'Ora':>5}  {'n':>4}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}  {'Bars':>5}")
    for h in range(10, 16):
        sp = sub[sub['hour_et'] == h]
        if len(sp) < 3: continue
        s = stats(sp)
        print(f"  {h:02d}:xx  {s['n']:>4}  {fmt_avg(s['avg'])}  "
              f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%  {s['bars']:>4.0f}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 1D — BREAKDOWN PER REGIME")
print(SEP)

print(f"\n  {'Simbolo':<8}  {'Regime':<8}  {'n':>4}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 50)
for sym in COLOSSI:
    sub = base[base['symbol'] == sym]
    for reg_val in ['neutral', 'bull', 'bear']:
        sp = sub[sub['regime'] == reg_val]
        if len(sp) < 3: continue
        s = stats(sp)
        print(f"  {sym:<8}  {reg_val:<8}  {s['n']:>4}  {fmt_avg(s['avg'])}  "
              f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 2A — EFFICIENZA DI MERCATO: timeout, TP2, bars_to_exit")
print("  Ipotesi: i colossi hanno timeout più alto → pattern neutralizzati dagli algos")
print(SEP)

print(f"\n  {'Simbolo':<8}  {'Tipo':>8}  {'TO%':>7}  {'TP1%':>7}  {'TP2%':>7}  "
      f"{'Stop%':>7}  {'MedianBarsExit':>14}  {'P90_bars':>9}")
print("  " + "─" * 72)
for sym in ALL_FOCUS:
    sub = base[base['symbol'] == sym]
    if len(sub) < 5: continue
    tipo = "COLOSS" if sym in COLOSSI else "TOP"
    to_p   = (sub['outcome'] == 'timeout').mean() * 100
    tp1_p  = sub['hit_tp1'].mean() * 100
    tp2_p  = (sub['outcome'] == 'tp2').mean() * 100
    stop_p = (sub['outcome'] == 'stop').mean() * 100
    med_b  = sub['bars_to_exit'].median()
    p90_b  = sub['bars_to_exit'].quantile(0.9)
    print(f"  {sym:<8}  {tipo:>8}  {to_p:>6.1f}%  {tp1_p:>6.1f}%  {tp2_p:>6.1f}%  "
          f"{stop_p:>6.1f}%  {med_b:>13.0f}  {p90_b:>8.0f}")

# Breakdown per fascia oraria — colossi vs top
print(f"\n  ── Timeout% per fascia oraria: COLOSSI vs TOP ──")
print(f"  {'Ora':>5}  {'AAPL':>8}  {'MSFT':>8}  {'GOOGL':>8}  {'AMZN':>8}  "
      f"  {'SMCI':>8}  {'COIN':>8}  {'PLTR':>8}")
print("  " + "─" * 72)
for h in range(10, 16):
    row = f"  {h:02d}:xx"
    for sym in ['AAPL','MSFT','GOOGL','AMZN','__','SMCI','COIN','PLTR']:
        if sym == '__':
            row += "  "; continue
        sub = base[(base['symbol'] == sym) & (base['hour_et'] == h)]
        if len(sub) < 3:
            row += f"  {'---':>8}"
        else:
            row += f"  {(sub['outcome']=='timeout').mean()*100:>7.1f}%"
    print(row)

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 2B — RANGE GIORNALIERO (ATR%)")
print("  Ipotesi: i colossi si muovono meno % → TP non raggiungibile")
print(SEP)

print(f"\n  {'Simbolo':<8}  {'Tipo':>8}  {'ATR%_medio':>11}  {'Range%_medio':>13}  "
      f"{'Prezzo_medio':>13}  {'risk_pct_med':>13}")
print("  " + "─" * 70)
for sym in ALL_FOCUS:
    sub = base[base['symbol'] == sym]
    if len(sub) < 3: continue
    tipo   = "COLOSS" if sym in COLOSSI else "TOP"
    atr    = atr_by_sym.get(sym, np.nan)
    rng    = range_by_sym.get(sym, np.nan)
    price  = close_by_sym.get(sym, np.nan)
    riskp  = sub['risk_pct'].mean()
    print(f"  {sym:<8}  {tipo:>8}  {atr:>10.2f}%  {rng:>12.2f}%  "
          f"  ${price:>10.1f}  {riskp:>12.2f}%")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 2C — SLIPPAGE RELATIVO: risk_pct distribution")
print("  Ipotesi: risk_pct basso → slippage/risk ratio alto")
print(SEP)

print(f"\n  Slippage modello: entry=-0.03/risk_pct, stop_extra=-0.05/risk_pct")
print(f"\n  {'Simbolo':<8}  {'risk_med':>9}  {'risk_p25':>9}  {'risk_p75':>9}  "
      f"{'slip_entry_R':>13}  {'slip_stop_R':>12}  {'slip_total_R':>13}")
print("  " + "─" * 72)
for sym in ALL_FOCUS:
    sub = base[base['symbol'] == sym]
    if len(sub) < 3: continue
    tipo   = "COLOSS" if sym in COLOSSI else "TOP   "
    r_med  = sub['risk_pct'].median()
    r_p25  = sub['risk_pct'].quantile(0.25)
    r_p75  = sub['risk_pct'].quantile(0.75)
    se_r   = 0.03 / r_med
    ss_r   = 0.05 / r_med
    st_r   = se_r + ss_r * 0.5  # assume 50% stop rate
    print(f"  {sym:<8}  {r_med:>8.3f}%  {r_p25:>8.3f}%  {r_p75:>8.3f}%  "
          f"  -{se_r:>10.3f}R  -{ss_r:>10.3f}R  -{st_r:>11.3f}R  [{tipo}]")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 2D — DIMENSIONE DEL PATTERN: dollar range del pattern")
print("  Ipotesi: pattern troppo piccoli in $ → noise supera il segnale")
print(SEP)

# entry_price - stop_price = dollar risk per trade
base['dollar_risk'] = abs(base['entry_price'] - base['stop_price'])
base['tp1_dist_pct'] = abs(base['tp1_price'] - base['entry_price']) / base['entry_price'] * 100

print(f"\n  {'Simbolo':<8}  {'DollarRisk_med':>14}  {'DollarRisk_p25':>15}  "
      f"{'TP1dist%_med':>13}  {'EntryPx_med':>12}")
print("  " + "─" * 68)
for sym in ALL_FOCUS:
    sub = base[base['symbol'] == sym]
    if len(sub) < 3: continue
    tipo = "COLOSS" if sym in COLOSSI else "TOP   "
    dr_med = sub['dollar_risk'].median()
    dr_p25 = sub['dollar_risk'].quantile(0.25)
    tp1_med = sub['tp1_dist_pct'].median()
    ep_med  = sub['entry_price'].median()
    print(f"  {sym:<8}  ${dr_med:>12.3f}  ${dr_p25:>12.3f}  "
          f"  {tp1_med:>11.3f}%  ${ep_med:>10.1f}  [{tipo}]")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3A — SOLO POWER HOURS (15:30-16:00)")
print(SEP)

ph = base[(base['hour_et'] == 15) & (base['min_et'] >= 30)]
print(f"\n  {'Simbolo':<8}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}  {'TP2%':>5}  {'Bars':>5}")
print("  " + "─" * 50)
for sym in ALL_FOCUS:
    sub = ph[ph['symbol'] == sym]
    if len(sub) < 3:
        print(f"  {sym:<8}  {len(sub):>5}  (troppo pochi)")
        continue
    s = stats(sub)
    tipo = " ◀ COLOSS" if sym in COLOSSI else " ◀ TOP"
    print(f"  {sym:<8}  {s['n']:>5}  {fmt_avg(s['avg'])}  "
          f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%  {s['tp2_pct']:>4.1f}%  "
          f"{s['bars']:>4.0f}{tipo}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3B — SOLO REGIME BEAR")
print(SEP)

bear_only = base[base['regime'] == 'bear']
print(f"\n  {'Simbolo':<8}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}")
print("  " + "─" * 44)
for sym in ALL_FOCUS:
    sub = bear_only[bear_only['symbol'] == sym]
    if len(sub) < 3:
        print(f"  {sym:<8}  {len(sub):>5}  (troppo pochi)")
        continue
    s = stats(sub)
    tipo = " ◀ COLOSS" if sym in COLOSSI else " ◀ TOP"
    print(f"  {sym:<8}  {s['n']:>5}  {fmt_avg(s['avg'])}  "
          f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%{tipo}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3C — SOLO double_top / double_bottom (no divergenze)")
print(SEP)

dt_db_only = base[base['pattern_name'].isin(['double_top', 'double_bottom'])]
print(f"\n  {'Simbolo':<8}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}  {'TP2%':>5}")
print("  " + "─" * 48)
for sym in ALL_FOCUS:
    sub = dt_db_only[dt_db_only['symbol'] == sym]
    if len(sub) < 3:
        print(f"  {sym:<8}  {len(sub):>5}  (troppo pochi)")
        continue
    s = stats(sub)
    tipo = " ◀ COLOSS" if sym in COLOSSI else " ◀ TOP"
    print(f"  {sym:<8}  {s['n']:>5}  {fmt_avg(s['avg'])}  "
          f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%  {s['tp2_pct']:>4.1f}%{tipo}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3D — COMBINAZIONI: Power Hours + double_top/double_bottom")
print("  (massima filtratura per cercare edge sui colossi)")
print(SEP)

ph_dtdb = base[
    (base['hour_et'] == 15) &
    (base['min_et'] >= 30) &
    (base['pattern_name'].isin(['double_top', 'double_bottom']))
]
print(f"\n  {'Simbolo':<8}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}  {'TP2%':>5}")
print("  " + "─" * 48)
for sym in COLOSSI:
    sub = ph_dtdb[ph_dtdb['symbol'] == sym]
    if len(sub) < 2:
        print(f"  {sym:<8}  {len(sub):>5}  (pochi dati)")
        continue
    s = stats(sub)
    if s is None:
        print(f"  {sym:<8}  pochi dati")
        continue
    print(f"  {sym:<8}  {s['n']:>5}  {fmt_avg(s['avg'])}  "
          f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%  {s['tp2_pct']:>4.1f}%")

# PH + tutte le ore (15:xx full)
print(f"\n  ── ALPHA (15:xx intero) + solo double_top/double_bottom ──")
alpha_dtdb = base[
    (base['hour_et'] == 15) &
    (base['pattern_name'].isin(['double_top', 'double_bottom']))
]
for sym in COLOSSI:
    sub = alpha_dtdb[alpha_dtdb['symbol'] == sym]
    if len(sub) < 2:
        print(f"  {sym:<8}  {len(sub):>5}  (pochi dati)")
        continue
    s = stats(sub)
    if s is None:
        print(f"  {sym:<8}  pochi dati")
        continue
    print(f"  {sym:<8}  n={s['n']:>4}  avg+slip={fmt_avg(s['avg'])}  WR={fmt_pct(s['wr'])}  TO={s['to_pct']:.1f}%")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3E — TRIPLO CONFIG sui colossi (stesso filtro produzione)")
print("  15:xx ALPHA + 11-14 MIDDAY_F (at_extreme proxy: risk_pct≤0.8 + hour 11-14)")
print("  (nota: at_extreme reale richiederebbe join con 1d OHLC — usa ALPHA come proxy)")
print(SEP)

# ALPHA (15:xx) puro per colossi
alpha_colossi = base[base['hour_et'] == 15]
print(f"\n  ── ALPHA (15:xx) per colossi ──")
print(f"  {'Simbolo':<8}  {'n':>5}  {'avg+slip':>9}  {'WR':>6}  {'TO%':>6}  OOS 2024/2025/2026")
print("  " + "─" * 70)
for sym in COLOSSI:
    sub = alpha_colossi[alpha_colossi['symbol'] == sym]
    if len(sub) < 3:
        print(f"  {sym:<8}  {len(sub):>5}  (pochi dati)")
        continue
    s = stats(sub)
    oos_parts = []
    for yr in [2024, 2025, 2026]:
        sy = sub[sub['year'] == yr]
        v  = sy['pnl_r_adj'].mean() if len(sy) >= 3 else float('nan')
        oos_parts.append(f"{'N/A':>7}" if np.isnan(v) else f"{v:>+7.3f}({len(sy)})")
    print(f"  {sym:<8}  {s['n']:>5}  {fmt_avg(s['avg'])}  "
          f"{fmt_pct(s['wr'])}  {s['to_pct']:>5.1f}%  {'  '.join(oos_parts)}")

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3F — CONFRONTO METRICA COMPLETA: SMCI/COIN/PLTR vs AAPL/MSFT/GOOGL/AMZN")
print(SEP)

compare_syms = ['SMCI','COIN','PLTR','AAPL','MSFT','GOOGL','AMZN']
print(f"\n  {'Metrica':<30}  " + "  ".join(f"{s:<8}" for s in compare_syms))
print("  " + "─" * 90)

metrics = {}
for sym in compare_syms:
    sub = base[base['symbol'] == sym]
    if len(sub) < 3:
        metrics[sym] = {}
        continue
    metrics[sym] = {
        'ATR%': atr_by_sym.get(sym, np.nan),
        'Range%': range_by_sym.get(sym, np.nan),
        'Prezzo_med': close_by_sym.get(sym, np.nan),
        'n_tot': len(sub),
        'avg+slip': sub['pnl_r_adj'].mean(),
        'WR%': sub['win'].mean() * 100,
        'Timeout%': (sub['outcome'] == 'timeout').mean() * 100,
        'TP2%': (sub['outcome'] == 'tp2').mean() * 100,
        'MedianBars': sub['bars_to_exit'].median(),
        'AvgBars': sub['bars_to_exit'].mean(),
        'risk_pct_med': sub['risk_pct'].median(),
        'Slip_entry_R': 0.03 / sub['risk_pct'].median(),
        'Slip_stop_R': 0.05 / sub['risk_pct'].median(),
        'Dollar_risk': sub['dollar_risk'].median(),
        'TP1dist%': sub['tp1_dist_pct'].median(),
    }

for mkey in ['ATR%','Range%','Prezzo_med','n_tot','avg+slip','WR%',
             'Timeout%','TP2%','MedianBars','AvgBars','risk_pct_med',
             'Slip_entry_R','Slip_stop_R','Dollar_risk','TP1dist%']:
    row = f"  {mkey:<30}"
    for sym in compare_syms:
        v = metrics[sym].get(mkey, np.nan)
        if isinstance(v, float) and not np.isnan(v):
            if mkey in ('Prezzo_med','Dollar_risk'):
                row += f"  ${v:<7.1f}"
            elif mkey in ('n_tot',):
                row += f"  {int(v):<8}"
            elif mkey in ('Slip_entry_R','Slip_stop_R'):
                row += f"  -{v:<7.3f}"
            elif '%' in mkey or mkey in ('TP1dist%',):
                row += f"  {v:<7.2f}%"
            elif mkey in ('MedianBars','AvgBars'):
                row += f"  {v:<8.1f}"
            else:
                row += f"  {v:<+8.3f}"
        else:
            row += f"  {'N/A':<8}"
    print(row)

# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 4 — CONCLUSIONI: chi vale la pena provare?")
print(SEP)

print("""
  Riepilogo per ogni colosso (ALPHA 15:xx — la componente più forte del sistema):
""")

for sym in COLOSSI:
    sub = base[base['hour_et'] == 15][base[base['hour_et'] == 15]['symbol'] == sym]
    sub_all = base[base['symbol'] == sym]
    n_alpha = len(sub)
    n_all   = len(sub_all)
    if n_alpha >= 3:
        avg_a = sub['pnl_r_adj'].mean()
        wr_a  = sub['win'].mean() * 100
        to_a  = (sub['outcome'] == 'timeout').mean() * 100
        # OOS years positivi
        oos_pos = sum(1 for yr in [2024,2025,2026]
                      if len(sub[sub['year']==yr]) >= 3
                      and sub[sub['year']==yr]['pnl_r_adj'].mean() > 0)
        oos_tot = sum(1 for yr in [2024,2025,2026] if len(sub[sub['year']==yr]) >= 3)
        verdict = "RIMUOVI DAL BLOCCO" if (avg_a > 0.3 and wr_a > 45 and oos_pos >= 2) else \
                  "CANDIDATO (monitor)" if (avg_a > 0 and oos_pos >= 1) else "MANTIENI BLOCCO"
        print(f"  {sym}: n_ALPHA={n_alpha}, avg+slip={avg_a:+.3f}R, WR={wr_a:.1f}%, "
              f"TO={to_a:.1f}%, OOS pos={oos_pos}/{oos_tot} → {verdict}")
    else:
        print(f"  {sym}: n_ALPHA={n_alpha} (insufficiente) → MANTIENI BLOCCO")

print(f"\n{SEP}")
print("DONE — colossi_analysis.py")
print(SEP)
