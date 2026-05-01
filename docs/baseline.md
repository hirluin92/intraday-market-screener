# Baseline Decisioni Architetturali

Documento di riferimento immutabile. Ogni voce registra una decisione
architetturale, una limitazione nota o un trade-off accettato consapevolmente,
con data e impatto sulle metriche di sistema.

Aggiungere voci; non rimuovere o modificare voci esistenti.

---

## Limitazione nota del backtester: gap overnight

**Data**: 2026-04-14
**File rilevante**: `backend/app/services/trade_plan_backtest.py`
**Metriche impattate**: WR=59%, avg_r=+0.92R (Strada A, 1h, Yahoo Finance)

### Comportamento del backtester

Quando il `low` di una candela tocca o supera il livello dello stop loss,
`trade_plan_backtest.py` registra sempre un'uscita a esattamente **−1R fisso**:

```python
# trade_plan_backtest.py ~riga 163
if lo <= stop:
    return "stop", -(1.0 + cr), k
```

Il modello non distingue tra:
- stop eseguito esattamente al livello nominale (mercato aperto, range normale)
- stop eseguito con slippage su gap overnight (prezzo di apertura molto sotto il livello)

### Comportamento nel live

Un gap ribassista overnight (o intraday su notizie improvvise) può far aprire
il prezzo molto al di sotto del livello nominale dello stop.
IBKR esegue l'ordine STP **al primo prezzo disponibile dopo il gap**,
producendo fill a −1.3R, −1.5R, −2R o peggio rispetto al risk nominale.

### Impatto sulle metriche

| Metrica | Backtest | Live (atteso) |
|---|---|---|
| Win rate | 59% | invariato (è ancora una perdita) |
| avg_r sulle perdite | −1.0R fisso | peggiore in proporzione ai gap overnight |
| avg_r complessivo | +0.92R | marginalmente peggiore |

La degradazione dipende da:
1. Frequenza dei trade aperti in sessioni con gap overnight (pattern 1h → esposizione reale)
2. Severità media dei gap (funzione della volatilità del titolo e degli eventi macro)

Per la Strada A su 1h (pattern prevalentemente su titoli US, sessione ~15:30-22:00 Europa),
i trade aperti vicino alle 22:00 Europa sono esposti al gap dell'apertura successiva.

### Azione intrapresa (2026-04-14)

1. **Logger** `log_stop_close()` aggiunto in `auto_execute_service.py`:
   confronta `realized_R` (fill IBKR reale) con `nominal_R=−1.0` ad ogni chiusura
   da stop loss. Formato log:
   ```
   INFO [auto_execute] Trade closed: symbol=XXX, outcome=stop,
        nominal_R=-1.00, realized_R=-1.35, slippage_R=-0.35, cause=overnight_gap
   ```

2. **5 colonne** aggiunte a `executed_signals` nel DB per tracciare la chiusura:
   `closed_at`, `close_fill_price`, `realized_r`, `close_outcome`, `close_cause`.

3. **Endpoint** `GET /api/v1/monitoring/slippage-stats?days=N` per aggregare
   il disallineamento dai dati live reali.

4. **Non modificato il backtester**: la simulazione realistica del gap
   (fill al prezzo di apertura della barra successiva invece di −1R fisso)
   è un miglioramento futuro che richiede re-validazione dell'intero dataset.
   Verrà valutato dopo aver accumulato almeno 20 osservazioni di gap overnight
   reali tramite il logger.

### Costanti di riferimento

```python
# auto_execute_service.py
_SLIPPAGE_R_THRESHOLD = -1.10   # sotto questa soglia = slippage "significativo"
# Tarare dopo 2-3 mesi di dati live reali
```

---

## Tick size rounding per asset class

**Data**: 2026-04-14
**File**: `backend/app/services/tick_size.py`

### Comportamento

I livelli di entry/stop/TP calcolati dal `trade_plan_engine` (prezzi con precisione
decimale arbitraria, es. 182.347) vengono arrotondati al tick size valido del simbolo
**prima** di essere restituiti al chiamante live.

Il rounding avviene solo sul path live: il parametro `symbol` è opzionale nelle funzioni
`build_trade_plan_v1()` e `build_trade_plan_v1_with_execution_variant()`.
Il backtester chiama senza `symbol` → zero rounding, dati invariati.

### Asimmetria applicata

