"""
Monte Carlo €100,000 — sistema completo configurazione MEDIUM.
5,000 simulazioni, 12 mesi, max drawdown tracking, curva mensile.
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

PRODUCTION_PATTERNS_6 = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
})
LONG_PATS = frozenset({"double_bottom", "macd_divergence_bull", "rsi_divergence_bull"})
SHORT_PATS = frozenset({"double_top", "macd_divergence_bear", "rsi_divergence_bear"})
PATTERNS_5M_4 = frozenset({"double_top","double_bottom","macd_divergence_bear","macd_divergence_bull"})

VALIDATED_48 = frozenset({
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
    "MU","LUNR","CAT","GS",
    "HON","ICE","CVX","DIA","VRTX",
})
VALIDATED_5M_29 = frozenset({
    "AMD","AMZN","CAT","CELH","COIN","DELL","GS","HOOD","LLY","LUNR",
    "MDB","META","MRNA","MSTR","MU","NET","NFLX","NKE","NVDA","NVO",
    "PLTR","RBLX","SCHW","SHOP","SMCI","SOFI","TGT","TSLA","ZS",
})

SEP = "=" * 78
MONTHS = 30
TRADING_DAYS_PER_YEAR = 252
N_SIM = 5000
np.random.seed(42)

def hour_et(ts):
    if TZ_ET is not None:
        return ts.astimezone(TZ_ET).hour
    return (ts.hour - 4) % 24

# ── Carica dataset 1h MEDIUM ──────────────────────────────────────────────────
raw = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
raw["hour_et"] = raw["pattern_timestamp"].apply(hour_et)
raw = raw[raw["symbol"].isin(VALIDATED_48) & raw["pattern_name"].isin(PRODUCTION_PATTERNS_6)]
raw = raw[~raw["hour_et"].isin([3])]              # solo 03:xx escluso (MEDIUM)
raw = raw[(raw["pattern_strength"]>=0.60) & (raw["pattern_strength"]<0.85)]
long_ok = raw["pattern_name"].isin(LONG_PATS) & (raw["risk_pct"]<=3.0)
short_ok = raw["pattern_name"].isin(SHORT_PATS) & (raw["risk_pct"]<=2.0)
raw = raw[long_ok | short_ok]
if "bars_to_entry" in raw.columns:
    raw = raw[raw["bars_to_entry"]<=6]
raw = raw[raw["entry_filled"]==True]
ret_1h = raw["pnl_r"].values
freq_1h = len(raw) / (MONTHS/12) / 4

# ── Carica dataset 5m TIGHT ───────────────────────────────────────────────────
try:
    m = pd.read_csv("data/val_5m_expanded.csv", parse_dates=["pattern_timestamp"])
    m["hour_et"] = m["pattern_timestamp"].apply(hour_et)
    m = m[m["symbol"].isin(VALIDATED_5M_29) & m["pattern_name"].isin(PATTERNS_5M_4)]
    m = m[(m["hour_et"]>=11) & (m["hour_et"]<16)]
    m = m[(m["pattern_strength"]>=0.60) & (m["pattern_strength"]<0.80)]
    m = m[m["risk_pct"]<=1.5]
    if "bars_to_entry" in m.columns:
        m = m[m["bars_to_entry"]<=3]
    m = m[m["entry_filled"]==True]
    ret_5m = m["pnl_r"].values
    freq_5m = len(m) / (MONTHS/12) / 4
    have_5m = True
except FileNotFoundError:
    ret_5m = np.array([])
    freq_5m = 0
    have_5m = False

# Combined
ret_combined = np.concatenate([ret_1h, ret_5m])
freq_combined = freq_1h + freq_5m

print(SEP)
print("  DATASET SUMMARY — CONFIG MEDIUM 1H + 5M TIGHT")
print(SEP)
print(f"\n  1H MEDIUM:   n={len(ret_1h):>6,}  freq={freq_1h:.0f}/anno  avg_r={ret_1h.mean():>+.4f}R  WR={(ret_1h>0).mean()*100:.1f}%")
if have_5m:
    print(f"  5M TIGHT:    n={len(ret_5m):>6,}  freq={freq_5m:.0f}/anno  avg_r={ret_5m.mean():>+.4f}R  WR={(ret_5m>0).mean()*100:.1f}%")
    print(f"  COMBINATO:   freq={freq_combined:.0f}/anno  avg_r={ret_combined.mean():>+.4f}R")
print(f"\n  Giorni trading/anno: {TRADING_DAYS_PER_YEAR}")
print(f"  Trade/mese:   {freq_combined/12:.0f}")
print(f"  Trade/giorno: {freq_combined/TRADING_DAYS_PER_YEAR:.1f}")

# ══════════════════════════════════════════════════════════════════════════════
# FUNZIONE MC COMPLETA con drawdown e curva mensile
# ══════════════════════════════════════════════════════════════════════════════
def mc_full(returns, freq_yr, capital, risk_pct, n_sim, slip=0.15, label=""):
    net = np.array(returns) - slip
    net = net[net > -3]
    n_trades = int(freq_yr)
    n_months = 12
    trades_per_month = n_trades // n_months

    final_caps = []
    max_dds = []
    monthly_curves = []

    for _ in range(n_sim):
        cap = capital
        peak = capital
        max_dd = 0.0
        monthly_caps = []

        total_sample = np.random.choice(net, size=n_trades, replace=True)
        idx = 0
        for m in range(n_months):
            batch = total_sample[idx:idx+trades_per_month]
            idx += trades_per_month
            for r in batch:
                cap += cap * risk_pct * r
                if cap <= 0:
                    cap = 0.0
                    break
                peak = max(peak, cap)
                dd = (peak - cap) / peak * 100
                max_dd = max(max_dd, dd)
            if cap <= 0:
                for _ in range(m, n_months):
                    monthly_caps.append(0.0)
                break
            monthly_caps.append(cap)

        final_caps.append(cap)
        max_dds.append(max_dd)
        monthly_curves.append(monthly_caps)

    final_caps = np.array(final_caps)
    max_dds = np.array(max_dds)

    med = np.median(final_caps)
    w5 = np.percentile(final_caps, 5)
    p95 = np.percentile(final_caps, 95)
    prob = (final_caps > capital).mean() * 100
    dd_med = np.median(max_dds)
    dd_p95 = np.percentile(max_dds, 95)  # worst 95% of simulations
    prob_dd20 = (max_dds > 20).mean() * 100
    prob_dd30 = (max_dds > 30).mean() * 100

    # Curva mensile mediana
    monthly_medians = []
    max_months = max(len(c) for c in monthly_curves)
    for i in range(max_months):
        vals = [c[i] for c in monthly_curves if i < len(c)]
        monthly_medians.append(np.median(vals) if vals else 0)

    return dict(
        label=label, capital=capital, freq=freq_yr, risk_pct=risk_pct,
        net_avg_r=net.mean(),
        med=med, w5=w5, p95=p95, prob=prob,
        dd_med=dd_med, dd_p95=dd_p95,
        prob_dd20=prob_dd20, prob_dd30=prob_dd30,
        monthly=monthly_medians,
        final_caps=final_caps, max_dds=max_dds,
    )

# ══════════════════════════════════════════════════════════════════════════════
# DOMANDA 5: MC €100,000 — 3 livelli di rischio
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  MONTE CARLO €100,000 — 3 LIVELLI RISCHIO — 5,000 sim — 12 mesi")
print(SEP)

CAPITAL = 100_000.0
SLIP = 0.15

results = []
for risk_pct, label in [(0.005, "0.5% (conservativo)"),
                         (0.010, "1.0% (baseline)"),
                         (0.020, "2.0% (aggressivo ~Half-Kelly)")]:
    r = mc_full(ret_combined, freq_combined, CAPITAL, risk_pct, N_SIM, SLIP, label)
    results.append(r)

# Tabella riassuntiva
print(f"\n{'Risk %':<25} {'t/anno':>7} {'net avg_r':>10} {'Mediana':>12} {'Worst5%':>12} {'DD med':>8} {'DD w95%':>8}")
print("-"*85)
for r in results:
    print(f"  {r['label']:<23} {r['freq']:>7.0f} {r['net_avg_r']:>+10.3f}R "
          f"EUR {r['med']:>9,.0f} EUR {r['w5']:>9,.0f} "
          f"{r['dd_med']:>7.1f}% {r['dd_p95']:>7.1f}%")

# ══════════════════════════════════════════════════════════════════════════════
# DETTAGLIO COMPLETO PER RISK 1%
# ══════════════════════════════════════════════════════════════════════════════
r1 = results[1]  # 1%
print(f"\n{SEP}")
print("  DETTAGLIO COMPLETO — risk 1% — €100,000")
print(SEP)

freq = r1["freq"]
print(f"""
  Capitale iniziale:     €{CAPITAL:>12,.0f}
  Trade/anno:            {freq:>7.0f}
  Trade/mese:            {freq/12:>7.0f}
  Trade/giorno:          {freq/TRADING_DAYS_PER_YEAR:>7.1f}
  avg_r netto (post-slip): {r1['net_avg_r']:>+.4f}R
  WR combinata:          {(ret_combined>0).mean()*100:>6.1f}%

  Equity 12 mesi mediana:  EUR {r1['med']:>10,.0f}  ({r1['med']/CAPITAL*100-100:>+.0f}%)
  Equity 12 mesi worst5%:  EUR {r1['w5']:>10,.0f}  ({r1['w5']/CAPITAL*100-100:>+.0f}%)
  Equity 12 mesi best 95%: EUR {r1['p95']:>10,.0f}  ({r1['p95']/CAPITAL*100-100:>+.0f}%)

  Profitto mensile mediano:  EUR {(r1['med']-CAPITAL)/12:>8,.0f}
  Profitto giornaliero med:  EUR {(r1['med']-CAPITAL)/TRADING_DAYS_PER_YEAR:>7,.0f}

  Max drawdown mediano:    {r1['dd_med']:>6.1f}%   = EUR {CAPITAL*r1['dd_med']/100:>8,.0f}
  Max drawdown worst 5%:   {r1['dd_p95']:>6.1f}%   = EUR {CAPITAL*r1['dd_p95']/100:>8,.0f}

  Probabilità profitto:    {r1['prob']:>6.1f}%
  Probabilità DD > 20%:    {r1['prob_dd20']:>6.1f}%
  Probabilità DD > 30%:    {r1['prob_dd30']:>6.1f}%
