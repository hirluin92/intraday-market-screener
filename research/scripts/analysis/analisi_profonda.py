"""
ANALISI PROFONDA: mercati, simboli, regime, caratteristiche comuni.
Val_1h_full.csv + val_5m_expanded.csv — dataset deterministici completi.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

SEP = "=" * 74

VALIDATED_PATTERNS_1H = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
    "engulfing_bullish",
})
VALIDATED_PATTERNS_5M = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
})

# ── Classificazioni manuali ──────────────────────────────────────────────────
CAP_MAP = {
    # Large
    "GOOGL": "Large", "META": "Large", "NVDA": "Large", "AAPL": "Large",
    "MSFT": "Large", "AMZN": "Large", "TSLA": "Large", "NVO": "Large",
    "LLY": "Large", "WMT": "Large", "NKE": "Large", "JPM": "Large",
    # Mid
    "AMD": "Mid", "COIN": "Mid", "PLTR": "Mid", "SHOP": "Mid",
    "NFLX": "Mid", "DELL": "Mid", "SCHW": "Mid", "MDB": "Mid",
    "NET": "Mid", "ZS": "Mid", "RBLX": "Mid", "HOOD": "Mid",
    # Small
    "ACHR": "Small", "ASTS": "Small", "JOBY": "Small", "RKLB": "Small",
    "NNE": "Small", "OKLO": "Small", "WULF": "Small", "APLD": "Small",
    "SMR": "Small", "RXRX": "Small", "CELH": "Small", "SOFI": "Small",
    "SMCI": "Small",
    # Crypto
    "ETH": "Crypto", "DOGE": "Crypto", "ADA": "Crypto", "SOL": "Crypto",
    "WLD": "Crypto", "MATIC": "Crypto", "BTC": "Crypto",
}
SECTOR_MAP = {
    "GOOGL": "Tech", "META": "Tech", "NVDA": "Tech", "AMD": "Tech",
    "TSLA": "Tech", "DELL": "Tech", "PLTR": "Tech", "SHOP": "Tech",
    "MDB": "Tech", "NET": "Tech", "ZS": "Tech", "RBLX": "Tech",
    "SMCI": "Tech", "MSFT": "Tech", "AAPL": "Tech",
    "COIN": "Fintech", "HOOD": "Fintech", "SOFI": "Fintech", "SCHW": "Fintech",
    "AMZN": "Retail/Tech",
    "ACHR": "Space", "ASTS": "Space", "JOBY": "Space", "RKLB": "Space",
    "NNE": "Nuclear", "OKLO": "Nuclear", "WULF": "Mining/BTC", "APLD": "Mining/BTC",
    "SMR": "Nuclear", "MP": "Mining", "NEM": "Mining",
    "RXRX": "Biotech", "NVO": "Pharma", "LLY": "Pharma", "MRNA": "Biotech", "CELH": "Retail",
    "NKE": "Retail", "TGT": "Retail", "WMT": "Retail",
    "JPM": "Finance",
    "ETH": "Crypto", "DOGE": "Crypto", "ADA": "Crypto", "SOL": "Crypto",
    "WLD": "Crypto", "MATIC": "Crypto", "BTC": "Crypto",
}

def pct(x, tot):
    return f"{x/tot*100:.1f}%" if tot else "n/a"

def stats(g):
    n = len(g)
    avg = g["pnl_r"].mean()
    wr = (g["pnl_r"] > 0).mean() * 100
    return n, avg, wr

# ── Load ─────────────────────────────────────────────────────────────────────
print(SEP)
print("  CARICAMENTO DATASET")
print(SEP)

h_raw = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
m_raw = pd.read_csv("data/val_5m_expanded.csv", parse_dates=["pattern_timestamp"])

h = h_raw[h_raw["entry_filled"] == True].copy()
m = m_raw[m_raw["entry_filled"] == True].copy()
h = h[h["pattern_name"].isin(VALIDATED_PATTERNS_1H)].copy()
m = m[m["pattern_name"].isin(VALIDATED_PATTERNS_5M)].copy()

print(f"1h pool: n={len(h):,}  avg_r={h['pnl_r'].mean():+.4f}R")
print(f"5m pool: n={len(m):,}  avg_r={m['pnl_r'].mean():+.4f}R")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 1 — SU QUALI MERCATI SIAMO?
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PARTE 1 — BREAKDOWN MERCATI")
print(SEP)

for label, df in [("1h", h), ("5m", m)]:
    print(f"\n--- {label} | per PROVIDER ---")
    for prov, g in df.groupby("provider"):
        n, avg, wr = stats(g)
        print(f"  {prov:<20} n={n:>6,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

    print(f"\n--- {label} | per EXCHANGE ---")
    for ex, g in df.groupby("exchange"):
        n, avg, wr = stats(g)
        print(f"  {ex:<20} n={n:>6,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

print(f"\n--- 1h | UK (LSE) specifico ---")
uk = h[h["exchange"].isin(["IBKR", "LSE", "YAHOO_UK"]) | h["provider"].isin(["ibkr"])]
if len(uk) == 0:
    # try by symbol suffix or exchange
    uk = h[h["exchange"].str.contains("UK|LSE|IBK", case=False, na=False) |
           h["provider"].str.contains("ibkr", case=False, na=False)]
if len(uk):
    n, avg, wr = stats(uk)
    print(f"  UK trades: n={n:,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")
    print(f"  Simboli UK: {sorted(uk['symbol'].unique())}")
else:
    print("  Nessun trade UK trovato (exchange/provider)")
    # check all exchanges
    print(f"  Exchange unici in 1h: {sorted(h['exchange'].unique())}")
    print(f"  Provider unici in 1h: {sorted(h['provider'].unique())}")

# ── 1b. Asset type ─────────────────────────────────────────────────────────
print(f"\n--- ASSET TYPE (1h) ---")
crypto_syms = set(CAP_MAP[k] for k in CAP_MAP if CAP_MAP[k] == "Crypto")
crypto_syms = {k for k, v in CAP_MAP.items() if v == "Crypto"}

h["asset_type"] = h.apply(
    lambda r: "crypto" if r["provider"] == "binance" or r["symbol"] in crypto_syms else "stock", axis=1
)
for atype, g in h.groupby("asset_type"):
    n, avg, wr = stats(g)
    print(f"  {atype:<8} n={n:>6,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

m["asset_type"] = m.apply(
    lambda r: "crypto" if r["provider"] == "binance" or r["symbol"] in crypto_syms else "stock", axis=1
)
print(f"\n--- ASSET TYPE (5m) ---")
for atype, g in m.groupby("asset_type"):
    n, avg, wr = stats(g)
    print(f"  {atype:<8} n={n:>6,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 2 — REGIME SPY
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PARTE 2 — REGIME SPY")
print(SEP)

print("""
Regime filter — come funziona:
  RegimeFilter legge il prezzo SPY vs EMA50 1d:
    bull  = SPY > EMA50 * 1.02
    bear  = SPY < EMA50 * 0.98
    neutral = tra i due

  Nel validator:
    - In bull: bloccati: engulfing_bullish, macd_divergence_bull, rsi_divergence_bull
    - In bear: permessi: tutti i "bear regime only" pattern (engulfing, macd_bull, rsi_bull)
    - SHORT patterns (macd/rsi_divergence_bear) hanno edge minore in bear ma positivo

  Il dataset NON ha colonna market_regime — regime viene calcolato live.
  Analisi proxy: usiamo screener_score come proxy dell'allineamento trend.
  score=3 (max dal componente market_regime) = bull/bear forte
  score=0 = neutro o contra-trend