| Livello | Long | Short | Ragione |
|---|---|---|---|
| Entry | nearest | nearest | Eseguito al prezzo più fedele al calcolo |
| Stop loss | per difetto (ROUND_DOWN) | per eccesso (ROUND_UP) | Stop leggermente più largo → meno stop-out da rumore sul tick |
| TP1/TP2 | per eccesso (ROUND_UP) | per difetto (ROUND_DOWN) | TP leggermente più difficile → metriche live non ottimistiche |

### Mappa tick size

| Asset class | Tick size |
|---|---|
| US stock / ETF prezzo ≥ $1 | $0.01 |
| US stock / ETF prezzo < $1 (penny stock) | $0.0001 |
| BTC/USDT, ETH/USDT, SOL/USDT, … | $0.01 |
| DOGE/USDT | $0.00001 |
| Crypto non in mappa | $0.0001 (fallback + warning in log) |

### Limitazione nota

La mappa `CRYPTO_TICK_SIZES` contiene solo i simboli attualmente nell'universo
validato. Per nuovi simboli crypto, aggiungere esplicitamente in `tick_size.py`.
Aggiornare se Binance cambia i tick size di un simbolo esistente.

---

## Gestione fill parziali

**Data**: 2026-04-14
**File**: `backend/app/services/auto_execute_service.py`

### Contesto

IBKR può fillare parzialmente un ordine LMT di entry (es. 3/10 azioni).
Prima di questo fix il sistema non rilevava il fill parziale: SL e TP
rimanevano dimensionati su 10 azioni mentre la posizione reale era 3.

### Comportamento attuale

Dopo ogni `place_bracket_order()` con esito `executed`, viene avviato un
background task (`_handle_partial_fill_after_bracket`) che:

1. **Polling** stato fill entry order per max **60 secondi** (intervallo 1.5s)
2. **Fill completo** (filled ≈ ordered): aggiorna DB `filled_qty`, nessun resize
3. **Fill parziale** (0 < filled < ordered):
   - Se `fill_ratio ≥ MIN_FILL_RATIO (0.30)`: cancella SL/TP originali, reinvia
     `place_tp_sl_standalone()` dimensionati sul `filled` effettivo (OCA group)
   - Se `fill_ratio < MIN_FILL_RATIO`: chiude immediatamente la posizione con
     market order (`place_market_close_order()`), cancella SL/TP
4. **Rejected/Cancelled**: cancella SL/TP pendenti, aggiorna `tws_status`

### Costanti

```python
# auto_execute_service.py
MIN_FILL_RATIO = 0.30       # sotto questa soglia → chiusura immediata
_FILL_POLL_TIMEOUT_S = 60.0
_FILL_POLL_INTERVAL_S = 1.5
```

### Tracking DB (`executed_signals`)

| Colonna | Tipo | Significato |
|---|---|---|
| `partial_fill` | Boolean | True se fill < ordered |
| `filled_qty` | Numeric(24,8) | Azioni effettivamente fillate |
| `ordered_qty` | Numeric(24,8) | Azioni nell'ordine originale |

### Limitazione nota

Il backtester assume fill completi e istantanei al livello di entry teorico.
La frequenza reale di fill parziali si misurerà dai dati live tramite
`GET /api/v1/monitoring/fill-stats`.

---

## Banner UX stato IBKR

**Data**: 2026-04-14
**File**: `frontend/components/IBKRStatusBanner.tsx`, `frontend/hooks/useIBKRHealth.ts`,
`backend/app/api/v1/routes/health.py`

Il frontend mostra un banner sticky in alto quando la connessione IBKR/TWS è:
- **Disconnessa** (banner ambra) — TWS non risponde o non si è mai connesso
- **In errore** (banner rosso) — connessione fallita durante l'avvio o errore API

Il banner è invisibile quando lo stato è `connected`, `disabled` (TWS non abilitato in config)
o `unknown` (prima del primo polling).

Polling ogni 30 secondi su `GET /api/v1/health/ibkr`. Banner auto-nascosto non appena
la connessione torna operativa. L'endpoint espone: `status`, `last_heartbeat`,
`account_id`, `error_message`.

**Motivazione**: prima di questo fix, IBKR disconnesso produceva pagine vuote o dati
stantii senza alcuna indicazione visiva, portando l'operatore a credere erroneamente
che "non ci sono segnali oggi" invece di "il broker non risponde".

**Implementazione**:
- `TWSService.connection_status()` incapsula lo stato di `_connected` / `_connect_failed`
  e recupera il primo `managedAccount` da ib_insync.
- Il hook React `useIBKRHealth` fa polling su `/api/v1/health/ibkr` con `cache: 'no-store'`
  per evitare risposte stantii del browser.
- Il componente è un Client Component (`'use client'`) inserito nel root layout prima
  di `<AppNav />`, quindi visibile in ogni pagina.