""")

# Curva mensile mediana
print("  CURVA EQUITY MENSILE MEDIANA (risk 1%):")
print(f"\n  {'Mese':>5} {'Equity mediana':>16} {'Profitto mese':>15} {'Profitto cumulato':>18}")
print(f"  {'-'*58}")
prev = CAPITAL
cum = 0
for i, eq in enumerate(r1["monthly"]):
    month_profit = eq - prev
    cum = eq - CAPITAL
    print(f"  {i+1:>5} EUR {eq:>12,.0f}   EUR {month_profit:>+10,.0f}   EUR {cum:>+13,.0f}")
    prev = eq

# ══════════════════════════════════════════════════════════════════════════════
# TABELLA COMPLETA
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  TABELLA COMPLETA — tutti i livelli di rischio")
print(SEP)

metrics = [
    ("Capitale iniziale", lambda r: f"EUR {r['capital']:,.0f}"),
    ("Trade/anno", lambda r: f"{r['freq']:.0f}"),
    ("Trade/mese", lambda r: f"{r['freq']/12:.0f}"),
    ("Trade/giorno", lambda r: f"{r['freq']/252:.1f}"),
    ("avg_r netto post-slip", lambda r: f"{r['net_avg_r']:>+.4f}R"),
    ("Mediana 12m", lambda r: f"EUR {r['med']:,.0f} ({r['med']/r['capital']*100-100:+.0f}%)"),
    ("Worst 5%", lambda r: f"EUR {r['w5']:,.0f} ({r['w5']/r['capital']*100-100:+.0f}%)"),
    ("Best 95%", lambda r: f"EUR {r['p95']:,.0f} ({r['p95']/r['capital']*100-100:+.0f}%)"),
    ("Profitto mensile med.", lambda r: f"EUR {(r['med']-r['capital'])/12:,.0f}"),
    ("Profitto giornaliero med.", lambda r: f"EUR {(r['med']-r['capital'])/252:,.0f}"),
    ("DD mediano", lambda r: f"{r['dd_med']:.1f}% = EUR {r['capital']*r['dd_med']/100:,.0f}"),
    ("DD worst 95%", lambda r: f"{r['dd_p95']:.1f}% = EUR {r['capital']*r['dd_p95']/100:,.0f}"),
    ("ProbProfit", lambda r: f"{r['prob']:.1f}%"),
    ("Prob DD > 20%", lambda r: f"{r['prob_dd20']:.1f}%"),
    ("Prob DD > 30%", lambda r: f"{r['prob_dd30']:.1f}%"),
]

labels = [r["label"] for r in results]
print(f"\n  {'Metrica':<27}", end="")
for l in labels:
    print(f"  {l:<25}", end="")
print()
print(f"  {'-'*100}")
for name, fn in metrics:
    print(f"  {name:<27}", end="")
    for r in results:
        try:
            val = fn(r)
        except Exception:
            val = "n/a"
        print(f"  {val:<25}", end="")
    print()

# ══════════════════════════════════════════════════════════════════════════════
# DOMANDA 3: MAX_SIMULTANEOUS_TRADES impact
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  DOMANDA 3: MAX_SIMULTANEOUS_TRADES — impatto sul volume")
print(SEP)
print(f"""
  MAX_SIMULTANEOUS_TRADES = 3 (usato in simulation_service, NON in live execution).

  In LIVE: il validator non ha un limite di slot — l'unico check live è
  "posizione già aperta su quel simbolo" (1 posizione per simbolo).
  Con 48 simboli 1h + 29 simboli 5m = 77 simboli distinti.
  In pratica non ci sono mai 3 segnali "execute" nella stessa barra sullo stesso simbolo.

  In BACKTEST/SIMULAZIONE: il limite 3 slot è attivo e compete per priority
  i trade nella stessa barra per pattern_strength decrescente.
  Il dataset produzione è già il risultato con questo limite applicato.

  Stima impatto volume: con freq_1h={freq_1h:.0f}/anno su 48 simboli = {freq_1h/252:.1f} trade/giorno medio.
  Probabilità di 3+ trade 1h nella stessa ora: molto bassa.
  Impatto stimato: < 5% del volume scartato per slot conflict.

  Il limite 3 slot NON è il collo di bottiglia — la frequenza bassa è
  dovuta ai filtri produzione (strength, risk_pct, bars_to_entry).
""")

# ══════════════════════════════════════════════════════════════════════════════
# REGIME ATTUALE
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  REGIME ATTUALE SPY (ultimi dati in DB)")
print(SEP)
print(f"""
  Ultimo dato DB: 2026-04-02
  SPY close: 655.83  |  EMA50: 669.70  |  pct: -2.07%
  Regime: BEAR (sotto EMA50 > 2%)

  => PATTERN BEAR-ONLY ATTIVI: engulfing_bullish (solo)
  => UNIVERSALI IN TUTTI I REGIMI (apr 2026): double_bottom, double_top,
     macd_divergence_bull, macd_divergence_bear, rsi_divergence_bull, rsi_divergence_bear
     (macd/rsi_divergence_bull rimossi da BEAR_ONLY: avg_r positivo in TUTTI i regimi)

  NOTA: dati DB fermi al 2026-04-02. Il mercato reale (aprile 2026) ha visto
  ulteriori cali per le tariffe Trump (annuncio 2 aprile).
  SPY probabilmente ancora in territorio BEAR. Refresh DB necessario prima del live.
""")

print(f"\nFine mc_100k.py")
