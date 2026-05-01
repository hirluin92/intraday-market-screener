"""
B: Analisi simboli candidati dal database.
Confronta simboli nel DB vs universo validato attuale.
Usa val_1h_full.csv per avg_r backtest.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

VALIDATED_PATTERNS_1H = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bear", "macd_divergence_bull",
    "rsi_divergence_bear", "rsi_divergence_bull",
    "engulfing_bullish",
})

VALIDATED_SYMBOLS_YAHOO = frozenset({
    "GOOGL","TSLA","AMD","META","NVDA","NFLX",
    "COIN","MSTR","HOOD","SOFI","SCHW",
    "RBLX","SHOP","ZS","NET","MDB","CELH","PLTR","HPE","SMCI","DELL",
    "ACHR","ASTS","JOBY","RKLB","NNE","OKLO","WULF","APLD","SMR","RXRX",
    "NVO","LLY","MRNA","NKE","TGT","MP","NEM","WMT",
})

SYMBOLS_BLOCKED = frozenset({"REGN","BMRN","HON","DIA","ICE","VRTX","CVX","SPY",
                              "LLOY","TSCO","VOD","LAND","ULVR"})
MONITORING_NEW = frozenset({"MARA","CLSK","RIOT","UPST","AFRM","HIMS"})

# Simboli UK in raccolta dati (monitor forzato)
UK_DC = frozenset({"AAL","ANTO","AZN","BA.","BARC","BATS","BLND","BP.","BT.A",
                   "CRH","DGE","EXPN","GLEN","GSK","HSBA","NWG","NXT","PRU",
                   "REL","RIO","RKT","RR.","SBRY","SHEL","STAN"})

# Tutti i simboli nel DB con dati 1h (dalla query precedente)
DB_SYMBOLS_1H = {
    # Core originali (dal 2023)
    "GOOGL","AAPL","MSFT","META","AMD","TSLA","NVDA","NFLX","AMZN","GS","JPM",
    "QQQ","IWM","SPY",
    # Batch oct 2024
    "DIA","WMT","TGT","V","SCHW","NKE","MA","ICE","COST","CVX","HON","NEM",
    "GD","SPGI","BAC","XOM","NVO","CME","LLY","TXN","BLK","DE","GILD","HPE",
    "VRTX","GE","BMRN","PFE","LMT","DELL","ZS","RTX","NOC","C","ARKK","MMM",
    "RBLX","SHOP","ABBV","BA","QCOM","CAT","OXY","FCX","WFC","MDB","PLTR","MS",
    "NET","KLAC","ARKG","CELH","CRWD","BIIB","MP","AMAT","UBER","SLB","ON",
    "LRCX","DDOG","PANW","REGN","AVGO","SOFI","RKLB","SMCI","MSTR","COIN",
    "MRNA","MU","TQQQ","SNOW","JOBY","BNTX","ACHR","ASTS","APLD","NNE","WULF",
    "SQQQ","RXRX","OKLO","SNAP","SMR","RIVN","VKTX","IONQ","LUNR",
    # UK
    "TSCO","ULVR","HSBA","RKT","NXT","REL","EXPN","SBRY","LAND","LLOY","SHEL",
    "BLND","AZN","GSK","STAN","VOD","BATS","RIO","BP.","DGE","PRU","BT.A",
    "NWG","BARC","BA.","GLEN","AAL","CRH","RR.","ANTO",
    # Crypto (recenti, pochi mesi)
    "ETH/USDT","DOGE/USDT","SOL/USDT","ADA/USDT","WLD/USDT",
}

SEP = "=" * 74

# ── Load dataset ─────────────────────────────────────────────────────────────
h = pd.read_csv("data/val_1h_full.csv", parse_dates=["pattern_timestamp"])
h = h[h["entry_filled"] == True].copy()
h_val = h[h["pattern_name"].isin(VALIDATED_PATTERNS_1H)].copy()
h_val["year"] = h_val["pattern_timestamp"].dt.year

# ════════════════════════════════════════════════════════════════════════════
print(SEP)
print("  B1 — SIMBOLI MONITORING: dati nel DB?")
print(SEP)
for sym in sorted(MONITORING_NEW):
    in_db = sym in DB_SYMBOLS_1H
    in_dataset = sym in h_val["symbol"].values
    n_db = len(h_val[h_val["symbol"] == sym])
    print(f"  {sym:<6}: DB={'SI' if in_db else 'NO'}  dataset={'SI' if in_dataset else 'NO'}  n_backtest={n_db}")
print("""
  Conclusione B1: nessun simbolo monitoring ha ancora dati nel DB.
  Erano stati aggiunti allo scheduler oggi — il primo ciclo di ingestione
  avverra' al prossimo run dello scheduler. Stimato: prossime ore/giornata.