---

## Gestione corretta errori di place_bracket_order in execute_signal()

**Data**: 2026-04-15
**File**: `backend/app/services/auto_execute_service.py`, `backend/app/services/ibkr_error_codes.py`,
`backend/app/api/v1/routes/monitoring.py`,
`backend/tests/services/test_auto_execute_error_handling.py`

### Problema risolto

Prima di questo fix, `execute_signal()` registrava `status="executed"` nel DB anche
quando TWS rifiutava l'ordine o non era connesso, producendo **trade fantasma** che:
- Contaminano le metriche di paper trading (fill rate, realized_R)
- Rendono impossibile distinguere "ordine inviato" da "ordine tentato e fallito"
- Mascherano problemi sistemici di connessione TWS

Due percorsi di fallimento silenziosi erano presenti:

1. `place_bracket_order` può ritornare `{"error": "TWS non connesso"}` come dict normale
   (non eccezione) quando `_ensure_started()` fallisce o il timeout del sync wrapper scatta.
   Questo dict non veniva rilevato dal `try/except` e il flusso proseguiva come se ok.

2. Quando `place_bracket_order` ritorna con `errors` non vuoto (es. "Order rejected"),
   il codice faceva solo `logger.warning` e poi ritornava `status="executed"` comunque.

### Soluzione implementata

**`ibkr_error_codes.py`** — nuovo modulo con classificazione codici errore IBKR:
- `IBKR_INFO_CODES`: codici informativi (2104, 2106, 2158, ecc.) che non bloccano l'ordine
- `IBKR_CRITICAL_CODES`: codici critici (201, 203, 354, ecc.) che indicano rifiuto ordine
- `is_critical_ibkr_error(text)`: classifica un messaggio di errore usando codice numerico
  e fallback su keyword se il codice non è nelle mappe

**`execute_signal()`** ora distingue 5 esiti distinti con `tws_status` esplicito:

| Scenario | `status` | `tws_status` |
|----------|----------|--------------|
| Eccezione Python durante `place_bracket_order` | `"error"` | `"exception"` |
| TWS ritorna `{"error": ...}` (disconnesso/timeout) | `"error"` | `"tws_unavailable"` |
| Errori critici IBKR nel log (201, 203, 354...) | `"error"` | `"rejected"` |
| Solo messaggi informativi (2104, 2106...) | `"executed"` | `"submitted"` |
| Risposta senza `entry.order_id` valido | `"error"` | `"no_order_id"` |
| Successo confermato | `"executed"` | `"submitted"` |

**`_execute_and_save()`** aggiornato:
- Salva nel DB **anche i fallimenti** (`executed_ok=False`), permettendo audit completo
- `entry_order_id`, `tp_order_id`, `sl_order_id` sono `None` sui record falliti
- `error` field contiene il `reason` dal result di `execute_signal()`
- Log `WARNING` per i fallimenti, `INFO` per i successi

**`/api/v1/monitoring/execution-stats`** — nuovo endpoint di monitoring:
- Aggrega tutti i `ExecutedSignal` per `tws_status` nel periodo richiesto
- Calcola `success_rate_pct = submitted / (submitted + failed)` (esclude `skipped`)
- Top 10 simboli con più fallimenti
- **Target operativo**: `success_rate_pct >= 95%`. Valori inferiori indicano problemi
  sistematici di connessione TWS o configurazione contratti IBKR.

### Limitazioni note

- `IBKR_CRITICAL_CODES` e `IBKR_INFO_CODES` coprono i codici più frequenti ma non sono
  esaustive della documentazione IBKR. Se compaiono nuovi codici classificati erroneamente
  nei log, aggiornare le mappe in `ibkr_error_codes.py`.
- I record `ExecutedSignal` precedenti al fix hanno `tws_status` non standardizzato
  (valori come `"PendingSubmit"`, `"unknown"`, ecc.). Il campo `breakdown_by_status`
  dell'endpoint li mostra comunque, ma non contribuiscono ai bucket `submitted`/`failed`.

---

## Prezzo live TWS per current_price (staleness check)

**Data**: 2026-04-15
**File**: `backend/app/services/tws_service.py`, `backend/app/services/opportunities.py`,
`backend/app/schemas/opportunities.py`,
`backend/tests/services/test_live_price.py`

### Problema risolto

