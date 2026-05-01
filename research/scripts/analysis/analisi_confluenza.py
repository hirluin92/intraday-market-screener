"""
AZIONE 3: Analisi confluenza sul dataset produzione.

Il CSV non ha colonna "confluence" — ogni riga e' un pattern singolo.
Confluenza viene ricostruita raggruppando per (symbol, pattern_timestamp):
N pattern distinti rilevati sullo stesso simbolo nella stessa barra = confluenza N.

Risponde anche alla domanda: il dataset produzione include trade a confluenza 1?
(Risposta: SI, perche' build_validation_dataset.py non applica nessun filtro confluenza.)
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

try:
    from zoneinfo import ZoneInfo
    TZ_ET = ZoneInfo("America/New_York")
except Exception:
    TZ_ET = None

PRODUCTION_PATTERNS = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
})

SEP = "=" * 74

def hour_et(ts):
    if TZ_ET is not None:
        return ts.astimezone(TZ_ET).hour
    return (ts.hour - 4) % 24

# ── Carica dataset produzione ────────────────────────────────────────────────
prod = pd.read_csv("data/val_1h_production.csv", parse_dates=["pattern_timestamp"])
print(f"Dataset produzione: {len(prod):,} trade\n")

# ── Ricostruisci confluenza da (symbol, timestamp) ───────────────────────────
# Conta quanti pattern distinti per ogni barra (symbol + timestamp)
bar_counts = prod.groupby(["symbol", "pattern_timestamp"])["pattern_name"].count().rename("n_patterns_bar")
prod = prod.join(bar_counts, on=["symbol", "pattern_timestamp"])

# Verifica: il dataset grezzo (tutti i pattern, no solo produzione) puo' avere
# convergenza piu' alta — qui usiamo solo quelli che superano i filtri produzione
print(SEP)
print("  DISTRIBUZIONE CONFLUENZA nel dataset produzione")
print(SEP)
print(f"\n  (Confluenza = n pattern VALIDATI che passano i filtri produzione")
print(f"   nella stessa barra per lo stesso simbolo)\n")

conf_dist = prod["n_patterns_bar"].value_counts().sort_index()
total = len(prod)
for conf, n in conf_dist.items():
    pct = n / total * 100
    avg = prod[prod["n_patterns_bar"] == conf]["pnl_r"].mean()
    wr = (prod[prod["n_patterns_bar"] == conf]["pnl_r"] > 0).mean() * 100
    print(f"  Confluenza {conf}: n={n:>6,} ({pct:>5.1f}%)  avg_r={avg:>+.4f}R  WR={wr:.1f}%")

print(f"\n  TOTALE: {total:,} trade")

# ── avg_r per livello di confluenza ─────────────────────────────────────────
print(f"\n{SEP}")
print("  avg_r PER LIVELLO CONFLUENZA — confronto 1 vs 2+")
print(SEP)

c1 = prod[prod["n_patterns_bar"] == 1]
c2p = prod[prod["n_patterns_bar"] >= 2]

print(f"\n  Confluenza 1 (singolo pattern):  n={len(c1):>5,}  avg_r={c1['pnl_r'].mean():>+.4f}R  WR={(c1['pnl_r']>0).mean()*100:.1f}%")
print(f"  Confluenza 2+ (multi pattern):   n={len(c2p):>5,}  avg_r={c2p['pnl_r'].mean():>+.4f}R  WR={(c2p['pnl_r']>0).mean()*100:.1f}%")
print(f"  Delta (2+ vs 1):                         {c2p['pnl_r'].mean()-c1['pnl_r'].mean():>+.4f}R")

# ── avg_r per pattern E confluenza ──────────────────────────────────────────
print(f"\n{SEP}")
print("  avg_r PER PATTERN E CONFLUENZA")
print(SEP)

print(f"\n{'Pattern':<36} {'n_tot':>6} {'avg_all':>8} {'n_conf1':>7} {'avg_c1':>8} {'n_conf2+':>8} {'avg_c2+':>9}")
print("-" * 88)

for pn in sorted(PRODUCTION_PATTERNS):
    g = prod[prod["pattern_name"] == pn]
    if len(g) == 0:
        continue
    g1 = g[g["n_patterns_bar"] == 1]
    g2 = g[g["n_patterns_bar"] >= 2]
    avg_all = g["pnl_r"].mean()
    avg_c1 = g1["pnl_r"].mean() if len(g1) > 0 else float("nan")
    avg_c2 = g2["pnl_r"].mean() if len(g2) > 0 else float("nan")
    c1_s = f"{avg_c1:>+8.3f}R" if not pd.isna(avg_c1) else "     n/a"
    c2_s = f"{avg_c2:>+9.3f}R" if not pd.isna(avg_c2) else "      n/a"
    print(f"{pn:<36} {len(g):>6} {avg_all:>+8.3f}R {len(g1):>7} {c1_s} {len(g2):>8} {c2_s}")

# ── Quanti trade PERDIAMO con filtro confluenza >= 2? ───────────────────────
print(f"\n{SEP}")
print("  IMPATTO FILTRO CONFLUENZA >= 2 (vecchio FIX pre-apr 2026)")
print(SEP)

n_conf1_only = len(c1)  # trade che verrebbero persi se applicassimo >= 2
n_conf2p = len(c2p)
print(f"\n  Con confluenza >= 2 (vecchio filtro):")
print(f"    Trade eseguiti: {n_conf2p:,}  ({n_conf2p/total*100:.1f}% del totale)")
print(f"    Trade persi:    {n_conf1_only:,}  ({n_conf1_only/total*100:.1f}% del totale)")
print(f"    avg_r tenuti (>=2): {c2p['pnl_r'].mean():>+.4f}R")
print(f"    avg_r persi   (=1): {c1['pnl_r'].mean():>+.4f}R")

print(f"\n  Con confluenza >= 1 (attuale — nessun filtro):")
print(f"    Trade eseguiti: {total:,} (100%)")
print(f"    avg_r: {prod['pnl_r'].mean():>+.4f}R  WR={(prod['pnl_r']>0).mean()*100:.1f}%")

# ── Convergenza nel dataset GREZZO ──────────────────────────────────────────
# (per capire quanti pattern per barra ci sono PRIMA dei filtri produzione)
print(f"\n{SEP}")
print("  CONFLUENZA NEL DATASET GREZZO (6 pattern, entry_filled, no altri filtri)")
print(SEP)

raw = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
raw = raw[(raw["entry_filled"] == True) & (raw["pattern_name"].isin(PRODUCTION_PATTERNS))].copy()
raw["hour_et"] = raw["pattern_timestamp"].apply(hour_et)

bar_raw = raw.groupby(["symbol", "pattern_timestamp"])["pattern_name"].count().rename("n_raw")
raw = raw.join(bar_raw, on=["symbol", "pattern_timestamp"])

raw_dist = raw["n_raw"].value_counts().sort_index()
for conf, n in raw_dist.items():
    pct = n / len(raw) * 100
    avg = raw[raw["n_raw"] == conf]["pnl_r"].mean()
    wr = (raw[raw["n_raw"] == conf]["pnl_r"] > 0).mean() * 100
    print(f"  Confluenza {conf}: n={n:>6,} ({pct:>5.1f}%)  avg_r={avg:>+.4f}R  WR={wr:.1f}%")

print(f"\n  Totale grezzo (6 pattern, entry_filled): {len(raw):,}")

# ── Effetto del vecchio filtro confluenza >= 2 sul dataset grezzo ────────────
raw_c1 = raw[raw["n_raw"] == 1]
raw_c2p = raw[raw["n_raw"] >= 2]
print(f"\n  Con confluenza >= 2 su dataset grezzo:")
print(f"    Trade eseguiti: {len(raw_c2p):,}  avg_r={raw_c2p['pnl_r'].mean():>+.4f}R")
print(f"    Trade persi:    {len(raw_c1):,}  avg_r={raw_c1['pnl_r'].mean():>+.4f}R")

# ── Scenario: quanti trade aggiuntivi con confluenza = 1 (gia' inclusi ora)? ─
print(f"\n{SEP}")
print("  RIEPILOGO: GIA' RISOLTO CON FIX 10 (SIGNAL_MIN_CONFLUENCE = 1)")
print(SEP)
print(f"""
  FIX 10 apr 2026 ha gia' impostato SIGNAL_MIN_CONFLUENCE = 1.
  Il validator attuale NON filtra per confluenza.

  Il dataset produzione include trade a confluenza 1:
    n={n_conf1_only:,} trade a confluenza 1  avg_r={c1['pnl_r'].mean():>+.4f}R
    n={n_conf2p:,} trade a confluenza 2+  avg_r={c2p['pnl_r'].mean():>+.4f}R

  Conclusione: confluenza 1 ha avg_r {c1['pnl_r'].mean()-c2p['pnl_r'].mean():>+.4f}R rispetto a 2+.
  Il FIX 10 era corretto — mantenerlo.
