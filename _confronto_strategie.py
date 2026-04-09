"""
Confronto strategia VECCHIA vs NUOVA (modifiche di oggi).

VECCHIA:
  - Pattern: compression_to_expansion_transition + rsi_momentum_continuation
  - Solo LONG, solo regime BULL

NUOVA (modifiche di oggi):
  - Pattern: tutti i validati inclusi double_top, double_bottom,
    macd_divergence_bear/bull, rsi_divergence_bear/bull, engulfing_bullish
  - LONG in bull/neutral
  - SHORT in bear/neutral
  - macd_divergence_bear e rsi_divergence_bear ora attivi ANCHE in regime BEAR
"""
import pandas as pd

df = pd.read_csv('trade_dataset_v1.csv', low_memory=False)
valid = df[df['pnl_final_r'].notna()].copy()
valid['win'] = valid['pnl_final_r'] > 0

print(f'Dataset: {str(valid["signal_timestamp"].min())[:10]} -> {str(valid["signal_timestamp"].max())[:10]}')
print(f'Segnali totali con PnL: {len(valid)}')
print()

# ── Definizione strategie ────────────────────────────────────────────────────

# VECCHIA: solo compression + rsi_momentum, solo LONG in BULL
mask_old = (
    valid['pattern_name'].isin([
        'compression_to_expansion_transition',
        'rsi_momentum_continuation',
    ]) &
    (valid['direction'] == 'long') &
    (valid['regime_spy'] == 'bull')
)

# NUOVA: tutti i pattern validati con direzione+regime allineati
# compresi i SHORT ora abilitati in bear
PATTERNS_NEW = [
    'compression_to_expansion_transition',
    'rsi_momentum_continuation',
    'double_bottom',
    'double_top',
    'engulfing_bullish',
    'macd_divergence_bull',
    'rsi_divergence_bull',
    # Le due novità di oggi: ora attivi anche in bear regime
    'rsi_divergence_bear',
    'macd_divergence_bear',
]

mask_new = (
    valid['pattern_name'].isin(PATTERNS_NEW) &
    (
        # LONG: bull o neutral
        ((valid['direction'] == 'long') & (valid['regime_spy'].isin(['bull', 'neutral'])))
        |
        # SHORT: bear o neutral
        ((valid['direction'] == 'short') & (valid['regime_spy'].isin(['bear', 'neutral'])))
    )
)

# ── Calcolo metriche ─────────────────────────────────────────────────────────

def metriche(sub, label):
    n = len(sub)
    if n == 0:
        print(f'{label}: nessun dato')
        return
    wins = sub[sub['win']]
    losses = sub[~sub['win']]
    wr = sub['win'].mean() * 100
    ev = sub['pnl_final_r'].mean()
    avg_w = wins['pnl_final_r'].mean() if len(wins) else 0
    avg_l = losses['pnl_final_r'].mean() if len(losses) else 0
    pf = abs(wins['pnl_final_r'].sum() / losses['pnl_final_r'].sum()) if len(losses) else float('inf')
    tp1 = sub['tp1_hit'].sum() if 'tp1_hit' in sub.columns else 0
    tp2 = sub['tp2_hit'].sum() if 'tp2_hit' in sub.columns else 0
    sl  = sub['stop_hit'].sum() if 'stop_hit' in sub.columns else 0

    print(f'  Segnali:           {n}')
    print(f'  Win Rate:          {wr:.1f}%')
    print(f'  EV per trade:      {ev:+.3f}R')
    print(f'  Avg vincita:       {avg_w:+.3f}R')
    print(f'  Avg perdita:       {avg_l:+.3f}R')
    print(f'  Profit Factor:     {pf:.2f}')
    print(f'  TP1 raggiunti:     {tp1} ({tp1/n*100:.0f}%)')
    print(f'  TP2 raggiunti:     {tp2} ({tp2/n*100:.0f}%)')
    print(f'  Stop raggiunti:    {sl} ({sl/n*100:.0f}%)')

print('=' * 58)
print('  STRATEGIA VECCHIA')
print('  (compression + rsi_momentum | LONG | solo BULL)')
print('=' * 58)
metriche(valid[mask_old], 'VECCHIA')

print()
print('=' * 58)
print('  STRATEGIA NUOVA (modifiche di oggi)')
print('  (tutti i pattern validati | LONG+SHORT | bull+bear)')
print('=' * 58)
metriche(valid[mask_new], 'NUOVA')

# ── Dettaglio nuovi pattern SHORT in BEAR (la vera novità) ───────────────────
print()
print('=' * 58)
print('  NUOVI PATTERN SHORT in BEAR (la novità di oggi)')
print('=' * 58)
for pname in ['macd_divergence_bear', 'rsi_divergence_bear', 'double_top', 'compression_to_expansion_transition']:
    for direction, regime in [('short', 'bear'), ('short', 'neutral')]:
        sub = valid[
            (valid['pattern_name'] == pname) &
            (valid['direction'] == direction) &
            (valid['regime_spy'] == regime)
        ]
        if len(sub) < 5:
            continue
        wr = sub['win'].mean() * 100
        ev = sub['pnl_final_r'].mean()
        avg_w = sub.loc[sub['win'], 'pnl_final_r'].mean() if sub['win'].any() else 0
        avg_l = sub.loc[~sub['win'], 'pnl_final_r'].mean() if (~sub['win']).any() else 0
        print(f'  {pname[:32]:<32} [{direction}/{regime:<7}]  n={len(sub):>3}  WR={wr:5.1f}%  EV={ev:+.3f}R  W={avg_w:+.2f}  L={avg_l:+.2f}')

# ── Delta finale ─────────────────────────────────────────────────────────────
n_old = mask_old.sum()
n_new = mask_new.sum()
ev_old = valid[mask_old]['pnl_final_r'].mean()
ev_new = valid[mask_new]['pnl_final_r'].mean()
wr_old = valid[mask_old]['win'].mean() * 100
wr_new = valid[mask_new]['win'].mean() * 100

print()
print('=' * 58)
print('  DELTA: NUOVA vs VECCHIA')
print('=' * 58)
print(f'  Segnali:    {n_old} -> {n_new}  ({n_new - n_old:+d})')
print(f'  Win Rate:   {wr_old:.1f}% -> {wr_new:.1f}%  ({wr_new - wr_old:+.1f}pp)')
print(f'  EV/trade:   {ev_old:+.3f}R -> {ev_new:+.3f}R  ({ev_new - ev_old:+.3f}R)')