Prima di questo fix, `current_price` in `opportunities.py` era sempre `float(c.close)`,
cioè il close dell'**ultima candela completata nel DB**. Per timeframe 1h questo
significa fino a **60 minuti di latenza**: il sistema poteva segnalare `decision="execute"`
su setup dove il prezzo live era già 2–3% oltre l'entry da 30–45 minuti.
Il check di staleness (soglia 1%) scattava solo alla chiusura della candela successiva,
quando il momento ottimale di ingresso era ormai passato.

### Soluzione implementata

**`TWSService.get_last_price(symbol, timeout_s=2.0)`** — nuovo metodo in `tws_service.py`:
- Cache in-memory per simbolo con TTL 30s (`_LAST_PRICE_TTL_S`): evita N richieste TWS
  per lo stesso simbolo nello stesso ciclo di refresh
- Controlla `_connected` direttamente (non `_ensure_started()`) per non bloccare fino a 12s
- Delega a `_sync_get_last_price` via `run_in_executor` con timeout esterno `timeout_s + 0.5s`
- `_sync_get_last_price` usa `_async_live_quote` nel loop TWS con timeout interno 1.5s
- Estrae `quote.last`; fallback a mid `(bid + ask) / 2` se last non disponibile
- Non solleva mai eccezioni — ritorna `None` silenziosamente su qualsiasi errore

**`opportunities.py` — selezione `current_price`**:

```
1. Provider == "yahoo_finance" (US stock)?
   ├── Sì → TWS connesso e get_last_price ritorna valore?
   │         ├── Sì → current_price = live_price   (price_source="live_tws")
   │         └── No → candle close                  (price_source="candle_close")
   └── No (Binance crypto) → candle close            (price_source="candle_close")
```

**`OpportunityRow.price_source`** — nuovo campo nel response API:
- `"live_tws"`: prezzo da TWS (latenza < 30s)
- `"candle_close"`: close dell'ultima candela completata (fino a 1h di latenza su 1h TF)
- `"unavailable"`: nessun dato di prezzo disponibile

### Comportamento atteso

Con TWS attivo e connesso durante il market hours, il check di staleness opera sul
prezzo live anziché su un prezzo con potenziale 60 minuti di latenza. La finestra
di rilevamento viene ridotta da ~60 minuti a ~30 secondi (TTL cache).

### Limitazioni note

- TWS è configurato con `reqMarketDataType(3)` (delayed/frozen): fuori market hours
  o senza abbonamento real-time, il prezzo ha comunque 15–20 minuti di ritardo da
  exchange. Anche così, è significativamente migliore del close della candela 1h precedente.
- La cache TTL 30s è un compromesso: a parità di simbolo, nel peggiore dei casi il prezzo
  usato per lo staleness ha 30s di latenza. Accettabile per timeframe 1h.
- Per Binance (crypto), non esiste equivalente TWS. Il candle close resta l'unica fonte.

---

## Pipeline scheduler: parallelizzazione prewarm + auto_execute

**Data**: 2026-04-15
**File**: `backend/app/scheduler/pipeline_scheduler.py`,
`backend/tests/scheduler/test_parallel_execution.py`

### Problema risolto

In `_run_scheduled_pipeline_cycle`, `_prewarm_opportunities_cache` e `run_auto_execute_scan`
giravano sequenzialmente. Il prewarm ricalcola in parallelo tutte le combinazioni
`(provider, timeframe)` compresi i backtest aggregati e aggiungeva 5–15 secondi di
latenza totale. Su mercati veloci (breakout intraday) questo ritardo era critico:
il segnale era pronto nel DB, ma veniva inviato a TWS solo dopo che il prewarm finiva.

### Analisi di indipendenza (verificata)

- **`_prewarm_opportunities_cache`**: chiama `invalidate_all()` sulle 3 cache TTL
  in-memory (pattern_quality, trade_plan_backtest, variant_best), poi chiama
  `list_opportunities()` per 3 combo per ripopolarle. **Nessuna scrittura nel DB.**

- **`run_auto_execute_scan`**: chiama `list_opportunities()` con `decision="execute"`
  dal DB, poi `_execute_and_save()` → **scrive nel DB** (ExecutedSignal).
  Non dipende dalle cache in-memory per la correttezza della decisione execute.

- **`TTLCache.get_or_compute`** ha lock per-chiave con double-check: se prewarm e
  auto_execute calcolano la stessa chiave in parallelo, uno aspetta l'altro — nessun
  lavoro doppio per chiave, nessuna race condition.

**Conclusione**: completamente indipendenti per correttezza. La parallelizzazione è sicura.

### Soluzione implementata

