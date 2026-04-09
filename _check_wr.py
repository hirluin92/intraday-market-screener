import pandas as pd

df = pd.read_csv('trade_dataset_v1.csv', low_memory=False)
valid = df[df['pnl_final_r'].notna()].copy()
valid['win'] = valid['pnl_final_r'] > 0

print('=== DIMENSIONI DATASET ===')
print(f'Totale segnali nel CSV: {len(df)}')
print(f'Con PnL finale: {len(valid)}')
if 'signal_timestamp' in df.columns:
    print(f'Periodo: {df["signal_timestamp"].min()} -> {df["signal_timestamp"].max()}')
print()

print('=== WR SENZA FILTRI ===')
for pname in ['compression_to_expansion_transition', 'rsi_momentum_continuation']:
    sub = valid[valid['pattern_name'] == pname]
    if len(sub) == 0:
        print(f'{pname}: nessun dato')
        continue
    wr = sub['win'].mean() * 100
    ev = sub['pnl_final_r'].mean()
    print(f'{pname}  n={len(sub)}  WR={wr:.1f}%  EV={ev:+.3f}R')

print()
print('=== WR PER DIREZIONE ===')
for pname in ['compression_to_expansion_transition', 'rsi_momentum_continuation']:
    for direction in ['bullish', 'bearish']:
        sub = valid[(valid['pattern_name'] == pname) & (valid['direction'] == direction)]
        if len(sub) < 10:
            continue
        wr = sub['win'].mean() * 100
        ev = sub['pnl_final_r'].mean()
        print(f'{pname[:38]} [{direction[:5]}]  n={len(sub):>4}  WR={wr:5.1f}%  EV={ev:+.3f}R')

print()
print('=== WR CON REGIME ALLINEATO ===')
for pname in ['compression_to_expansion_transition', 'rsi_momentum_continuation']:
    for direction in ['bullish', 'bearish']:
        cond = 'bull' if direction == 'bullish' else 'bear'
        if 'regime_spy' in valid.columns:
            mask = (
                (valid['pattern_name'] == pname) &
                (valid['direction'] == direction) &
                (valid['regime_spy'].astype(str).str.lower().str.contains(cond, na=False))
            )
            sub = valid[mask]
            if len(sub) < 5:
                continue
            wr = sub['win'].mean() * 100
            ev = sub['pnl_final_r'].mean()
            print(f'{pname[:35]} [{direction[:5]}+{cond}]  n={len(sub):>3}  WR={wr:5.1f}%  EV={ev:+.3f}R')

print()
print('=== WR NUOVI PATTERN (bear) CON REGIME ALLINEATO ===')
for pname in ['macd_divergence_bear', 'rsi_divergence_bear', 'double_top', 'double_bottom']:
    for direction, cond in [('bearish', 'bear'), ('bullish', 'bull')]:
        if 'regime_spy' in valid.columns:
            mask = (
                (valid['pattern_name'] == pname) &
                (valid['direction'] == direction) &
                (valid['regime_spy'].astype(str).str.lower().str.contains(cond, na=False))
            )
            sub = valid[mask]
            if len(sub) < 5:
                continue
            wr = sub['win'].mean() * 100
            ev = sub['pnl_final_r'].mean()
            print(f'{pname[:35]} [{direction[:5]}+{cond}]  n={len(sub):>3}  WR={wr:5.1f}%  EV={ev:+.3f}R')
