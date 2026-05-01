"""
Monte Carlo 1h con pool aggiornato (44 simboli vs 39 precedenti).
Applica tutti i fix attivi: no 03/09 ET, strength>=0.60, risk_pct<=1.5%.
Confronto: vecchio pool (39) vs nuovo pool (44).
"""
import pandas as pd
import numpy as np
from datetime import UTC, datetime

try:
    from zoneinfo import ZoneInfo
    TZ_ET = ZoneInfo("America/New_York")
except Exception:
    TZ_ET = None

VALIDATED_PATTERNS_1H = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
    "engulfing_bullish",
})

OLD_39 = frozenset({
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
})
NEW_5 = frozenset({"MU","LUNR","CAT","AVGO","GS"})
NEW_44 = OLD_39 | NEW_5

SEP = "=" * 70

def hour_et(ts):
    if TZ_ET is not None:
        return ts.astimezone(TZ_ET).hour
    return (ts.hour - 4) % 24

# ── Load + filtri post-fix ────────────────────────────────────────────────
h = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
h = h[h["entry_filled"] == True].copy()
h = h[h["pattern_name"].isin(VALIDATED_PATTERNS_1H)].copy()
h["hour_et"] = h["pattern_timestamp"].apply(hour_et)

def apply_fixes(df):
    df = df[~df["hour_et"].isin([3, 9])].copy()               # FIX 7+8
    df = df[df["pattern_strength"] >= 0.60].copy()             # FIX 11
    df = df[df["risk_pct"] <= 1.5].copy()                      # FIX 12
    return df

def pool_stats(df, syms, label):
    g = df[df["symbol"].isin(syms)]
    g = apply_fixes(g)
    n = len(g)
    avg = g["pnl_r"].mean()
    wr = (g["pnl_r"] > 0).mean() * 100
    # periodo coperto
    months = 30  # 39k dataset = ~30 mesi
    trades_per_year = n / (months / 12)
    return dict(label=label, n=n, avg=avg, wr=wr,
                raw_per_year=trades_per_year)

print(SEP)
print("  POOL STATS POST-FIX: vecchio vs nuovo")
print(SEP)

old = pool_stats(h, OLD_39, "Pool 39 (vecchio)")
new = pool_stats(h, NEW_44, "Pool 44 (nuovo)")
inc = pool_stats(h, NEW_5,  "Soli 5 nuovi simboli")

for p in [old, new, inc]:
    print(f"\n  {p['label']}:")
    print(f"    n={p['n']:,}  avg_r={p['avg']:+.4f}R  WR={p['wr']:.1f}%")
    print(f"    freq raw/anno={p['raw_per_year']:.0f}  live@raw/4={p['raw_per_year']/4:.0f}")

print(f"\n  Delta avg_r: {new['avg']-old['avg']:+.4f}R")
print(f"  Delta trade/anno (live raw/4): +{(new['raw_per_year']-old['raw_per_year'])/4:.0f}")

# ── Monte Carlo ───────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  MONTE CARLO: vecchio 39 vs nuovo 44")
print("  EUR 2500 | 1% risk | slip=0.15R | 2000 sim | 12 mesi | raw/4")
print(SEP)

SLIP = 0.15
CAPITAL_START = 2500.0
RISK_PCT = 0.01
N_SIM = 2000
np.random.seed(42)

def run_mc(returns, trades_per_year, n_sim, capital, risk_pct, slip, label):
    net = returns - slip
    net = net[net > -3]  # rimuovi outlier estremi
    medians, worst5 = [], []
    for _ in range(n_sim):
        cap = capital
        sample = np.random.choice(net, size=int(trades_per_year), replace=True)
        for r in sample:
            stake = cap * risk_pct
            cap += stake * r
            if cap <= 0:
                cap = 0
                break
        medians.append(cap)
    medians = sorted(medians)
    med = np.median(medians)
    w5 = np.percentile(medians, 5)
    prob = sum(1 for x in medians if x > capital) / n_sim * 100
    print(f"\n  {label}:")
    print(f"    Mediana 12m: EUR {med:>10,.0f}  ({med/capital*100-100:>+.0f}%)")
    print(f"    Worst 5%:    EUR {w5:>10,.0f}  ({w5/capital*100-100:>+.0f}%)")
    print(f"    ProbProfit:  {prob:.1f}%")
    return med, w5

old_pool = apply_fixes(h[h["symbol"].isin(OLD_39)])
new_pool = apply_fixes(h[h["symbol"].isin(NEW_44)])

old_freq = len(old_pool) / (30/12) / 4   # raw/4
new_freq = len(new_pool) / (30/12) / 4

m_old, w_old = run_mc(old_pool["pnl_r"].values, old_freq, N_SIM,
                      CAPITAL_START, RISK_PCT, SLIP, "Pool 39 (vecchio)")
m_new, w_new = run_mc(new_pool["pnl_r"].values, new_freq, N_SIM,
                      CAPITAL_START, RISK_PCT, SLIP, "Pool 44 (nuovo)")

print(f"\n  Delta mediana: EUR {m_new-m_old:>+,.0f}  ({(m_new-m_old)/m_old*100:>+.1f}%)")
print(f"  Delta worst5%: EUR {w_new-w_old:>+,.0f}")

# ── Breakdown 5 nuovi simboli ─────────────────────────────────────────────
print(f"\n{SEP}")
print("  CONTRIBUTO DEI 5 NUOVI SIMBOLI (post-fix)")
print(SEP)
print(f"\n{'Simbolo':<7} {'n':>5} {'avg_r':>8} {'WR':>6} {'raw/a':>6} {'live/a':>7}")
print("-" * 45)
for sym in sorted(NEW_5):
    g = apply_fixes(h[h["symbol"] == sym])
    if len(g) == 0:
        print(f"{sym:<7}   n/a — nessun dato post-fix")
        continue
    n = len(g)
    avg = g["pnl_r"].mean()
    wr = (g["pnl_r"] > 0).mean() * 100
    raw_yr = n / (30/12)
    live_yr = raw_yr / 4
    print(f"{sym:<7} {n:>5,} {avg:>+8.3f}R {wr:>5.1f}% {raw_yr:>6.0f} {live_yr:>7.0f}")

print(f"\nFine MC aggiornato.")