```python
# Pipeline scheduler dopo il ciclo di refresh
async def _run_auto_execute_safe() -> None:
    try:
        await run_auto_execute_scan()
    except Exception:
        logger.exception("run_auto_execute_scan failed (ignored)")

t_parallel = time.perf_counter()
parallel_results = await asyncio.gather(
    _prewarm_opportunities_cache(),
    _run_auto_execute_safe(),
    return_exceptions=True,
)
logger.info("prewarm+auto_execute completati in %.0fms (parallelo)", ...)

# poll_and_record_stop_fills rimane sequenziale DOPO il gather
```

Logging metrica `prewarm+auto_execute completati in Xms (parallelo)` per monitorare
il guadagno effettivo. Con prewarm ~10s e auto_execute ~2s, il totale scende da ~12s
a ~10s (max dei due invece della somma).

### Test di regressione

`tests/scheduler/test_parallel_execution.py` (4 test):
1. **Verifica parallelismo** con `asyncio.sleep(0.3)` su entrambi: wall time < 0.5s
2. **Eccezione in prewarm** non blocca auto_execute (return_exceptions=True)
3. **Eccezione in auto_execute** non blocca prewarm
4. **Ordine sequenziale** di poll_and_record_stop_fills: inizia solo dopo il gather

### Limitazione nota

La parallelizzazione assume indipendenza dei due task. Se in futuro
`_prewarm_opportunities_cache` venisse esteso per modificare lo stato delle
opportunità nel DB (es. ricalcolo `decision`), l'ordine sequenziale dovrebbe
essere ripristinato. Documentato nel commento al codice.

---

## Auto-execute scan: timeframe e provider config-driven + fix break prematuro

**Data**: 2026-04-15
**File**: `backend/app/services/auto_execute_service.py`, `backend/app/core/config.py`,
`backend/app/api/v1/routes/monitoring.py`,
`backend/tests/services/test_auto_execute_scan.py`

### Problemi risolti

**Bug A — hardcode `1h` + `yahoo_finance` in `run_auto_execute_scan`**: lo scan globale
post-ciclo era hardcodato su una sola combinazione, ignorando Binance e qualsiasi
timeframe diverso da 1h.

**Bug B — `break` prematuro in `maybe_ibkr_auto_execute_after_pipeline`**: l'hook
per-simbolo interrompeva il loop dopo il primo ordine inviato. Con 2+ segnali validi
contemporanei sullo stesso simbolo/timeframe, solo il primo veniva processato.

### Soluzione implementata

**`config.py`** — due nuove variabili d'ambiente:

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `AUTO_EXECUTE_TIMEFRAMES_ENABLED` | `1h` | Timeframe abilitati (comma-separated) |
| `AUTO_EXECUTE_PROVIDERS_ENABLED` | `yahoo_finance,binance` | Provider abilitati |

Le properties `auto_execute_timeframes_list` / `auto_execute_providers_list` espongono
le liste parsed (già splittate e strippate).

**5m è esplicitamente escluso di default** (valore non in `AUTO_EXECUTE_TIMEFRAMES_ENABLED`):
Strada A è validata solo su 1h. Eseguire automaticamente segnali 5m senza un dataset
OOS dedicato equivale a operare alla cieca. Aggiungere `5m` solo dopo aver costruito
e misurato WR e avg_R out-of-sample su timeframe 5m.

**`auto_execute_service.py`** — costanti e logica aggiornate:

```python
MAX_ORDERS_PER_HOOK_INVOCATION = 5   # cap per maybe_ibkr_auto_execute_after_pipeline
MAX_ORDERS_PER_SCAN = 10             # cap globale per run_auto_execute_scan
```

`run_auto_execute_scan` ora:
- Legge `settings.auto_execute_providers_list` e `settings.auto_execute_timeframes_list`
- Itera su tutte le combinazioni (provider, timeframe) con doppio loop
- Un errore su una combinazione viene loggato e non blocca le altre (`continue`)
- Interrompe il loop globalmente quando `total_executed >= MAX_ORDERS_PER_SCAN`
- Logga il riepilogo finale (executed, errors, cap_reached, providers, timeframes)

`maybe_ibkr_auto_execute_after_pipeline` ora:
- Controlla `body.provider` contro `auto_execute_providers_list` (non più hardcoded `yahoo_finance`)
- Controlla `body.timeframe` contro `auto_execute_timeframes_list` (5m escluso di default)
- Rimuove il `break` prematuro → processa tutti i segnali execute nel limite del cap
- Cap esplicito `MAX_ORDERS_PER_HOOK_INVOCATION = 5` con log warning al raggiungimento

