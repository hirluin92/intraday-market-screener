import pandas as pd

df = pd.read_csv('trade_dataset_v1.csv', low_memory=False)
valid = df[df['pnl_final_r'].notna()].copy()
valid['win'] = valid['pnl_final_r'] > 0

periodo_min = str(valid['signal_timestamp'].min())[:10]
periodo_max = str(valid['signal_timestamp'].max())[:10]
print(f'Periodo dataset: {periodo_min} -> {periodo_max}')
print(f'Segnali totali con PnL: {len(valid)}')
print()

print('=== WR PER DIREZIONE + REGIME (filtri corretti: long/short, bull/bear) ===')
patterns = [
    'compression_to_expansion_transition',
    'rsi_momentum_continuation',
    'double_top',
    'double_bottom',
    'macd_divergence_bear',
    'rsi_divergence_bear',
    'macd_divergence_bull',
    'rsi_divergence_bull',
    'engulfing_bullish',
]

for pname in patterns:
    for direction, regime in [('long', 'bull'), ('short', 'bear'), ('long', 'neutral'), ('short', 'neutral'), ('short', 'bull'), ('long', 'bear')]:
        sub = valid[
            (valid['pattern_name'] == pname) &
            (valid['direction'] == direction) &
            (valid['regime_spy'] == regime)
        ]
        if len(sub) < 10:
            continue
        wr = sub['win'].mean() * 100
        ev = sub['pnl_final_r'].mean()
        avg_w = sub.loc[sub['win'], 'pnl_final_r'].mean() if sub['win'].any() else 0
        avg_l = sub.loc[~sub['win'], 'pnl_final_r'].mean() if (~sub['win']).any() else 0
        print(f'{pname[:32]:<32} [{direction:<5} {regime:<7}]  n={len(sub):>4}  WR={wr:5.1f}%  EV={ev:+.3f}R  avgW={avg_w:+.2f}  avgL={avg_l:+.2f}')

print()
print('=== STRATEGIA VECCHIA (compression+rsi_momentum, long in bull) ===')
sub_old = valid[
    valid['pattern_name'].isin(['compression_to_expansion_transition', 'rsi_momentum_continuation']) &
    (valid['direction'] == 'long') &
    (valid['regime_spy'] == 'bull')
]
wr_old = sub_old['win'].mean() * 100
ev_old = sub_old['pnl_final_r'].mean()
print(f'n={len(sub_old)}  WR={wr_old:.1f}%  EV={ev_old:+.3f}R')

print()
print('=== STRATEGIA NUOVA (tutti i pattern, direzione+regime allineati) ===')
new_patterns = [
    'compression_to_expansion_transition',
    'rsi_momentum_continuation',
    'double_top',
    'double_bottom',
    'macd_divergence_bear',
    'rsi_divergence_bear',
    'macd_divergence_bull',
    'rsi_divergence_bull',
    'engulfing_bullish',
]
sub_new = valid[
    valid['pattern_name'].isin(new_patterns) &
    (
        ((valid['direction'] == 'long') & (valid['regime_spy'].isin(['bull', 'neutral']))) |
        ((valid['direction'] == 'short') & (valid['regime_spy'].isin(['bear', 'neutral'])))
    )
]
wr_new = sub_new['win'].mean() * 100
ev_new = sub_new['pnl_final_r'].mean()
print(f'n={len(sub_new)}  WR={wr_new:.1f}%  EV={ev_new:+.3f}R')