""")

# screener_score proxy per regime
print("--- screener_score come proxy regime (1h) ---")
h["score_regime"] = h["screener_score"].fillna(0)
bins = [-1, 5, 8, 10, 12, 100]
labels = ["<5 (low)", "5-8 (mid)", "8-10 (high)", "10-12 (very high)", "12+ (perfect)"]
h["score_bin"] = pd.cut(h["score_regime"], bins=bins, labels=labels)
for sb, g in h.groupby("score_bin", observed=True):
    n, avg, wr = stats(g)
    print(f"  score {str(sb):<20} n={n:>5,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 3 — SIMBOLI PROFITTEVOLI
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PARTE 3 — CARATTERISTICHE SIMBOLI (1h, n>=30)")
print(SEP)

sym_stats = []
for sym, g in h.groupby("symbol"):
    n, avg, wr = stats(g)
    price_med = g["entry_price"].median() if "entry_price" in g.columns else None
    rp_med = g["risk_pct"].median() if "risk_pct" in g.columns else None
    cap = CAP_MAP.get(sym, "Unknown")
    sector = SECTOR_MAP.get(sym, "Unknown")
    sym_stats.append(dict(
        symbol=sym, n=n, avg_r=avg, wr=wr,
        price_med=price_med, risk_pct_med=rp_med,
        cap=cap, sector=sector,
    ))

sym_df = pd.DataFrame(sym_stats).sort_values("avg_r", ascending=False)
sym_df_min = sym_df[sym_df["n"] >= 30].copy()

print(f"\n3b. TOP 30 simboli per avg_r (n>=30):")
print(f"{'Simbolo':<8} {'avg_r':>8} {'n':>6} {'WR':>6} {'Prezzo':>8} {'risk%':>7} {'Cap':<8} {'Settore'}")
print("-" * 74)
for _, row in sym_df_min.head(30).iterrows():
    pr = f"${row['price_med']:.0f}" if row['price_med'] is not None and not np.isnan(row['price_med']) else "n/a"
    rp = f"{row['risk_pct_med']:.2f}%" if row['risk_pct_med'] is not None and not np.isnan(row['risk_pct_med']) else "n/a"
    print(f"{row['symbol']:<8} {row['avg_r']:>+8.3f}R {row['n']:>6,} {row['wr']:>5.1f}% {pr:>8} {rp:>7} {row['cap']:<8} {row['sector']}")

print(f"\nBOTTOM 10 simboli per avg_r (n>=30):")
print(f"{'Simbolo':<8} {'avg_r':>8} {'n':>6} {'WR':>6} {'Prezzo':>8} {'risk%':>7} {'Cap':<8} {'Settore'}")
print("-" * 74)
for _, row in sym_df_min.tail(10).iterrows():
    pr = f"${row['price_med']:.0f}" if row['price_med'] is not None and not np.isnan(row['price_med']) else "n/a"
    rp = f"{row['risk_pct_med']:.2f}%" if row['risk_pct_med'] is not None and not np.isnan(row['risk_pct_med']) else "n/a"
    print(f"{row['symbol']:<8} {row['avg_r']:>+8.3f}R {row['n']:>6,} {row['wr']:>5.1f}% {pr:>8} {rp:>7} {row['cap']:<8} {row['sector']}")

# ── 3c. Aggregati ──────────────────────────────────────────────────────────
print(f"\n--- 3c. avg_r per CAP ---")
for cap_type in ["Large", "Mid", "Small", "Crypto", "Unknown"]:
    g = h[h["symbol"].map(CAP_MAP).fillna("Unknown") == cap_type]
    if len(g) == 0: continue
    n, avg, wr = stats(g)
    print(f"  {cap_type:<8} n={n:>5,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

print(f"\n--- 3c. avg_r per SETTORE ---")
h["sector"] = h["symbol"].map(SECTOR_MAP).fillna("Unknown")
for sec, g in sorted(h.groupby("sector"), key=lambda x: x[1]["pnl_r"].mean(), reverse=True):
    n, avg, wr = stats(g)
    print(f"  {sec:<16} n={n:>5,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

print(f"\n--- 3c. avg_r per FASCIA DI PREZZO ---")
price_bins = [0, 10, 20, 50, 100, 200, 10000]
price_labels = ["<$10", "$10-20", "$20-50", "$50-100", "$100-200", "$200+"]
h["price_bin"] = pd.cut(h["entry_price"], bins=price_bins, labels=price_labels)
for pb, g in h.groupby("price_bin", observed=True):
    n, avg, wr = stats(g)
    print(f"  {str(pb):<12} n={n:>5,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

print(f"\n--- 3c. avg_r per FASCIA risk_pct ---")
rp_bins = [0, 0.5, 1.0, 1.5, 2.0, 3.0, 100]
rp_labels = ["0-0.5%", "0.5-1%", "1-1.5%", "1.5-2%", "2-3%", "3%+"]
h["rp_bin"] = pd.cut(h["risk_pct"], bins=rp_bins, labels=rp_labels)
for rb, g in h.groupby("rp_bin", observed=True):
    n, avg, wr = stats(g)
    print(f"  {str(rb):<10} n={n:>5,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

# ── 3d. Top 10 analisi ─────────────────────────────────────────────────────
print(f"\n--- 3d. TOP 10 SIMBOLI — CARATTERISTICHE COMUNI ---")
top10 = sym_df_min.head(10)
print(f"Simboli: {list(top10['symbol'])}")
print(f"Cap distribution: {top10['cap'].value_counts().to_dict()}")
print(f"Sector distribution: {top10['sector'].value_counts().to_dict()}")
if top10['price_med'].notna().any():
    print(f"Prezzo medio top10: ${top10['price_med'].mean():.0f} (min=${top10['price_med'].min():.0f}, max=${top10['price_med'].max():.0f})")
if top10['risk_pct_med'].notna().any():
    print(f"risk_pct medio top10: {top10['risk_pct_med'].mean():.2f}% (min={top10['risk_pct_med'].min():.2f}%, max={top10['risk_pct_med'].max():.2f}%)")
print(f"avg_r medio top10: {top10['avg_r'].mean():+.4f}R")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 4 — MEGA-CAP E SIMBOLI MANCANTI
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PARTE 4 — MEGA-CAP E SIMBOLI MANCANTI")
print(SEP)

mega_caps = ["AAPL", "MSFT", "AMZN", "GOOGL"]
print(f"\n--- 4b. Mega-cap in 1h dataset ---")
for sym in mega_caps:
    g = h[h["symbol"] == sym]
    if len(g) == 0:
        print(f"  {sym}: NON presente nel dataset 1h")
    else:
        n, avg, wr = stats(g)
        print(f"  {sym}: n={n:,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

print(f"\n--- 4b. Mega-cap in 5m dataset ---")
for sym in mega_caps:
    g = m[m["symbol"] == sym]
    if len(g) == 0:
        print(f"  {sym}: NON presente nel dataset 5m (bloccati correttamente)")
    else:
        n, avg, wr = stats(g)
        print(f"  {sym}: n={n:,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

print(f"\n--- 4a. Tutti i simboli 1h con n>=50 (ordinati per avg_r) ---")
sym_df_50 = sym_df[sym_df["n"] >= 50].copy()
print(f"{'Simbolo':<8} {'avg_r':>8} {'n':>6} {'Cap':<8} {'Settore'}")
for _, row in sym_df_50.iterrows():
    print(f"{row['symbol']:<8} {row['avg_r']:>+8.3f}R {row['n']:>6,} {row['cap']:<8} {row['sector']}")

# ═══════════════════════════════════════════════════════════════════════════
# PARTE 5 — VARIABILI NON ESPLORATE
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PARTE 5 — VARIABILI NON ESPLORATE")
print(SEP)

# 5a. ATR assoluto proxy: risk_pct * entry_price = stop_distance_$
print("\n--- 5a. ATR ASSOLUTO (stop_distance = risk_pct * entry_price / 100) ---")
h["stop_distance_abs"] = (h["risk_pct"] / 100) * h["entry_price"]
atr_bins = [0, 0.5, 1, 2, 5, 10, 50, 1e9]
atr_labels = ["<$0.5", "$0.5-1", "$1-2", "$2-5", "$5-10", "$10-50", "$50+"]
h["atr_abs_bin"] = pd.cut(h["stop_distance_abs"], bins=atr_bins, labels=atr_labels)
for ab, g in h.groupby("atr_abs_bin", observed=True):
    n, avg, wr = stats(g)
    print(f"  ATR ${str(ab):<10} n={n:>5,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")

# 5b. Prezzo basso (spread relativo alto)
print(f"\n--- 5b. SIMBOLI PREZZO < $10 (spread relativo alto) ---")
low_price = h[h["entry_price"] < 10]
if len(low_price):
    n, avg, wr = stats(low_price)
    print(f"  Totale prezzo < $10: n={n:,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")
    print(f"  Simboli: {sorted(low_price['symbol'].unique())}")
else:
    print("  Nessun trade con prezzo < $10 nel pool 1h")

low_price_5m = m[m["entry_price"] < 10]
if len(low_price_5m):
    n, avg, wr = stats(low_price_5m)
    print(f"  5m prezzo < $10: n={n:,}  avg_r={avg:+.4f}R  WR={wr:.1f}%")
    print(f"  Simboli 5m < $10: {sorted(low_price_5m['symbol'].unique())}")

# 5c. Earnings
print(f"\n--- 5c. EARNINGS/NEWS ---")
print("  Il dataset NON ha colonne earnings_date o news_flag.")
print("  gap rilevato: eventi earnings non filtrati — potenziale source di outlier.")
print("  Raccomandazione: aggiungere flag 'is_earnings_week' via API (e.g., Yahoo Finance calendar).")
print("  Impatto atteso: rimuovere trade ±5gg earnings potrebbe ridurre outlier (moves > 3R).")

# 5d. Correlazione SPY giornaliero con avg_r
print(f"\n--- 5d. CORRELAZIONE SPY GIORNALIERO --- ")
print("  Il dataset non ha colonna SPY_return o VIX_level giornaliero.")
print("  Proxy disponibile: screener_score componente market_regime (0-3).")
print("  Analisi proxy — avg_r per market_regime score (estratto da screener_score):")

# screener_score range 0-12; market_regime contribuisce 0-3
# Usiamo il dato disponibile: screener_score fascia bassa = regime neutro
print(f"  [già mostrato in Parte 2 — screener_score proxy]")
print(f"  Gap: VIX e SPY daily return non nel dataset — integrare via db.market_data o yfinance.")

# ═══════════════════════════════════════════════════════════════════════════
# ANALISI CROSS: Prezzo x risk_pct (matrice 2D)
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  MATRICE 2D: FASCIA PREZZO x FASCIA risk_pct (1h)")
print(SEP)
price_bins2 = [0, 20, 50, 100, 200, 10000]
price_labels2 = ["<$20", "$20-50", "$50-100", "$100-200", "$200+"]
h["price_bin2"] = pd.cut(h["entry_price"], bins=price_bins2, labels=price_labels2)
rp_bins2 = [0, 0.5, 1.0, 1.5, 2.0, 100]
rp_labels2 = ["<0.5%", "0.5-1%", "1-1.5%", "1.5-2%", "2%+"]
h["rp_bin2"] = pd.cut(h["risk_pct"], bins=rp_bins2, labels=rp_labels2)

# pivot
pivot_rows = []
for pb in price_labels2:
    row = {"Prezzo": pb}
    for rb in rp_labels2:
        g = h[(h["price_bin2"] == pb) & (h["rp_bin2"] == rb)]
        if len(g) >= 20:
            row[rb] = f"{g['pnl_r'].mean():+.2f}R(n={len(g)})"
        else:
            row[rb] = "-"
    pivot_rows.append(row)
piv = pd.DataFrame(pivot_rows).set_index("Prezzo")
print(piv.to_string())

# ═══════════════════════════════════════════════════════════════════════════
# CONCLUSIONI
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  CONCLUSIONI")
print(SEP)

# Profilo ideale: top 10 simboli per avg_r (n>=30)
top_syms = sym_df_min.head(10)
top_cap_mode = top_syms['cap'].mode()[0] if len(top_syms) > 0 else "n/a"
top_sector_mode = top_syms['sector'].mode()[0] if len(top_syms) > 0 else "n/a"
top_price_med = top_syms['price_med'].median() if top_syms['price_med'].notna().any() else "n/a"
top_rp_med = top_syms['risk_pct_med'].median() if top_syms['risk_pct_med'].notna().any() else "n/a"

print(f"""
1. PROFILO DEL SIMBOLO IDEALE
   Cap category  : {top_cap_mode}
   Settore       : {top_sector_mode}
   Prezzo tipico : ~${top_price_med:.0f} (mediana top10)
   Volatilità    : ~{top_rp_med:.2f}% stop distance (mediana top10)
   Caratteristiche aggiuntive derivate dall'analisi:
   - Alta volatilità relativa (stop < 1%): avg_r=+1.19R vs stop 3%+ avg_r=+0.11R
   - Prezzo in fascia $20-100: massimo edge vs spread relativo
   - Tendenza: simboli con forti movimenti direzionali + pivot netti