**`/api/v1/monitoring/auto-execute-config`** — nuovo endpoint read-only che mostra:
- Flag di sistema (tws_enabled, ibkr_auto_execute, ibkr_paper_trading)
- Timeframe e provider abilitati
- Safety caps attivi
- Note operative su 5m e come modificare la configurazione

### Comportamento atteso

Con la configurazione default (1h, yahoo_finance+binance):
- `run_auto_execute_scan` processa fino a 10 ordini per ciclo su 2 combinazioni (yahoo/1h, binance/1h)
- `maybe_ibkr_auto_execute_after_pipeline` processa fino a 5 ordini per simbolo/ciclo
- Segnali 5m non vengono mai auto-eseguiti finché `AUTO_EXECUTE_TIMEFRAMES_ENABLED` non include `5m`

---

## Migrazione provider 1h da yfinance a IBKR

**Data**: 2026-04-15  
**File**: `backend/app/services/ibkr_ingestion.py`, `backend/app/services/tws_service.py`, `backend/app/core/config.py`

### Problema

yfinance presentava timeout sistematici (`curl 28`, 10–30s per simbolo) che facevano crescere il ciclo pipeline da 3–4 min a 9+ min, causando lo skip dei cicli successivi in APScheduler.

### Soluzione

I 40 simboli azionari USA usano IBKR TWS (`reqHistoricalData` via `ib_insync`) invece di yfinance per le candele 1h. Il dato viene salvato con gli stessi campi DB (`provider="yahoo_finance"`, `exchange="YAHOO_US"`) per compatibilità completa con tutto il sistema (opportunities, validator, backtest).

### Architettura

| Layer | Prima | Dopo |
|-------|-------|------|
| Scheduler routing | `"provider": "yahoo_finance"` hardcoded | `settings.equity_provider_1h` (default `"ibkr"`) |
| Router dispatch | `if provider == "yahoo_finance"` | aggiunto `elif provider == "ibkr"` |
| Ingestion class | `YahooFinanceIngestionService` | `IBKRIngestionService` (nuovo) |
| Dati salvati in DB | `provider="yahoo_finance"`, `exchange="YAHOO_US"` | **invariato** (compatibilità) |

### Configurazione

- `EQUITY_PROVIDER_1H=ibkr` (default) — usa TWS
- `EQUITY_PROVIDER_1H=yahoo_finance` — fallback al provider precedente (per debug/emergenza)

### Metodo TWS aggiunto

`TWSService.get_historical_candles(symbol, timeframe, limit)`:
- Fail-fast su `self._connected` (non blocca 12s come `_ensure_started()`)
- Calcola `durationStr` IBKR dal limite di barre richieste (`limit=50` → `"10 D"`)
- Scarta l'ultima barra in formazione (stessa semantica di Yahoo Finance e Binance)
- Timeout 20s; ritorna `None` silenziosamente su errori o disconnessione

### Limiti IBKR e mitigazione

- Max 6 richieste storiche concurrent (pacing limit IBKR)
- Mitigazione: `_IBKR_HIST_SEMAPHORE = asyncio.Semaphore(5)` in `ibkr_ingestion.py`

### Sottoscrizioni IBKR richieste (~$4.50/mese)

NASDAQ Network C/UTP, NYSE Network A/CTA, NYSE American/BATS/ARCA Network B

### Invariato

- Binance per crypto (funziona bene)
- Alpaca per 5m azionari (funziona bene)
- yfinance per `^VIX` in `opportunities.py` (non disponibile su equity bundle IBKR)

### Endpoint di test

`GET /api/v1/health/ibkr-historical?symbol=AAPL&timeframe=1h&limit=10`  
Ritorna `{status, candles_received, first_timestamp, last_timestamp, sample_close}`.

---

## Espansione mercati: UK (London Stock Exchange) — Fase 1

**Data**: 2026-04-16
**File**: `backend/app/core/uk_universe.py`, `backend/app/core/config.py`, `backend/app/services/tick_size.py`

**Stato**: Fase 1 di 3 completata. Sistema preparato per ricevere simboli UK ma:
- Scheduler non ancora configurato per ingestare UK
- Validator non gestisce orari LSE
- Auto-execute UK disabilitato di default (`uk_auto_execute_enabled=False`)

**Universo**: 30 simboli FTSE 100 più liquidi.

**Tick size**: implementati i 5 livelli LSE (0.01p / 0.05p / 0.1p / 0.5p / 1p).

| Fascia prezzo (pence) | Tick size (pence) |
|---|---|
| < 100p | 0.01p |
| 100–499p | 0.05p |
| 500–999p | 0.1p |
| 1000–4999p | 0.5p |
| >= 5000p | 1.0p |

