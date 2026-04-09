"""
Analisi: quali caratteristiche rendono compression_to_expansion e rsi_momentum
i pattern migliori? Da questi principi deduciamo cosa aggiungere.
"""
import pandas as pd
import numpy as np

df = pd.read_csv('trade_dataset_v1.csv', low_memory=False)
valid = df[df['pnl_final_r'].notna()].copy()
valid['win'] = valid['pnl_final_r'] > 0

top2 = valid[valid['pattern_name'].isin(['compression_to_expansion_transition','rsi_momentum_continuation'])]
others = valid[~valid['pattern_name'].isin(['compression_to_expansion_transition','rsi_momentum_continuation'])]

print('=== COSA HANNO IN COMUNE I PATTERN TOP vs GLI ALTRI? ===')
print()

for col in ['strength', 'atr_pct', 'volume_ratio', 'rsi_14', 'price_vs_vwap_pct',
            'candle_body_pct', 'ctx_candle_expansion', 'stop_distance_pct']:
    if col in valid.columns:
        t = top2[col].dropna()
        o = others[col].dropna()
        if col == 'ctx_candle_expansion':
            print(f'{col}:')
            print(f'  TOP2: {top2[col].value_counts(normalize=True).head(3).to_dict()}')
            print(f'  OTHER: {others[col].value_counts(normalize=True).head(3).to_dict()}')
        else:
            print(f'{col}: TOP2={t.mean():.3f}  ALTRI={o.mean():.3f}  diff={t.mean()-o.mean():.3f}')

print()
print('=== CORRELAZIONE FEATURE --> WR (tutti i segnali) ===')
num_cols = ['strength', 'atr_pct', 'volume_ratio', 'rsi_14',
            'candle_body_pct', 'stop_distance_pct', 'rr_tp1', 'quality_score',
            'price_position_in_range', 'dist_to_swing_low_pct', 'vix_close',
            'days_to_fomc', 'hour_utc', 'day_of_week']
corrs = []
for col in num_cols:
    if col in valid.columns:
        c2 = valid[[col, 'win']].dropna()
        if len(c2) > 100 and c2[col].std() > 0 and c2['win'].std() > 0:
            corr = c2[col].corr(c2['win'].astype(float))
            if not (corr != corr):  # not NaN
                corrs.append((col, corr, len(c2)))
corrs.sort(key=lambda x: abs(x[1]), reverse=True)
print('{:<35} {:>12}  {:>8}'.format('Feature', 'Corr con WR', 'n'))
for col, c, n in corrs:
    sign = '+' if c > 0 else '-'
    print('{:<35} {}{:.4f}        {:>7}'.format(col, sign, abs(c), n))
