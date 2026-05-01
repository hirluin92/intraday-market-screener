import pandas as pd
df = pd.read_csv('/app/data/val_5m_expanded.csv')
filled = df[df['entry_filled']==True]
for outcome in ['tp1','tp2','stop','timeout']:
    subset = filled[filled['outcome']==outcome]['pnl_r']
    if len(subset) > 0:
        print(f"{outcome}: n={len(subset)} mean={subset.mean():.3f} min={subset.min():.3f} p10={subset.quantile(0.10):.3f} p90={subset.quantile(0.90):.3f} max={subset.max():.3f}")

print()
# Check tp1 pnl_r distribution
tp1 = filled[filled['outcome']=='tp1']['pnl_r']
print("TP1 pnl_r value_counts (rounded to 1dp):")
print(tp1.round(1).value_counts().sort_index().head(15))