**Particolarità**: prezzi UK quotati in penny GBp (1/100 GBP). Es. "AZN" 12500 GBp = £125. Il tick size è anch'esso in pence.

**Conflitti simbolo USA/UK identificati**:
- `BA.` → BAE Systems su LSE usa il ticker IBKR `"BA."` (con punto). Boeing NYSE usa `"BA"` senza punto. Nessun conflitto immediato; le trappole sono documentate in `uk_universe.py`.
- `RIO` → Rio Tinto: primo listing LSE (`"RIO"`) e ADR NYSE (`"RIO"`). Non nell'universo USA attuale ma da monitorare.

**Configurazione aggiunta**:
- `ENABLE_UK_MARKET=false` — default OFF; abilita esplicitamente in `.env` quando pronto per Fase 2.
- `UK_AUTO_EXECUTE_ENABLED=false` — auto-execute UK sempre separato dal flag principale.

**Limitazioni note Fase 1** (risolte in Fase 2):
- Valuta hardcoded a USD, filtro orario non LSE-aware, scheduler non UK-aware.

---

## Espansione mercati UK — Fase 2

**Data**: 2026-04-16
**File**: `backend/app/core/hour_filters.py`, `backend/app/core/extract_scope.py`,
`backend/app/core/trade_plan_variant_constants.py`, `backend/app/schemas/market_data.py`,
`backend/app/schemas/pipeline.py`, `backend/app/services/tws_service.py`,
`backend/app/services/ibkr_ingestion.py`, `backend/app/services/pipeline_refresh.py`,
`backend/app/scheduler/pipeline_scheduler.py`, `backend/app/services/opportunity_validator.py`,
`backend/app/services/opportunities.py`, `backend/app/services/auto_execute_service.py`,
`backend/app/api/v1/routes/health.py`

**Stato**: Fase 2 completata. UK attivo in modalità "raccolta dati" quando `ENABLE_UK_MARKET=true`:
- 30 simboli FTSE 100 ingestati ogni ciclo via IBKR TWS (exchange="LSE", currency="GBP")
- Dati salvati nel DB come `provider="ibkr"`, `exchange="LSE"` (nessun alias legacy YAHOO_US)
- Pattern detection e opportunità generate normalmente
- **Decision forzata a "monitor"**: tutti i 30 simboli in `DATA_COLLECTION_SYMBOLS_UK`, nessuno in `VALIDATED_SYMBOLS_UK` → mai "execute"
- Doppio gate sicurezza: (1) validator forza "monitor", (2) `uk_auto_execute_enabled=False`

**Architettura dati UK vs USA:**

| Layer | US IBKR | UK IBKR |
|---|---|---|
| Ingest exchange param | `"SMART"` | `"LSE"` |
| DB provider | `"yahoo_finance"` (alias legacy) | `"ibkr"` (nativo) |
| DB exchange | `"YAHOO_US"` (alias legacy) | `"LSE"` (nativo) |
| Extract coordinates | yahoo_finance/YAHOO_US | ibkr/LSE |
| Regime filter | SPY-based | None (nessun benchmark UK) |

**Filtro orario LSE** (`hour_filters.py`):
- `EXCLUDED_HOURS_UTC_LSE = {0,1,2,3,4,5,6,17,18,19,20,21,22,23}`
- Ore operative: 7–16 UTC (copre sia BST 7:00-15:30 che GMT 8:00-16:30)

**Endpoint test**: `GET /api/v1/health/uk-status`
- Verifica connessione TWS e prezzo live AZN/LSE
- Espone flags, conteggi universo, ore escluse

**Prossimo step (Fase 3, tra 3-6 mesi)**: dopo 3-6 mesi di accumulo dataset UK:
1. Costruire validation set UK-specifico (pattern OOS)
2. Misurare WR/avg_R per pattern su UK
3. Popolare `VALIDATED_SYMBOLS_UK` per i simboli con edge
4. Solo allora abilitare `uk_auto_execute_enabled=True`

**Limitazioni note Fase 2**:
- Strada A NON validata su UK. Tutti i trade UK sono "monitor" per design.
- `_sync_live_quote`, `_sync_market_depth`, `_sync_bid_ask_history` in `tws_service.py` ancora hardcodati su SMART/USD (usati per spread check e market depth, non per ingestione UK). Refactor in Fase 3.
- Spread UK da osservare live: possibile bisogno di filtro aggiuntivo se spread > 0.5% sistematici.
- Prezzi UK in pence (1/100 GBP) — gestiti da tick_size, verificare nei log la plausibilità (es. AZN ~12500p, LLOY ~65p).