""")

# ════════════════════════════════════════════════════════════════════════════
print(SEP)
print("  B3 — SIMBOLI NEL DB MA NON IN VALIDATED_SYMBOLS_YAHOO")
print("       (con dati backtest sufficenti)")
print(SEP)

# Tutti i simboli US nel dataset (non UK, non crypto, non bloccati)
# che non sono in VALIDATED_SYMBOLS_YAHOO e non sono in monitoring
all_syms = h_val["symbol"].unique()
candidates = []
for sym in all_syms:
    if sym in VALIDATED_SYMBOLS_YAHOO: continue
    if sym in SYMBOLS_BLOCKED: continue
    if sym in UK_DC: continue
    if sym in MONITORING_NEW: continue
    if "/" in sym: continue   # crypto
    g = h_val[h_val["symbol"] == sym]
    n = len(g)
    if n < 30: continue
    avg = g["pnl_r"].mean()
    wr = (g["pnl_r"] > 0).mean() * 100
    price_med = g["entry_price"].median()
    rp_med = g["risk_pct"].median()
    in_db = sym in DB_SYMBOLS_1H
    # Per anno
    yr_avgs = {}
    for yr, gy in g.groupby("year"):
        if len(gy) >= 8:
            yr_avgs[yr] = gy["pnl_r"].mean()
    # Top pattern
    top_pat = g.groupby("pattern_name")["pnl_r"].mean().sort_values(ascending=False).head(1)
    top_pat_name = top_pat.index[0] if len(top_pat) else "n/a"
    top_pat_avg = top_pat.values[0] if len(top_pat) else 0
    candidates.append(dict(
        sym=sym, n=n, avg=avg, wr=wr, price=price_med, rp=rp_med,
        in_db=in_db, yr_avgs=yr_avgs,
        top_pat=top_pat_name, top_pat_avg=top_pat_avg,
    ))

candidates.sort(key=lambda x: x["avg"], reverse=True)

print(f"\n{'Simbolo':<7} {'n':>5} {'avg_r':>8} {'WR':>6} {'Prezzo':>7} {'risk%':>6} "
      f"{'2023':>8} {'2024':>8} {'2025':>8} {'DB':>4} {'Stab'}")
print("-" * 95)
for c in candidates:
    y23 = f"{c['yr_avgs'][2023]:>+.2f}" if 2023 in c["yr_avgs"] else "  n/a"
    y24 = f"{c['yr_avgs'][2024]:>+.2f}" if 2024 in c["yr_avgs"] else "  n/a"
    y25 = f"{c['yr_avgs'][2025]:>+.2f}" if 2025 in c["yr_avgs"] else "  n/a"
    # stabilità: tutti gli anni con dati sono positivi?
    valid = list(c["yr_avgs"].values())
    stab = "ROB" if len(valid) >= 2 and all(v > 0 for v in valid) else \
           "MIX" if len(valid) >= 2 else "1YR"
    c["stab"] = stab
    db_flag = "SI" if c["in_db"] else "NO"
    print(f"{c['sym']:<7} {c['n']:>5,} {c['avg']:>+8.3f}R {c['wr']:>5.1f}% "
          f"${c['price']:>5.0f} {c['rp']:>5.2f}% "
          f"{y23:>8} {y24:>8} {y25:>8} {db_flag:>4} {stab}")

# ════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  B4 — CANDIDATI PRONTI: n>=30, avg_r>+0.20R, ROB o 1YR positivo")
print(SEP)

ready = [c for c in candidates if c["avg"] > 0.20 and c["in_db"]]
ready_rob = [c for c in ready if c["stab"] in ("ROB", "1YR")]

print(f"\n{'Simbolo':<7} {'n':>5} {'avg_r':>8} {'WR':>6} {'Prezzo':>7} "
      f"{'risk%':>6} {'Stabilita':>10} {'Top pattern'}")
print("-" * 80)
for c in ready_rob:
    valid = list(c["yr_avgs"].values())
    stab = "ROBUSTO" if c["stab"] == "ROB" else "1 anno"
    print(f"{c['sym']:<7} {c['n']:>5,} {c['avg']:>+8.3f}R {c['wr']:>5.1f}% "
          f"${c['price']:>5.0f} {c['rp']:>5.2f}% {stab:>10}  {c['top_pat']} ({c['top_pat_avg']:>+.2f}R)")

# ════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  B4b — ANALISI PER ANNO dei candidati robusti (n>=30, avg>+0.20R)")
print(SEP)
for c in ready:
    print(f"\n  {c['sym']} (n={c['n']}, avg={c['avg']:+.3f}R):")
    for yr in [2023, 2024, 2025]:
        if yr in c["yr_avgs"]:
            gy = h_val[(h_val["symbol"] == c["sym"]) & (h_val["year"] == yr)]
            print(f"    {yr}: avg_r={c['yr_avgs'][yr]:+.3f}R  n={len(gy)}  WR={(gy['pnl_r']>0).mean()*100:.1f}%")
    # Top 3 pattern per questo simbolo
    g_sym = h_val[h_val["symbol"] == c["sym"]]
    pat_agg = g_sym.groupby("pattern_name")["pnl_r"].agg(["mean","count"]).rename(
        columns={"mean":"avg","count":"n"}).sort_values("avg", ascending=False)
    for pn, row in pat_agg.head(3).iterrows():
        if row["n"] >= 5:
            print(f"    Pattern: {pn:<36} n={int(row['n']):>4}  avg={row['avg']:>+.3f}R")

# ════════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  CONFRONTO: nuovi candidati vs universo attuale")
print(SEP)
current_avg = h_val[h_val["symbol"].isin(VALIDATED_SYMBOLS_YAHOO)]["pnl_r"].mean()
current_n = len(h_val[h_val["symbol"].isin(VALIDATED_SYMBOLS_YAHOO)])
if ready_rob:
    cand_avgs = [c["avg"] for c in ready_rob]
    print(f"\n  Universo attuale (39 simboli): avg_r={current_avg:+.4f}R  n={current_n:,}")
    print(f"  Candidati robusti (>+0.20R):   avg_r={sum(cand_avgs)/len(cand_avgs):+.4f}R  n_simboli={len(ready_rob)}")
    print(f"\n  Impatto aggiunta top 5 candidati:")
    top5_syms = [c["sym"] for c in ready_rob[:5]]
    combined = h_val[h_val["symbol"].isin(VALIDATED_SYMBOLS_YAHOO | set(top5_syms))]
    print(f"    Pool combinato: avg_r={combined['pnl_r'].mean():+.4f}R  n={len(combined):,}  "+
          f"simboli={len(top5_syms)+39}")

print(f"\n{SEP}")
print("  CONCLUSIONE B")
print(SEP)
print(f"""
B1: Simboli monitoring (MARA, CLSK, RIOT, UPST, AFRM, HIMS) non ancora nel DB.
    Saranno ingeriti al primo ciclo scheduler (prossime ore/giorno).
    Rivalutare dopo 6 mesi di dati accumulati.

B3/B4: Simboli nel DB con edge confermato e PRONTI per validazione:
    Vedi tabella sopra. I "ROBUSTO" hanno avg_r positivo in tutti gli anni disponibili.

RACCOMANDAZIONE:
    - Simboli con 2+ anni ROB e avg_r > +0.25R: candidati forti per VALIDATED
    - Simboli con 1 anno solo (1YR): aspettare un altro ciclo di dati
    - ETF leveraged (SQQQ, TQQQ): edge reale ma liquidare difficile per stop
    - Non aggiungere piu' di 5-10 simboli per volta: diluisce il DB e l'analisi
""")