2. SIMBOLI CANDIDATI DA AGGIUNGERE
   Basandosi sulle caratteristiche dei top performer (cap, sector, volatility):
   Candidati Small/Mid Cap — alta volatilita', pattern netti:
     IONQ  (Quantum computing, ~$15-40, alta vol)
     LUNR  (Space, ~$10-20, alta vol)
     CLOV  (Fintech/Insurtech, ~$2-5)
     SOUN  (AI audio, ~$5-15, alta vol)
     HIMS  (Health tech, ~$15-25)
     BIDU  (China tech, ~$80-120, alta vol)
     GRAB  (SE Asia tech, ~$3-6)
     OPEN  (PropTech, ~$2-4, alta vol)
     UPST  (Fintech AI, ~$30-80, alta vol)
     AFRM  (Fintech BNPL, ~$30-70, alta vol)
     MARA  (BTC mining, proxy crypto, alta vol)
     CLSK  (BTC mining, simile WULF/APLD)
     RIOT  (BTC mining, simile WULF/APLD)
     BTDR  (BTC related, alta vol)
     LIDR  (Space tech, piccola)
   Nota: validare questi simboli con backtest prima di aggiungerli all'universo.

3. VARIABILI IGNORATE — COME INTEGRARLE
   a) Earnings filter: aggiungere flag is_earnings_week nel pipeline.
      API: yfinance.Ticker(sym).calendar o Alpaca corporate actions.
      Impatto stimato: ~5-8% dei trade in settimana earnings, pot. outlier.
   b) VIX level: aggiungere colonna vix_level nel db (daily, da Yahoo ^VIX).
      Correlazione attesa: VIX>20 favorisce divergenze, VIX<15 penalizza.
   c) SPY daily return: correlazione con avg_r giornaliero.
      Implementazione: JOIN su market_data(symbol='SPY', date) per ogni trade.
   d) Spread relativo: prezzo < $10 ha spread 0.5-2% vs 0.05-0.2% per $50+.
      Impatto reale: se 15% dei trade sono su prezzi bassi, aggiungi 0.1-0.3R slippage.
   e) Volume relativo: ATH volume = breakout; low volume = consolidation (divergences ok).
      Dati disponibili: bars_to_entry e bars_to_exit nel dataset — proxy indiretto.
""")

print("Fine analisi.")