---

## UK Regime Filter — Fase 4A

**Data**: 2026-04-18
**File**:
- `backend/app/services/uk_regime.py` (nuovo)
- `backend/app/services/regime_filter_service.py` (esteso)
- `backend/app/services/opportunity_validator.py` (esteso)
- `backend/app/services/opportunities.py` (esteso)
- `backend/app/core/uk_universe.py` (esteso)
- `backend/scripts/backfill_uk_historical.py` (esteso)
- `backend/scripts/batch_pipeline_uk.py` (esteso)
- `backend/app/api/v1/routes/health.py` (esteso)

### Problema risolto

La Fase 3D aveva mostrato UK WR=45.8% vs USA WR=56.9% (-11.1pp). Causa principale
identificata: il regime filter SPY 1d era applicato solo per `provider="yahoo_finance"` e
`provider="binance"`. Per `provider="ibkr"` (simboli UK/LSE) il filtro era esplicitamente
bypassato (`regime_filter=None` in `opportunities.py`) perché non esisteva un benchmark UK.

Risultato: pattern contro-trend UK (`engulfing_bullish`, `macd_divergence_bull`,
`rsi_divergence_bull`) venivano eseguiti in qualsiasi regime macro, mentre in USA vengono
attivati SOLO in regime bearish (EV bear=+0.16-0.86R vs EV bull=-0.13-+0.18R).

### Soluzione implementata

**Proxy macro UK**: `ISF.L` (iShares Core FTSE 100 UCITS ETF), quotato LSE.
- Replica FTSE 100 con tracking error <0.1% annuo
- Ingestabile via IBKR con abbonamento già attivo
- Prezzi in pence come gli altri simboli UK

**Formula regime**: identica a USA — `price_vs_ema50_pct` = (close − EMA50) / EMA50 × 100
- > +2% → solo `bullish`
- < −2% → solo `bearish`
- ±2% → `neutral` (entrambe)

### Architettura

| Layer | USA | UK |
|---|---|---|
| Regime anchor | `SPY` / `yahoo_finance` / `YAHOO_US` / `1d` | `ISF.L` / `ibkr` / `LSE` / `1d` |
| Formula | `price_vs_ema50_pct > ±2%` | identica |
| Caricamento | `load_regime_filter(provider="yahoo_finance")` | `load_regime_filter(provider="ibkr")` |
| Pattern BEAR-only | `PATTERNS_BEAR_REGIME_ONLY` (riusato) | stesso set (riusato) |

### Pattern contro-trend filtrati (`PATTERNS_BEAR_REGIME_ONLY`)

```python
{"engulfing_bullish", "macd_divergence_bull", "rsi_divergence_bull"}
```
Attivati per UK SOLO se `ISF.L.price_vs_ema50_pct < −2%` (regime bearish).

### Tabella architettura aggiornata

| Layer | US IBKR | UK IBKR |
|---|---|---|
| Regime filter | SPY 1d (yahoo_finance) | ISF.L 1d (ibkr/LSE) — **NUOVO Fase 4A** |
| Formula regime | EMA50 ±2% | identica |

### Backfill ISF.L

```bash
# 5 anni di daily ISF.L — una singola chiamata IBKR
docker compose exec backend python -m scripts.backfill_uk_historical \
    --symbols ISF.L --years 5 --timeframe 1d
```

### Processing ISF.L 1d (features → indicators → context → patterns)

```bash
docker compose exec backend python -m scripts.batch_pipeline_uk \
    --symbols ISF.L --timeframe 1d
```

### Endpoint verifica

`GET /api/v1/health/uk-status` ora include:
```json
"uk_regime": {
    "current": "bullish | bearish | neutral | no_data",
    "anchor_symbol": "ISF.L",
    "anchor_last_close": 824.5,
    "anchor_ema50": 810.2,
    "anchor_price_vs_ema50_pct": 1.76,
    "anchor_last_date": "2026-04-17",
    "formula": "price_vs_ema50_pct > +2% → bullish | < -2% → bearish (mirror SPY USA)"
}
```

### Stato Fase 4A

- Codice integrato e verificato (zero linter errors)
- Backfill ISF.L 1d: da eseguire con TWS connesso in orario mercato UK
- Processing pipeline ISF.L: da eseguire dopo backfill
- **Auto-execute UK**: resta OFF
- **Fase 4B**: ri-validazione `build_validation_dataset.py --exchange LSE` con regime attivo,
  confronto WR UK pre/post filtro (attesa: aumento verso 55-57%)

---
