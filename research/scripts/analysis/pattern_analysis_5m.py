#!/usr/bin/env python3
"""ANALISI PATTERN COMPLETA 5m — tutti i pattern, parti 1-6."""
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

# ═══ Regime ════════════════════════════════════════════════════════════════
print("Loading...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur  = conn.cursor()
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

# ═══ Load & filter ═════════════════════════════════════════════════════════
df = pd.read_csv('/app/data/val_5m_expanded.csv')
df['ts']     = pd.to_datetime(df['pattern_timestamp'], utc=True)
df['_d']     = df['ts'].apply(lambda x: x.date())
df['regime'] = df['_d'].apply(get_regime)
df['year']   = df['ts'].dt.year
if TZ_ET:
    df['hour_et'] = df['ts'].dt.tz_convert(TZ_ET).dt.hour
else:
    df['hour_et'] = (df['ts'].dt.hour - 4) % 24

BLOCKED_BASE = frozenset({'SPY','AAPL','MSFT','GOOGL','WMT','DELL'})

# Regime filter mask
regime_ok = (
    ((df['regime'] == 'bull')    & (df['direction'] == 'bullish')) |
    ((df['regime'] == 'bear')    & (df['direction'] == 'bearish')) |
    (df['regime'] == 'neutral')
)

# Structural filters — NO pattern exclusion
base = df[
    (df['entry_filled'] == True) &
    (df['risk_pct'] >= 0.50) &
    (df['risk_pct'] <= 2.00) &
    (~df['symbol'].isin(BLOCKED_BASE)) &
    regime_ok
].copy()

# Slippage
base['pnl_r_adj'] = (
    base['pnl_r']
    - 0.03 / base['risk_pct']
    - np.where(base['outcome'] == 'stop', 0.05 / base['risk_pct'], 0.0)
)
base['win'] = base['pnl_r_adj'] > 0

SEP  = '═' * 78
SEP2 = '─' * 78

def stats_pat(g):
    n   = len(g)
    wr  = g['win'].mean() * 100 if n > 0 else 0
    ar  = g['pnl_r'].mean() if n > 0 else 0
    aadj = g['pnl_r_adj'].mean() if n > 0 else 0
    return pd.Series({'n': int(n),
                      'avg_r': round(ar, 3),
                      'avg+slip': round(aadj, 3),
                      'WR%': round(wr, 1)})

ALL_PATS = sorted(base['pattern_name'].unique())

print(f"Dataset base (tutti pattern): n={len(base):,}")
print(f"Pattern: {ALL_PATS}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 1 — Tutti i pattern, TUTTO il dataset
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 1 — TUTTI I PATTERN × DIRECTION  (full dataset, strutturale)")
print(SEP)

t = base.groupby(['pattern_name', 'direction']).apply(stats_pat).reset_index()
t = t.sort_values('avg+slip', ascending=False)
print(f"\n  {'Pattern':<28} {'Dir':<9} {'n':>6}  {'avg_r':>7}  {'avg+slip':>9}  {'WR%':>6}")
print(f"  {SEP2}")
for _, row in t.iterrows():
    flag = "  ← BLOCKED" if row['pattern_name'] == 'engulfing_bullish' else ""
    print(f"  {row['pattern_name']:<28} {row['direction']:<9} {row['n']:>6,}  {row['avg_r']:>7.3f}  {row['avg+slip']:>9.3f}  {row['WR%']:>6.1f}%{flag}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 2 — Power Hours 14-16 ET
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 2 — POWER HOURS (14-16 ET)  — tutti i pattern")
print(SEP)

ph = base[base['hour_et'].between(14, 15)]
print(f"\n  Dataset PH: n={len(ph):,}")

t2 = ph.groupby(['pattern_name', 'direction']).apply(stats_pat).reset_index()
t2 = t2.sort_values('avg+slip', ascending=False)
print(f"\n  {'Pattern':<28} {'Dir':<9} {'n':>6}  {'avg_r':>7}  {'avg+slip':>9}  {'WR%':>6}")
print(f"  {SEP2}")
for _, row in t2.iterrows():
    flag = " ← BLOCKED" if row['pattern_name'] == 'engulfing_bullish' else ""
    ok   = " ✓" if row['avg+slip'] > 0 and row['n'] >= 30 else (" ?" if row['avg+slip'] > 0 else "")
    print(f"  {row['pattern_name']:<28} {row['direction']:<9} {row['n']:>6,}  {row['avg_r']:>7.3f}  {row['avg+slip']:>9.3f}  {row['WR%']:>6.1f}%{flag}{ok}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 3 — Last Hour 15-16 ET
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 3 — LAST HOUR (15-16 ET)  — tutti i pattern")
print(SEP)

lh = base[base['hour_et'] == 15]
print(f"\n  Dataset LH: n={len(lh):,}")

t3 = lh.groupby(['pattern_name', 'direction']).apply(stats_pat).reset_index()
t3 = t3.sort_values('avg+slip', ascending=False)
print(f"\n  {'Pattern':<28} {'Dir':<9} {'n':>6}  {'avg_r':>7}  {'avg+slip':>9}  {'WR%':>6}")
print(f"  {SEP2}")
for _, row in t3.iterrows():
    flag = " ← BLOCKED" if row['pattern_name'] == 'engulfing_bullish' else ""
    ok   = " ✓" if row['avg+slip'] > 0 and row['n'] >= 20 else (" ?" if row['avg+slip'] > 0 else "")
    print(f"  {row['pattern_name']:<28} {row['direction']:<9} {row['n']:>6,}  {row['avg_r']:>7.3f}  {row['avg+slip']:>9.3f}  {row['WR%']:>6.1f}%{flag}{ok}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 4 — Pattern × Regime (Power Hours)
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 4 — PATTERN × REGIME  (Power Hours 14-16 ET, tutti i pattern)")
print(SEP)

t4 = ph.groupby(['pattern_name', 'direction', 'regime']).apply(stats_pat).reset_index()
t4 = t4.sort_values(['pattern_name', 'direction', 'regime'])

for pat in sorted(t4['pattern_name'].unique()):
    sub = t4[t4['pattern_name'] == pat]
    flag = "  [BLOCKED]" if pat == 'engulfing_bullish' else ""
    print(f"\n  {pat}{flag}")
    print(f"    {'Dir':<9} {'Regime':<9} {'n':>6}  {'avg+slip':>9}  {'WR%':>6}")
    print(f"    {'─'*46}")
    for _, row in sub.iterrows():
        n_warn = " (pochi)" if row['n'] < 15 else ""
        print(f"    {row['direction']:<9} {row['regime']:<9} {row['n']:>6,}  {row['avg+slip']:>9.3f}  {row['WR%']:>6.1f}%{n_warn}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 5 — Pattern "bloccati" con avg+slip > 0 nelle Power Hours
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 5 — ENGULFING_BULLISH nelle Power Hours: analisi dettagliata")
print(SEP)

engu_ph = ph[ph['pattern_name'] == 'engulfing_bullish'].copy()
print(f"\n  n totale in PH: {len(engu_ph):,}")

# Overall stats
n_e = len(engu_ph)
ar_e  = engu_ph['pnl_r'].mean()
aadj_e = engu_ph['pnl_r_adj'].mean()
wr_e  = engu_ph['win'].mean() * 100
print(f"  avg_r={ar_e:.3f}  avg+slip={aadj_e:.3f}  WR={wr_e:.1f}%")

# Annual stability
print(f"\n  Stabilità annuale:")
print(f"    {'Anno':<6} {'n':>6}  {'avg+slip':>9}  {'WR%':>6}")
print(f"    {'─'*32}")
for yr in [2023, 2024, 2025, 2026]:
    sub = engu_ph[engu_ph['year'] == yr]
    if len(sub) > 0:
        print(f"    {yr:<6} {len(sub):>6,}  {sub['pnl_r_adj'].mean():>9.3f}  {sub['win'].mean()*100:>6.1f}%")

# By regime
print(f"\n  Per regime:")
rg = engu_ph.groupby('regime').apply(stats_pat).reset_index()
for _, row in rg.sort_values('avg+slip', ascending=False).iterrows():
    print(f"    {row['regime']:<9} n={row['n']:>4,}  avg+slip={row['avg+slip']:>7.3f}  WR={row['WR%']:.1f}%")

# By hour (14 vs 15)
print(f"\n  Per ora:")
ho = engu_ph.groupby('hour_et').apply(stats_pat).reset_index()
for _, row in ho.sort_values('avg+slip', ascending=False).iterrows():
    print(f"    {int(row['hour_et']):02d}:xx ET   n={row['n']:>4,}  avg+slip={row['avg+slip']:>7.3f}  WR={row['WR%']:.1f}%")

# Risk bands
print(f"\n  Per fascia risk_pct:")
rbins  = [0.50, 0.75, 1.00, 1.25, 1.50, 2.01]
rlabels = ['0.50-0.75', '0.75-1.00', '1.00-1.25', '1.25-1.50', '1.50-2.00']
engu_ph = engu_ph.copy()
engu_ph['rb'] = pd.cut(engu_ph['risk_pct'], bins=rbins, labels=rlabels, right=False)
rb = engu_ph.groupby('rb', observed=True).apply(stats_pat).reset_index()
for _, row in rb.iterrows():
    print(f"    {row['rb']:<12} n={row['n']:>4,}  avg+slip={row['avg+slip']:>7.3f}  WR={row['WR%']:.1f}%")

# Top symbols for engulfing in PH
print(f"\n  Top 10 simboli per avg+slip (n>=10):")
sym_e = engu_ph.groupby('symbol').apply(stats_pat).reset_index()
sym_e = sym_e[sym_e['n'] >= 10].sort_values('avg+slip', ascending=False)
for _, row in sym_e.head(10).iterrows():
    print(f"    {row['symbol']:<8} n={row['n']:>3}  avg+slip={row['avg+slip']:>7.3f}  WR={row['WR%']:.1f}%")

# Verdict
print(f"\n  VERDETTO engulfing_bullish PH:")
if aadj_e > 0.10 and len(engu_ph) >= 100:
    print(f"  → POTREBBE valere: avg+slip={aadj_e:.3f}, n={len(engu_ph):,}")
elif aadj_e > 0:
    print(f"  → MARGINALE: avg+slip={aadj_e:.3f} (>{0}), ma verificare stabilità")
else:
    print(f"  → CONFERMA DISCARD: avg+slip={aadj_e:.3f} < 0 anche in PH")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 6 — RSI divergence sul 5m
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 6 — RSI DIVERGENCE sul 5m (bull e bear)")
print(SEP)

for pat in ['rsi_divergence_bull', 'rsi_divergence_bear']:
    sub_all = base[base['pattern_name'] == pat]
    sub_ph  = ph[ph['pattern_name']   == pat]
    sub_lh  = lh[lh['pattern_name']   == pat]

    direction = 'bullish' if 'bull' in pat else 'bearish'
    n_tot  = len(sub_all)
    n_ph   = len(sub_ph)
    n_lh   = len(sub_lh)

    print(f"\n  {pat} ({direction})")
    print(f"  {'─'*60}")

    if n_tot == 0:
        print("  Nessun trade nel dataset.")
        continue

    print(f"  Totale     : n={n_tot:>4,}  avg+slip={sub_all['pnl_r_adj'].mean():>7.3f}  WR={sub_all['win'].mean()*100:.1f}%")
    print(f"  PH 14-16   : n={n_ph:>4,}  avg+slip={sub_ph['pnl_r_adj'].mean() if n_ph>0 else 0:>7.3f}  WR={sub_ph['win'].mean()*100 if n_ph>0 else 0:.1f}%")
    print(f"  LH 15-16   : n={n_lh:>4,}  avg+slip={sub_lh['pnl_r_adj'].mean() if n_lh>0 else 0:>7.3f}  WR={sub_lh['win'].mean()*100 if n_lh>0 else 0:.1f}%")

    print(f"\n  Stabilità annuale (PH):")
    print(f"    {'Anno':<6}  {'n':>4}  {'avg+slip':>9}  {'WR%':>6}")
    for yr in [2024, 2025, 2026]:
        sy = sub_ph[sub_ph['year'] == yr]
        if len(sy) > 0:
            print(f"    {yr:<6}  {len(sy):>4,}  {sy['pnl_r_adj'].mean():>9.3f}  {sy['win'].mean()*100:>6.1f}%")
        else:
            print(f"    {yr:<6}  {'0':>4}  {'N/A':>9}  {'N/A':>6}")

    # Regime breakdown (PH)
    print(f"\n  PH per regime:")
    if n_ph > 0:
        rg_r = sub_ph.groupby('regime').apply(stats_pat).reset_index()
        for _, row in rg_r.sort_values('avg+slip', ascending=False).iterrows():
            print(f"    {row['regime']:<9} n={row['n']:>3,}  avg+slip={row['avg+slip']:>7.3f}  WR={row['WR%']:.1f}%")
    else:
        print("    Nessun trade in PH.")

    # Verdict
    print(f"\n  VERDETTO:")
    if n_ph < 20:
        print(f"  → CAMPIONE INSUFFICIENTE in PH (n={n_ph}): tenere ma monitorare.")
    elif sub_ph['pnl_r_adj'].mean() > 0.20:
        print(f"  → EDGE CHIARO in PH: avg+slip={sub_ph['pnl_r_adj'].mean():.3f}, n={n_ph}. Tenere.")
    elif sub_ph['pnl_r_adj'].mean() > 0:
        print(f"  → MARGINALE in PH: avg+slip={sub_ph['pnl_r_adj'].mean():.3f}. Tenere con cautela.")
    else:
        print(f"  → NO EDGE in PH: avg+slip={sub_ph['pnl_r_adj'].mean():.3f}. Valutare rimozione.")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 7 — Confronto configurazione ATTUALE vs senza engulfing
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("PARTE 7 — IMPATTO RIMOZIONE engulfing_bullish (PH 14-16)")
print(SEP)

# Con engulfing
all_ph  = ph.copy()
# Senza engulfing
no_engu = ph[ph['pattern_name'] != 'engulfing_bullish'].copy()

configs_cmp = {
    'PH (tutti 7 pattern)':       all_ph,
    'PH (senza engulfing = 6p)':  no_engu,
}

print(f"\n  {'Config':<35}  {'n':>6}  {'avg_r':>7}  {'avg+slip':>9}  {'WR%':>6}")
print(f"  {'─'*66}")
for nm, c in configs_cmp.items():
    n, ar, aadj, wr = len(c), c['pnl_r'].mean(), c['pnl_r_adj'].mean(), c['win'].mean()*100
    print(f"  {nm:<35}  {n:>6,}  {ar:>7.3f}  {aadj:>9.3f}  {wr:>6.1f}%")

# Impact of engulfing on overall PH
engu_n    = len(engu_ph)
other_n   = len(ph) - engu_n
engu_r    = engu_ph['pnl_r_adj'].sum()
other_r   = ph[ph['pattern_name'] != 'engulfing_bullish']['pnl_r_adj'].sum()
print(f"\n  engulfing in PH: n={engu_n:,}  total R={engu_r:.1f}  (avg={engu_r/engu_n:.3f}R/trade)")
print(f"  altri in PH:     n={other_n:,}  total R={other_r:.1f}  (avg={other_r/other_n:.3f}R/trade)")
print(f"\n  Rimozione engulfing aumenta avg+slip da {all_ph['pnl_r_adj'].mean():.3f}R")
print(f"  a {no_engu['pnl_r_adj'].mean():.3f}R  (+{no_engu['pnl_r_adj'].mean()-all_ph['pnl_r_adj'].mean():.3f}R per trade)")

# ═══════════════════════════════════════════════════════════════════════════
# RIEPILOGO DECISIONALE
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("RIEPILOGO DECISIONALE — tutti i pattern")
print(SEP)

print(f"\n  PATTERN DA TENERE in Config A (PH 14-16):")
keep  = t2[t2['avg+slip'] > 0].sort_values('avg+slip', ascending=False)
discard = t2[t2['avg+slip'] <= 0].sort_values('avg+slip')
for _, row in keep.iterrows():
    ok = "✓ n>=30" if row['n'] >= 30 else "? n<30"
    print(f"    {row['pattern_name']:<28} {row['direction']:<9} n={row['n']:>4,}  avg+slip={row['avg+slip']:>7.3f}  {ok}")

print(f"\n  PATTERN DA SCARTARE in Config A (PH 14-16):")
for _, row in discard.iterrows():
    print(f"    {row['pattern_name']:<28} {row['direction']:<9} n={row['n']:>4,}  avg+slip={row['avg+slip']:>7.3f}")

print(f"\n=== DONE ===\n")