""")

# ── Quanti trade in piu' con risk_pct <= 3% per LONG? ───────────────────────
print(SEP)
print("  SCENARIO COMBINATO: risk_pct differenziato + tutti i simboli sbloccati")
print(SEP)

LONG_PATS = {"double_bottom", "macd_divergence_bull", "rsi_divergence_bull"}
SHORT_PATS = {"double_top", "macd_divergence_bear", "rsi_divergence_bear"}

VALIDATED_NEW = frozenset({
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
    "MU","LUNR","CAT","GS",
    "HON","ICE","CVX","DIA","VRTX",  # sbloccati apr 2026
})

try:
    from zoneinfo import ZoneInfo
    TZ_ET2 = ZoneInfo("America/New_York")
except Exception:
    TZ_ET2 = None

raw2 = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
raw2 = raw2[(raw2["entry_filled"] == True) & (raw2["pattern_name"].isin(PRODUCTION_PATTERNS))].copy()
raw2["hour_et"] = raw2["pattern_timestamp"].apply(hour_et)
raw2 = raw2[raw2["symbol"].isin(VALIDATED_NEW)]
raw2 = raw2[~raw2["hour_et"].isin([3, 9])]
raw2 = raw2[(raw2["pattern_strength"] >= 0.60) & (raw2["pattern_strength"] < 0.80)]
if "bars_to_entry" in raw2.columns:
    raw2 = raw2[raw2["bars_to_entry"] <= 4]

# Scenario A: 1.5% per tutti (vecchio)
scen_a = raw2[raw2["risk_pct"] <= 1.5]

# Scenario B: 3% per LONG, 1.5% per SHORT (nuovo)
long_mask = raw2["pattern_name"].isin(LONG_PATS)
short_mask = raw2["pattern_name"].isin(SHORT_PATS)
scen_b = pd.concat([
    raw2[long_mask & (raw2["risk_pct"] <= 3.0)],
    raw2[short_mask & (raw2["risk_pct"] <= 1.5)],
])

months = 30
fa = len(scen_a) / (months/12) / 4
fb = len(scen_b) / (months/12) / 4

print(f"\n  Pool: {len(VALIDATED_NEW)} simboli (43 VALIDATED + 5 sbloccati)\n")
print(f"  {'':30} {'n':>7} {'avg_r':>8} {'WR':>6} {'live/anno':>10}")
print(f"  {'-'*65}")
print(f"  {'A: risk <= 1.5% (vecchio)':30} {len(scen_a):>7,} {scen_a['pnl_r'].mean():>+8.4f}R {(scen_a['pnl_r']>0).mean()*100:>5.1f}% {fa:>10.0f}")
print(f"  {'B: LONG<=3% / SHORT<=1.5%':30} {len(scen_b):>7,} {scen_b['pnl_r'].mean():>+8.4f}R {(scen_b['pnl_r']>0).mean()*100:>5.1f}% {fb:>10.0f}")
print(f"\n  Trade aggiuntivi B vs A: +{len(scen_b)-len(scen_a):,}")
print(f"  avg_r margine (trade extra): {scen_b[~scen_b.index.isin(scen_a.index)]['pnl_r'].mean():>+.4f}R")

# ── Monte Carlo rapido ────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  MONTE CARLO — EUR 2500 | 1% risk | slip=0.15R | 2000 sim | 12 mesi")
print(SEP)

SLIP = 0.15
CAPITAL = 2500.0
RISK_PCT_MC = 0.01
N_SIM = 2000
np.random.seed(42)

def run_mc(returns, freq_yr, label):
    net = returns - SLIP
    net = net[net > -3]
    caps = []
    for _ in range(N_SIM):
        cap = CAPITAL
        sample = np.random.choice(net, size=int(freq_yr), replace=True)
        for r in sample:
            cap += cap * RISK_PCT_MC * r
            if cap <= 0:
                cap = 0
                break
        caps.append(cap)
    med = np.median(caps)
    w5 = np.percentile(caps, 5)
    prob = sum(1 for x in caps if x > CAPITAL) / N_SIM * 100
    print(f"\n  {label}:")
    print(f"    Mediana: EUR {med:>10,.0f}  ({med/CAPITAL*100-100:>+.0f}%)")
    print(f"    Worst5%: EUR {w5:>10,.0f}  ({w5/CAPITAL*100-100:>+.0f}%)")
    print(f"    ProbProfit: {prob:.1f}%")
    return med, w5

run_mc(scen_a["pnl_r"].values, fa, f"A: risk<=1.5%, 43 sym, freq={fa:.0f}/anno")
run_mc(scen_b["pnl_r"].values, fb, f"B: LONG<=3%/SHORT<=1.5%, 48 sym, freq={fb:.0f}/anno")

print(f"\nFine analisi confluenza.")
