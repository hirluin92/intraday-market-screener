# Contesto operativo — intraday-market-screener (incolla in nuove chat)

**Ultimo aggiornamento:** 2026-04-15  
**Fonte dettagliata metriche:** `backend/data/SCORING_BASELINE_2026-04-10.md`  
**Decisioni architetturali complete:** `docs/baseline.md`

---

## Dataset di riferimento

| File | n (filled) | Uso |
|------|------------|-----|
| `backend/data/val_1h_large.csv` | 2095 (n_pq=1304) | Metriche principali 1h |
| `backend/data/val_1d_large.csv` | 881 (n_pq=871) | 1d |
| `backend/data/validation_baseline_2026-04-10.csv` | 834 | Cross-TF |

---

## Baseline "random" (1h, n=2095)

- **avg_r:** +0.655R  
- **WR:** 56.9%  
- Confronto: **top 20% by final_score** = +0.618R (peggio del random); **bot 20%** = +1.010R (il sistema ranka al contrario rispetto all'EV).

---

## Strada A (validata — sez. 10 `analyze_validation_dataset.py`)

**Idea:** gate **binario** per pattern **contro-trend** (nessuna soglia di score) + **solo top K%** per pattern **ranking-dependent** (engulfing_bullish).

**Set contro-trend (execute senza filtro score):**  
`rsi_divergence_bull/bear`, `macd_divergence_bull/bear`, `double_top`, `double_bottom`

**Set ranking:** `engulfing_bullish` — eseguire solo se `final_score` nel top K% (raccomandazione **K=20%**).

### Numeri (train, n=2095)

| K% engulfing | n Strada A | avg_r | WR% | vs random |
|--------------|------------|-------|-----|-----------|
| 10% | 1235 | +0.903R | 64.2% | +0.249R |
| **20%** | **1264** | **+0.905R** | **64.2%** | **+0.250R** |
| 30% | 1293 | +0.894R | 63.9% | +0.239R |

Baseline sistema "tutto incluso": avg_r **+0.655R**, WR **56.9%**.

### Test set (ultimi 30%, n=628)

| K% | n Strada A | avg_r test | vs random test (+0.639R) |
|----|------------|------------|--------------------------|
| 10% | 369 | +0.930R | +0.291R |
| **20%** | **376** | **+0.922R** | **+0.284R** |
| 30% | 383 | +0.900R | +0.261R |

**Conclusione:** upgrade stabile su unseen; nessun segnale di overfitting marcato. **K raccomandato: 20%.**

---

## Scoring attuale (v1) — sintesi diagnostica 1h

- **final_score AUC ≈ 0.451** (invertito vs win): numero da battere con formule alternative su `val_1h_large.csv` è **> 0.50** se si usa ancora AUC.  
- **Metrica preferita per sostituti:** **avg_r@top20%** deve battere **+0.655R** out-of-time (non solo battere il ranker attuale). Target teorico alto: avvicinarsi al **bot20% attuale (~+1.01R)**.  
- **Spearman(score, pnl_r):** oggi negativo; obiettivo **> 0** sul test.

**Strada 1 (pesi lineari / per-pattern):** scartata — esperimento `scoring_v2.py` mostra paradosso di Simpson: migliora dentro-pattern ma peggiora il ranking aggregato. **Non riprovare** varianti lineari simili.

**LightGBM / tree:** candidato per **dopo** Strada A (secondo livello), non sostituto 1:1 di Strada A; sui contro-trend l'AUC interna è spesso ~rumore — Strada A copre quella lacuna con logica esplicita.

---

## Decisioni prese (riepilogo)

1. **Strada A** è la strategia di filtro **validata** numericamente; implementazione target: `opportunity_validator.py`: contro-trend → execute; engulfing → solo sopra soglia **p80** (`final_score ≥ 84.0`).  
2. **Non** affidarsi al `final_score` globale come ranker unico senza questa stratificazione.  
3. Qualsiasi nuovo scoring si misura con **avg_r@K** e Spearman, non solo AUC globale.  
4. **Strada 1** lineare abbandonata; **LightGBM** eventualmente come layer successivo a Strada A.
5. **5m non auto-eseguito** finché non esiste un validation set OOS 5m con WR e avg_R misurati (analogo al dataset 1h esistente).

---

## Stato implementazione (aggiornato 2026-04-15)

### Strada A — IN PRODUZIONE ✓

| File | Modifica |
|------|----------|
| `backend/app/core/trade_plan_variant_constants.py` | `STRADA_A_ENGULFING_MIN_FINAL_SCORE = 84.0` (p80) |
| `backend/app/services/opportunity_validator.py` | Gate engulfing_bullish: `final_score < 84.0` → monitor |
| `backend/app/services/opportunities.py` | Passa `final_score` al validator |

**Impatto:** solo `engulfing_bullish` in regime bear con `final_score < 84.0` passa da execute → monitor (~80% casi). Tutti gli altri pattern invariati.

---

### Validator — filtri operativi completi (aprile 2026)

`opportunity_validator.py` è il **sistema decisionale unico** per `operational_decision` (execute / monitor / discard). Filtri applicati in ordine:

1. **Ora UTC non operativa** (solo Yahoo): after-hours e bassa liquidità → discard  
2. **Timeframe** non in `{1h, 5m}` → discard  
3. **Simbolo** non nell'universo validato (40 Yahoo, 6 Binance) → discard  
4. **`PATTERNS_BLOCKED`** (14 pattern, WR < 40% su 26k+ segnali — es. `impulsive_bearish_candle` WR 32%, `volatility_squeeze_breakout` EV +0.04R) → discard  
5. **Pattern non nella lista operativa** per TF (`VALIDATED_PATTERNS_1H` / `VALIDATED_PATTERNS_5M`) → discard  
6. **Regime errato per `PATTERNS_BEAR_REGIME_ONLY`** (`engulfing_bullish`, `macd_divergence_bull`, `rsi_divergence_bull`): attivi **solo** in regime SPY bear; se regime ≠ bear → monitor  
7. **`SIGNAL_MIN_CONFLUENCE = 2`**: almeno 2 pattern validati distinti attivi nella stessa barra → se < 2 → monitor *(OOS: EV +0.478R +95.3% vs no-filter, WR 58.4%, PF 2.82)*  
8. **`SIGNAL_MIN_STRENGTH = 0.70`**: strength pattern < 0.70 → monitor  
9. **Strada A engulfing**: `final_score < 84.0` → monitor  

Tutto il resto → **execute**.

### Pattern operativi 1h — riferimento rapido

| Pattern | Tipo | Regime richiesto | WR | EV |
|---------|------|-----------------|----|----|
| `compression_to_expansion_transition` | universale | qualsiasi | 67% | +0.45R |
| `rsi_momentum_continuation` | universale | qualsiasi | 56% | +0.30R |
| `double_bottom` | universale | qualsiasi | 65% | +0.55R |
| `double_top` | universale | qualsiasi | 61% | +0.41R |
| `engulfing_bullish` | bear-only | bear (+ score ≥ 84) | 67% | +0.16R |
| `macd_divergence_bull` | bear-only | bear | 71% | +0.86R |
| `rsi_divergence_bull` | bear-only | bear | 64% | +0.68R |
| `rsi_divergence_bear` | short universale | qualsiasi | 58% | +0.40R bull / +0.22R bear |
| `macd_divergence_bear` | short universale | qualsiasi | 59% | +0.37R bull / +0.25R bear |
| `fibonacci_bounce` | SOSPESO | — | — | EV portfolio −0.580R in test |

5m operativo (Yahoo/Alpaca): solo `rsi_momentum_continuation`. Alpaca 5m OOS: `double_top` (WR 69.5%), `macd_divergence_bear` (WR 64.4%), `double_bottom` (WR 57%) — auto-execute 5m comunque disabilitato di default.

### Trade plan variant in live

`trade_plan_live_variant.py` sceglie se applicare la **best variant backtest** o il **motore standard**:

| Status variante | Condizione | Applicata in live? |
|----------------|-----------|---------------------|
| `promoted` | campione ≥ 50 | ✓ sempre |
| `watchlist` | campione 20–49, expectancy > 0 | ✓ se campione ≥ 30 |
| `rejected` | expectancy ≤ 0 | ✗ → fallback standard |
| `no_variant_bucket` | nessuna variante backtest | ✗ → fallback standard |

Campo `trade_plan_fallback_reason` nell'API response: `no_pattern` / `no_variant_bucket` / `variant_rejected` / `watchlist_insufficient_sample`.

Profili TP testati: `tp_1.0_2.0`, `tp_1.5_2.0`, `tp_1.5_2.5`, `tp_2.0_3.0`, `tp_2.5_4.0` (ultimi due aggiunti per crypto 5m ad alta volatilità).

---

### Bug critici chiusi (2026-04-14/15) — SISTEMA PRONTO PER PAPER TRADING

**Bug #1 — Trade fantasma (execute_signal):** `execute_signal()` registrava `status="executed"` anche quando TWS rifiutava l'ordine.  
→ **Fix:** `ibkr_error_codes.py` classifica errori critici vs informativi (codici 201/203/354 vs 2104/2106). `execute_signal()` ora distingue 5 esiti con `tws_status` esplicito (`submitted`, `rejected`, `tws_unavailable`, `exception`, `no_order_id`). I fallimenti vengono salvati nel DB con `executed_ok=False`.  
→ **Monitoring:** `GET /api/v1/monitoring/execution-stats` — target `success_rate_pct ≥ 95%`.

**Bug #2 — Prezzo stale per staleness check:** `current_price` era sempre il close dell'ultima candela completata (fino a 60min di latenza su 1h).  
→ **Fix:** `TWSService.get_last_price()` ritorna il last price live per simboli US (cache TTL 30s, timeout 2s, fallback silenzioso a candle close). `OpportunityRow` espone `price_source: "live_tws" | "candle_close" | "unavailable"`.  
→ Per Binance crypto: invariato (candle close, nessun equivalente TWS).

**Bug #3 — Hardcode `1h + yahoo_finance` in auto_execute scan:** lo scan globale post-ciclo ignorava Binance e timeframe diversi da 1h.  
→ **Fix:** due nuove env var: `AUTO_EXECUTE_TIMEFRAMES_ENABLED=1h` (default, 5m escluso) e `AUTO_EXECUTE_PROVIDERS_ENABLED=yahoo_finance,binance`. Scan itera su tutte le combo abilitate.  
→ **Fix collegato:** rimosso `break` prematuro nell'hook per-simbolo. Cap di sicurezza: `MAX_ORDERS_PER_HOOK_INVOCATION=5`, `MAX_ORDERS_PER_SCAN=10`.  
→ **Monitoring:** `GET /api/v1/monitoring/auto-execute-config`.

**Bug #4 — Latenza prewarm → auto_execute:** `_prewarm_opportunities_cache` e `run_auto_execute_scan` giravano sequenzialmente (+5–15s di latenza critica su mercati veloci).  
→ **Fix:** `asyncio.gather` li esegue in parallelo (verificata indipendenza: prewarm scrive solo in-memory cache, auto_execute legge dal DB). `poll_and_record_stop_fills` rimane sequenziale dopo.  
→ Log metrica: `prewarm+auto_execute completati in Xms (parallelo)`.

---

### Infrastruttura live — stato componenti

| Componente | Stato | Note |
|------------|-------|------|
| Bracket order (entry LMT + TP + SL GTC) | ✓ operativo | `tws_service.py` |
| Fill parziali | ✓ gestito | Polling 60s, resize o close se ratio < 30% |
| Slippage gap overnight | ✓ tracciato | `GET /monitoring/slippage-stats` |
| Tick size rounding | ✓ implementato | US stock $0.01, crypto per-simbolo |
| Banner UX stato IBKR | ✓ operativo | Frontend, polling 30s |
| Errori TWS classificati | ✓ implementato | `ibkr_error_codes.py` |
| Prezzo live per staleness | ✓ implementato | TWS last price, cache TTL 30s |
| Trade plan variant in live | ✓ implementato | `trade_plan_live_variant.py`, promoted/watchlist |
| Alert Discord/Telegram | ✓ operativo | Flusso globale + mirato; dedupe atomico DB; `send_system_alert` |
| Invalidazione cache manuale | ✓ disponibile | `POST /api/v1/health/cache/invalidate` |

### Endpoint monitoring disponibili

| Endpoint | Cosa mostra |
|----------|-------------|
| `GET /api/v1/monitoring/execution-stats?days=30` | Tasso successo invio ordini (target ≥ 95%) |
| `GET /api/v1/monitoring/fill-stats?days=30` | Fill completi vs parziali vs rejected |
| `GET /api/v1/monitoring/slippage-stats?days=30` | realized_R vs nominal_R su chiusure da stop |
| `GET /api/v1/monitoring/auto-execute-config` | Config corrente auto-execute (read-only) |
| `GET /api/v1/health/ibkr` | Stato connessione TWS |
| `GET /api/v1/health/settings` | Universo scheduler, soglie operative, cache stats |
| `POST /api/v1/health/cache/invalidate` | Forza ricalcolo cache qualità pattern / varianti |

### Frontend — funzionalità chiave

| Pagina | Feature |
|--------|---------|
| **`/opportunities`** | Badge IBKR (connected / paper / auto-exec); tabella segnali eseguiti (submitted/filled/rejected/cancelled); deep-link `?expand=symbol:tf:provider` |
| **`/opportunities/[symbol]/[timeframe]`** | Badge **Variant backtest** vs **Fallback standard** con motivo; `Promise.allSettled` (sezioni parziali se market-data fallisce) |
| **`/diagnostica`** | KPI screener e best/worst pattern per TF da backtest aggregato; banner dati parziali se fetch fallisce |
| **Layout globale** | `IBKRStatusBanner` su tutte le pagine, polling 30s |
| **`SignalCard`** | `price_distance_pct`, badge `price_stale`, regime SPY, variant status nel sizing |

---

## Limitazioni note per il paper trading

1. **TWS usa `reqMarketDataType(3)` (delayed/frozen):** senza abbonamento real-time i prezzi hanno 15–20 min di ritardo. Per 1h il Bug #2 fix è comunque utile (15 min vs 60 min di latenza del close candela). Per 5m il prezzo "live" delayed sarebbe quasi inutile per lo staleness check — ulteriore motivo per mantenere 5m disabilitato finché non si ha real-time. In live con capitale reale, valutare abbonamento dati US equities (~$10–15/mese IBKR) per azzerare questo ritardo.
2. **Backtester assume −1R fisso su stop:** gap overnight avversi producono fill peggiori del nominale. Tracciare con `slippage-stats` per tarare aspettative.
3. **5m non validato (Yahoo/Alpaca):** Strada A è costruita su dataset 1h. Auto-execute su 5m disabilitato di default (`AUTO_EXECUTE_TIMEFRAMES_ENABLED=1h`). Alpaca 5m OOS mostra pattern promettenti ma mancano ≥20 esecuzioni live per conferma.
4. **Codici errore IBKR non esaustivi:** `IBKR_CRITICAL_CODES` / `IBKR_INFO_CODES` coprono i casi frequenti. Se compaiono nuovi codici mal-classificati nei log, aggiornare `ibkr_error_codes.py`.
5. **`SIGNAL_MIN_CONFLUENCE = 2` riduce volume segnali:** in mercati laterali con pochi pattern attivi contemporaneamente, molti segnali rimangono "monitor". È un costo accettato per la qualità (EV +95.3% OOS).
6. **Trade plan variant in watchlist:** varianti con campione 30–49 vengono applicate in live ma con stima statistica ancora incerta (CI Wilson ≈ ±18%). Non esiste ancora un meccanismo automatico per degradare una watchlist a "rejected" se inizia a fare male in live. Da monitorare manualmente: se una bucket watchlist accumula ≥ 10 trade live con expectancy < 0, rivalutare la sua applicazione.
7. **Strada A validata su universo specifico:** le metriche (WR, EV, PF) sono misurate sull'universo attuale — 39 simboli Yahoo + 6 crypto Binance. Aggiungere un nuovo simbolo all'universo non estende automaticamente la validazione. Ogni nuovo simbolo va trattato come non validato finché non accumula almeno 30 segnali eseguiti sul dataset storico disponibile.

---

## Prossimi step (post paper trading)

- Accumulare ≥ 20 osservazioni gap overnight per tarare `_SLIPPAGE_R_THRESHOLD` e valutare correzione backtester
- Costruire dataset OOS 5m Yahoo (WR + avg_R misurati) prima di abilitare `AUTO_EXECUTE_TIMEFRAMES_ENABLED=1h,5m`; Alpaca 5m OOS già promettente (double_top WR 69.5%) ma serve validazione esecuzione live
- Portare varianti watchlist a "promoted" accumulando ≥ 50 trade per bucket
- Valutare LightGBM come secondo livello sopra Strada A dopo 2–3 mesi di dati live
- Rivalutare `fibonacci_bounce` con SL/TP ottimizzati e allocazione isolata (EV isolato OOS +0.218R ma EV portfolio −0.580R nel test)

---

*Documento sintetico per onboarding rapido in chat; per tabelle complete usare `backend/data/SCORING_BASELINE_2026-04-10.md` e `docs/baseline.md`.*
