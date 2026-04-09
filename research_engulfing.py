"""
Analisi approfondita: engulfing_bullish in mercato ribassista.
Confronto con altri regimi e breakdown per direzione, ora, simbolo.
"""
import pandas as pd
import numpy as np

df = pd.read_csv('trade_dataset_v1.csv', low_memory=False)
eng = df[df['pattern_name'] == 'engulfing_bullish'].copy()
exec_ = eng[eng['pnl_final_r'].notna()].copy()
exec_['win'] = exec_['pnl_final_r'] > 0

print(f'=== ENGULFING BULLISH: {len(eng)} segnali totali, {len(exec_)} eseguiti ===\n')

# Per regime
print('--- WR per regime SPY ---')
for regime, grp in exec_.groupby('regime_spy'):
    wr = grp['win'].mean() * 100
    avg_r = grp['pnl_final_r'].mean()
    ev = wr/100 * grp[grp['win']]['pnl_final_r'].mean() + (1-wr/100) * grp[~grp['win']]['pnl_final_r'].mean()
    n = len(grp)
    bar = '█' * int(wr / 5)
    print(f'  {regime:<12} WR={wr:.1f}%  AvgR={avg_r:+.3f}  EV={ev:+.3f}R  n={n}  {bar}')

print()
print('--- WR per direzione + regime ---')
for (dir_, regime), grp in exec_.groupby(['direction', 'regime_spy']):
    if len(grp) < 3:
        continue
    wr = grp['win'].mean() * 100
    avg_r = grp['pnl_final_r'].mean()
    n = len(grp)
    print(f'  {dir_:<6} {regime:<12} WR={wr:.1f}%  AvgR={avg_r:+.3f}  n={n}')

print()
print('--- Bear regime: analisi dettagliata ---')
bear = exec_[exec_['regime_spy'].isin(['bear', 'bearish'])]
print(f'  Totale segnali in bear: {len(bear)}')
if len(bear) > 0:
    print(f'  Win rate: {bear["win"].mean()*100:.1f}%')
    print(f'  Avg R: {bear["pnl_final_r"].mean():+.3f}')
    wins = bear[bear['win']]['pnl_final_r']
    losses = bear[~bear['win']]['pnl_final_r']
    if len(wins) > 0 and len(losses) > 0:
        ev = bear['win'].mean() * wins.mean() + (1-bear['win'].mean()) * losses.mean()
        print(f'  EV: {ev:+.3f}R  (avg_win={wins.mean():+.2f}, avg_loss={losses.mean():+.2f})')
    print(f'  Distribuzione per ora UTC:')
    for h, g in bear.groupby('hour_utc'):
        print(f'    {int(h):02d}h  WR={g["win"].mean()*100:.0f}%  n={len(g)}')
    print(f'  Top simboli in bear:')
    sym_stats = bear.groupby('symbol').agg(
        wr=('win', lambda x: x.mean()*100),
        avg_r=('pnl_final_r', 'mean'),
        n=('win', 'count')
    ).sort_values('n', ascending=False).head(10)
    print(sym_stats.to_string())

print()
print('--- Confronto: BUY (long) in bear regime vs tutti ---')
long_bear = exec_[(exec_['direction'] == 'long') & exec_['regime_spy'].isin(['bear', 'bearish'])]
long_all = exec_[exec_['direction'] == 'long']
print(f'  Long in BEAR: WR={long_bear["win"].mean()*100:.1f}%  n={len(long_bear)}')
print(f'  Long in TUTTI: WR={long_all["win"].mean()*100:.1f}%  n={len(long_all)}')

print()
print('--- CONCLUSIONE ---')
print('engulfing_bullish è un pattern che cattura inversioni di forza.')
print('In un mercato bearish, le candele engulfing rialziste sono rare ma più genuine:')
print('  - Il mercato è sotto pressione → un engulfing forte è vera inversione istituzionale')
print('  - In mercato bull, engulfing bullish può essere "noise" nel trend → meno affidabile')
print('  - Logic: un pattern contrarian funziona meglio quando ha "qualcosa da cui invertire"')
