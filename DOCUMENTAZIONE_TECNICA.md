# Documentazione Tecnica — intraday-market-screener

> Versione: 1.0 — Aprile 2026  
> Documento generato dall'analisi completa del codice sorgente. Copre architettura, flussi dati, formule, logica di scoring, decisioni operative e interfaccia utente.

---

## Indice

1. [Cos'è questa applicazione](#1-cosè-questa-applicazione)
2. [Architettura generale](#2-architettura-generale)
3. [Infrastruttura Docker](#3-infrastruttura-docker)
4. [Database — modelli ORM e relazioni](#4-database--modelli-orm-e-relazioni)
5. [Pipeline dati — flusso completo](#5-pipeline-dati--flusso-completo)
6. [Feature extraction — calcoli dettagliati](#6-feature-extraction--calcoli-dettagliati)
7. [Indicator extraction — tutti gli indicatori](#7-indicator-extraction--tutti-gli-indicatori)
8. [Context extraction — classificazione mercato](#8-context-extraction--classificazione-mercato)
9. [Pattern extraction — tutti i pattern rilevati](#9-pattern-extraction--tutti-i-pattern-rilevati)
10. [Pattern staleness — età e freschezza](#10-pattern-staleness--età-e-freschezza)
11. [Pattern quality score — formula completa](#11-pattern-quality-score--formula-completa)
12. [Screener scoring — punteggio strutturale](#12-screener-scoring--punteggio-strutturale)
13. [Final opportunity score — formula completa v2](#13-final-opportunity-score--formula-completa-v2)
14. [Trade plan engine — costruzione entry/stop/TP](#14-trade-plan-engine--costruzione-entrystoptp)
15. [Trade plan backtest — simulazione storica](#15-trade-plan-backtest--simulazione-storica)
16. [Trade plan variant backtest](#16-trade-plan-variant-backtest)
17. [Trade plan live adjustment](#17-trade-plan-live-adjustment)
18. [Opportunity validator — decisione operativa](#18-opportunity-validator--decisione-operativa)
19. [Sistema alert — Telegram e Discord](#19-sistema-alert--telegram-e-discord)
20. [Auto-execute TWS (Interactive Brokers)](#20-auto-execute-tws-interactive-brokers)
21. [Machine Learning scorer (opzionale)](#21-machine-learning-scorer-opzionale)
22. [Monte Carlo](#22-monte-carlo)
23. [Cache sistema](#23-cache-sistema)
24. [API endpoints — riferimento completo](#24-api-endpoints--riferimento-completo)
25. [Frontend — pagina opportunità](#25-frontend--pagina-opportunità)
26. [Position sizing (frontend)](#26-position-sizing-frontend)
27. [Configurazione completa (.env)](#27-configurazione-completa-env)
28. [Scheduler — comportamento temporale](#28-scheduler--comportamento-temporale)

---

## 1. Cos'è questa applicazione

**intraday-market-screener** è uno screener di mercato intraday automatizzato. Il suo scopo è identificare, classificare e presentare in tempo reale le migliori opportunità operative su azioni USA (tramite Yahoo Finance) e criptovalute (tramite Binance), con possibilità di integrazione opzionale con Alpaca (azioni US con dati più granulari) e Interactive Brokers TWS per l'esecuzione automatica degli ordini.

### Cosa fa concretamente

1. **Raccoglie dati OHLCV** (Open, High, Low, Close, Volume) periodicamente da più sorgenti di mercato.
2. **Calcola feature, indicatori tecnici e contesto di mercato** per ogni barra di ogni serie.
3. **Rileva pattern su candele** usando una libreria di 32+ detector algoritmici (non ML nel rilevamento, solo regole).
4. **Produce un punteggio composito** (`final_opportunity_score`) per ogni opportunità, combinando qualità strutturale del mercato, allineamento del pattern con la direzione dello screener, qualità storica del pattern da backtest, e forza del segnale corrente.
5. **Genera un piano di trade** (entry, stop, take profit, R/R) per ogni opportunità rilevata.
6. **Classifica ogni opportunità** come `execute` (segnale operativo immediato), `monitor` (da tenere d'occhio) o `discard` (scartata per criteri oggettivi).
7. **Invia notifiche** su Telegram e Discord per le opportunità di alta priorità.
8. **Esegue automaticamente ordini bracket** su Interactive Brokers TWS se configurato.
9. **Espone una UI web** (Next.js) che mostra in tempo reale tutte le opportunità ordinate per score.

### Stack tecnologico

| Layer | Tecnologia |
|-------|------------|
| Backend API | Python 3.11+, FastAPI, uvicorn |
| ORM / DB | SQLAlchemy (asyncio), asyncpg, PostgreSQL 16 |
| Scheduler | APScheduler 3.x (in-process, AsyncIOScheduler) |
| Dati mercato | ccxt (Binance), yfinance (Yahoo), Alpaca SDK (opzionale) |
| Broker | ib-insync (TWS socket), IBKR Client Portal REST |
| Machine Learning | LightGBM, scikit-learn, joblib |
| Statistica | scipy (Wilson CI, binomiale, t-test) |
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| Containerizzazione | Docker Compose |

---

## 2. Architettura generale

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SORGENTI DATI                                │
│  Binance (ccxt)   Yahoo Finance (yfinance)   Alpaca (opzionale)    │
└────────────────────┬────────────────────────────────────────────────┘
                     │ OHLCV periodico
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PIPELINE (APScheduler)                           │
│                                                                     │
│  Ingest ──► Features ──► Indicators ──► Context ──► Patterns       │
│                                                          │          │
│                              (post-pipeline hooks)       │          │
│  Cache invalidation ◄────────────────────────────────────┤          │
│  Alert Telegram/Discord ◄────────────────────────────────┤          │
│  Auto-execute TWS ◄──────────────────────────────────────┘          │
└──────────────────────────────────────────────────────────┬──────────┘
                                                           │
                                                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    FASTAPI BACKEND (:8000)                          │
│                                                                     │
│  GET /opportunities  ──►  list_opportunities()                      │
│                              │                                      │
│                              ├── screener_scoring                   │
│                              ├── pattern_quality (cache)            │
│                              ├── opportunity_final_score            │
│                              ├── pattern_timeframe_policy           │
│                              ├── trade_plan_backtest (cache)        │
│                              ├── trade_plan_live_adjustment         │
│                              ├── staleness decay                    │
│                              ├── opportunity_validator              │
│                              ├── trade_plan_engine                  │
│                              └── ml_signal_scorer (opzionale)       │
└──────────────────────────────────────────────────────────┬──────────┘
                                                           │ JSON
                                                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   NEXT.JS FRONTEND (:3000)                          │
│   Pagina Opportunità  │  Pagina Backtest  │  Diagnostica            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Infrastruttura Docker

Il file `docker-compose.yml` definisce tre servizi:

### postgres
- Immagine: `postgres:16-alpine`
- Volume persistente: `postgres_data:/var/lib/postgresql/data`
- `shm_size: 512mb` per operazioni di sort/hash su tabelle grandi
- Healthcheck: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` ogni 5s, max 5 retry
- Porta esposta: `$POSTGRES_PORT:5432` (default 5432)

### backend
- Build da `./backend/Dockerfile`
- Dipende da `postgres` con condizione `service_healthy` (non parte finché Postgres non risponde)
- Comando: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Volume mount `./backend:/app`: il codice sorgente è montato live (no rebuild per modifiche Python)
- Volume `./eda_output:/app/eda_output:ro`: cartella analisi esplorative (read-only)
- Tutta la configurazione passa da `.env`

### frontend
- Build da `./docker/Dockerfile.frontend`
- Dipende dal backend
- Volume mount `./frontend:/app`: codice live
- Volume `/app/node_modules`: evita che i moduli host sovrascrivano quelli del container
- Volume `frontend_next_cache:/app/.next`: cache build Next.js persistente
- `NEXT_PUBLIC_API_URL` punta al backend (default `http://localhost:8000`)
- `NODE_OPTIONS=--max-old-space-size=4096`: aumenta heap Node per build grandi
- Limite memoria Docker: 4GB

---

## 4. Database — modelli ORM e relazioni

Il database PostgreSQL contiene 7 tabelle. Le prime 5 formano una catena di derivazione:

```
candles (OHLCV)
  │
  ├──► candle_features (1:1, FK CASCADE)
  │         │
  │         ├──► candle_contexts (1:1, FK CASCADE)
  │         │
  │         └──► candle_patterns (N:1, FK CASCADE)
  │                   │
  │                   └──► candle_contexts (FK SET NULL, opzionale)
  │
  └──► candle_indicators (1:1, FK CASCADE)

alerts_sent             (deduplica alert legacy)
alert_notifications_sent (deduplica notifiche post-pipeline)
executed_signals        (log ordini auto-eseguiti)
```

### Tabella `candles`

La tabella radice. Ogni riga è una barra OHLCV univoca.

| Campo | Tipo | Significato |
|-------|------|-------------|
| `id` | int PK | Surrogate key |
| `asset_type` | String(16), default `crypto` | Tipo strumento: `crypto`, `stock`, `etf` |
| `provider` | String(32), default `binance` | Sorgente: `binance`, `yahoo_finance`, `alpaca` |
| `symbol` | String(32) | Es. `BTC/USDT`, `SPY`, `AAPL` |
| `exchange` | String(32) | Venue: `binance`, `NASDAQ`, `NYSE` |
| `timeframe` | String(16) | Es. `5m`, `1h`, `1d` |
| `market_metadata` | JSONB nullable | Metadati aggiuntivi (nome, settore, ecc.) |
| `timestamp` | timestamptz | Inizio barra (UTC) |
| `open`, `high`, `low`, `close` | Numeric | Prezzi OHLC |
| `volume` | Numeric | Volume della barra |
| `created_at` | timestamptz, default `now()` | Timestamp inserimento |

**Vincolo univoco:** `(exchange, symbol, timeframe, timestamp)` — nessuna barra duplicata.  
**Indici:** `(exchange, symbol, timeframe)`, `timestamp`.

### Tabella `candle_features`

Una riga per ogni candela. Calcolata da `extract_features`.

| Campo | Tipo | Significato |
|-------|------|-------------|
| `candle_id` | int FK → candles.id CASCADE | Link alla candela |
| `body_size` | Numeric | Proporzione del corpo sul range totale |
| `range_size` | Numeric | `high - low` in unità di prezzo |
| `upper_wick` | Numeric | Proporzione dello stoppino superiore |
| `lower_wick` | Numeric | Proporzione dello stoppino inferiore |
| `close_position_in_range` | Numeric | Dove chiude la candela nel suo range: 0=bottom, 1=top |
| `pct_return_1` | Numeric nullable | Rendimento % vs barra precedente |
| `volume_ratio_vs_prev` | Numeric nullable | Volume / volume barra precedente |
| `is_bullish` | Boolean | `close >= open` |

**Vincolo univoco:** `candle_id` — esattamente una feature per candela.

### Tabella `candle_indicators`

Una riga per ogni candela. Calcolata da `extract_indicators`. Contiene decine di colonne:

- EMA9, EMA20, EMA50, RSI14, ATR14
- Volume MA20
- Swing high/low precedenti, distanze strutturali %
- VWAP sessione, OR high/low (solo Yahoo)
- Fibonacci levels (38.2%, 50%, 61.8%, 78.6%)
- Fair Value Gap (FVG: presenza, tipo, livelli)
- Order Block (OB: presenza, tipo, zona)
- CVD (Cumulative Volume Delta), CVD trend
- Relative Strength vs SPY (solo Yahoo, simboli non-SPY)
- Funding rate bias (solo Binance)

**Vincolo univoco:** `candle_id`.

### Tabella `candle_contexts`

Una riga per ogni candela (via candle_feature). Calcolata da `extract_context`.

| Campo | Tipo | Valori |
|-------|------|--------|
| `candle_feature_id` | FK | Link alla feature (CASCADE) |
| `market_regime` | String | `trend`, `range`, `neutral`, `choppy`, `volatile` |
| `volatility_regime` | String | `high`, `normal`, `low` |
| `candle_expansion` | String | `expansion`, `normal`, `compression` |
| `direction_bias` | String | `bullish`, `bearish`, `neutral` |

**Vincolo univoco:** `candle_feature_id`.

### Tabella `candle_patterns`

Ogni riga è un pattern rilevato su una specifica candela. Più pattern possono coesistere sulla stessa candela (es. engulfing + rsi_divergence).

| Campo | Tipo | Significato |
|-------|------|-------------|
| `candle_feature_id` | FK CASCADE | Candela su cui è rilevato |
| `candle_context_id` | FK SET NULL | Contesto al momento del rilevamento |
| `pattern_name` | String | Es. `engulfing_bullish`, `bull_flag` |
| `pattern_strength` | Numeric | Score 0–1 (euristico, specifico del detector) |
| `direction` | String | `bullish`, `bearish`, `neutral` |

**Vincolo univoco:** `(candle_feature_id, pattern_name)` — un pattern per nome per candela.

### Tabella `alerts_sent`

Deduplica degli alert "legacy" (inviati da `alert_service`).

**Vincolo univoco:** `(symbol, timeframe, provider, pattern_name, direction, bar_hour_utc)` — un alert per ora per combinazione. Questo previene lo spam se il pipeline gira più volte nella stessa ora.

### Tabella `alert_notifications_sent`

Deduplica delle notifiche post-pipeline (inviate da `alert_notifications`).

**Vincolo univoco:** `(exchange, symbol, timeframe, context_timestamp)` — un alert per contesto. Se il contesto non cambia (stesso `context_timestamp`), non viene reinviata la notifica anche se il pipeline rigira.

### Tabella `executed_signals`

Log degli ordini auto-eseguiti via TWS. Non ha FK verso le altre tabelle (log applicativo puro).

Campi chiave: `symbol`, `timeframe`, `direction`, `pattern_name`, `opportunity_score`, prezzi entry/stop/TP1/TP2, quantità, order ID TWS per entry/TP/SL, `tws_status`, `error`, `executed_at`.

---

## 5. Pipeline dati — flusso completo

### Orchestratore: `execute_pipeline_refresh`

Il file `backend/app/services/pipeline_refresh.py` contiene la funzione centrale che esegue l'intera pipeline per un set di simboli/timeframe. Viene chiamata sia dall'endpoint `POST /api/v1/pipeline/refresh` (manualmente dalla UI) sia dallo scheduler automatico.

**Ordine di esecuzione:**

```
1. INGEST  ──────────► candles
2. extract_features ──► candle_features
3. extract_indicators ► candle_indicators
4. extract_context ───► candle_contexts
5. extract_patterns ──► candle_patterns
6. maybe_send_pattern_alerts_after_pipeline   (try/except, non bloccante)
7. maybe_notify_after_pipeline_refresh        (se ALERT_LEGACY_ENABLED)
8. invalidate_opportunity_lookups_after_pipeline
9. maybe_ibkr_auto_execute_after_pipeline     (try/except, non bloccante)
```

Ogni step riceve un `request` con filtri (provider, exchange, symbol, timeframe, limit, lookback) e produce una `response` con conteggi di righe processate.

### Routing dell'ingest

Il routing della sorgente dati avviene in base al `provider` del job:

- **`yahoo_finance`**: usa `YahooFinanceIngestionService`. Il `ingest_limit` viene sostituto da `settings.pipeline_ingest_limit_5m` per timeframe `5m`/`15m` (finestre più corte perché Yahoo ha più storico disponibile per TF brevi).
- **`alpaca`** (se `settings.alpaca_enabled`): usa `AlpacaIngestionService`. La finestra temporale è calcolata dinamicamente: ultime 2h per `5m`, ultime 26h per `1h`.
- **default / `binance`**: usa `MarketDataIngestionService` con ccxt.

### Scheduler APScheduler

Il file `backend/app/scheduler/pipeline_scheduler.py` gestisce l'esecuzione periodica.

**Comportamento:**
- Ogni `PIPELINE_REFRESH_INTERVAL_SECONDS` secondi esegue un ciclo completo
- I job vengono eseguiti in **parallelo fino a 4 contemporaneamente** (Semaphore(4))
- Ogni singolo job ha **timeout 120 secondi** (via `asyncio.wait_for`)
- Se un job fallisce 3 volte consecutive, viene loggato un alert
- Dopo ogni ciclo completo, esegue il **pre-warm della cache opportunità**

**Job di manutenzione:**
- Ogni 24h: `cleanup_old_alerts(days_to_keep=7)` — elimina record vecchi da `alerts_sent`
- Ogni 2 minuti (se TWS abilitato): `update_live_candles()` — aggiorna candela 1h parziale

**Modalità di risoluzione dei job:**
- `explicit` / `validated_1h` / `universe`: lista esplicita di dict `{provider, symbol, timeframe, ...}`
- `legacy`: prodotto cartesiano di `PIPELINE_SYMBOLS × PIPELINE_TIMEFRAMES` su Binance
- `registry_full`: usa un registry di job filtrati per tag

---

## 6. Feature extraction — calcoli dettagliati

File: `backend/app/services/feature_extraction.py`

Questo step calcola feature geometriche per ogni candela. Tutte le operazioni usano `Decimal` per precisione numerica.

### Calcoli per candela

```
range_size        = high - low

body_size         = |close - open| / range_size
                    (proporzione del corpo sul range totale: 0 = doji puro, 1 = marubozu)

upper_wick        = (high - max(open, close)) / range_size
                    (stoppino superiore come proporzione del range)

lower_wick        = (min(open, close) - low) / range_size
                    (stoppino inferiore come proporzione del range)

close_position_in_range = (close - low) / (high - low)
                    (dove chiude nel range: 0.0 = al minimo, 1.0 = al massimo)

is_bullish        = close >= open
```

**Nota:** se `range_size <= 0` (candela doji con high=low), le proporzioni non vengono calcolate e rimangono None.

### Calcoli che richiedono la candela precedente

```
pct_return_1      = (close - prev_close) / prev_close * 100
                    (rendimento percentuale rispetto alla barra precedente)

volume_ratio_vs_prev = volume / prev_volume
                    (quanto volume ha questa barra rispetto alla precedente:
                     > 1 = volume crescente, < 1 = volume calante)
```

Per la prima candela di ogni serie o se manca la precedente, questi campi sono `None`.

### Logica query

Per ogni serie `(exchange, symbol, timeframe)`, vengono caricate le ultime `limit + 1` candele ordinate cronologicamente (DESC poi invertite). La prima candela serve solo come "prev" per la seconda: non produce una riga di feature. Il risultato è `limit` righe di feature per serie.

---

## 7. Indicator extraction — tutti gli indicatori

File: `backend/app/services/indicator_extraction.py` (~1467 righe)

Questo è il modulo più complesso della pipeline. Calcola indicatori tecnici senza dipendenze da pandas-ta o ta-lib — tutto in puro Python/float/Decimal per massima portabilità e controllo.

### EMA (Exponential Moving Average)

Periodi: 9, 20, 50. Formula standard:

```
alpha = 2 / (period + 1)
EMA[0] = close[0]
EMA[i] = close[i] * alpha + EMA[i-1] * (1 - alpha)
```

Le prime N barre (warm-up) producono EMA con meno dati: questo è corretto e accettato.

### RSI (Relative Strength Index) — metodo Wilder

Periodo: 14. Il metodo Wilder usa smoothing diverso da EMA standard:

```
alpha_wilder = 1 / period     (invece di 2/(period+1))

Per le prime 14 barre: media aritmetica di gain/loss
Da barra 14+:
  avg_gain = avg_gain * (period-1)/period + max(delta, 0) / period
  avg_loss = avg_loss * (period-1)/period + max(-delta, 0) / period
  RS = avg_gain / avg_loss
  RSI = 100 - 100 / (1 + RS)
```

### ATR (Average True Range) — metodo Wilder

Periodo: 14.

```
TR = max(high - low, |high - prev_close|, |low - prev_close|)
Prime 14 barre: ATR = media aritmetica dei TR
Successive: ATR = (ATR_prev * (period-1) + TR) / period
```

### Volume MA

Periodo: 20. Media mobile semplice sul volume delle ultime 20 barre.

### Swing High/Low

Finestra: 5 barre. Un punto è swing high se è il massimo nelle 5 barre centrate su di esso (2 prima, 2 dopo). Analogo per swing low.

```
swing_high[i] = True se high[i] == max(high[i-2 : i+3])
swing_low[i]  = True se low[i]  == min(low[i-2 : i+3])
```

Vengono salvati i valori degli ultimi swing high/low e le loro distanze percentuali dal close corrente.

### VWAP (Volume Weighted Average Price)

**Per Yahoo Finance (azioni):** VWAP di sessione. La sessione US è 14:30–21:00 UTC. Il VWAP si resetta ogni giorno di sessione:
```
VWAP = sum(typical_price * volume) / sum(volume)
typical_price = (high + low + close) / 3
```

**Per Binance (crypto):** VWAP rolling 24h. Finestre: 288 barre per `5m` (288 * 5min = 24h), 24 barre per `1h`.

### Opening Range (OR)

Solo per Yahoo Finance. L'Opening Range è definito dalle prime N barre di sessione (tipicamente la prima ora). Vengono salvati `or_high` e `or_low`. Un breakout sopra `or_high` o sotto `or_low` attiva alcuni detector di pattern.

### Livelli Fibonacci

Calcolati dai più recenti swing high e swing low nel lookback. Livelli standard: 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%.

In un uptrend (swing low → swing high recenti):
```
fib_level = swing_low + (swing_high - swing_low) * retracement_pct
```

### Fair Value Gap (FVG)

Un FVG si forma quando tre candele consecutive lasciano un gap non coperto:

**FVG bullish:** `low[i] > high[i-2]` con gap >= 0.1% del prezzo — la candela centrale è impulsiva al rialzo e lascia un gap sotto di sé.

**FVG bearish:** `high[i] < low[i-2]` — gap sopra la candela centrale.

Il FVG è "retestato" quando il prezzo ritorna nella zona del gap.

### Order Block (OB)

Pattern a 3 barre che precede un movimento esplosivo:

**OB bullish:** ultima barra ribassista prima di un impulso bullish. Il range della barra ribassista diventa una zona di supporto (order block).

**OB bearish:** ultima barra rialzista prima di un impulso bearish. Il range diventa resistenza.

Soglie: la barra di impulso successiva deve avere corpo proporzionalmente grande rispetto alla media.

### CVD (Cumulative Volume Delta)

Stima del Volume Delta (buy volume - sell volume):

```
Se is_bullish: buy_vol = volume * close_position_in_range
              sell_vol = volume * (1 - close_position_in_range)
Se bearish:    sell_vol = volume * (1 - close_position_in_range)
               buy_vol  = volume * close_position_in_range

delta = buy_vol - sell_vol
CVD = sum(delta, ultimi N candles)
```

Il CVD trend (crescente/decrescente/neutro) è calcolato su una finestra mobile di 10 barre.

### Relative Strength vs SPY

Solo per Yahoo Finance, solo per simboli ≠ SPY.

```
RS_ratio[i] = pct_return_symbol[i] / pct_return_SPY[i]
              (rendimento relativo su ogni barra)

RS_rolling = media_mobile(RS_ratio, 5 barre)
RS_signal  = "outperforming" se RS_rolling > 1 else "underperforming"
```

I dati SPY vengono caricati dalla stessa tabella `candle_features` per lo stesso timeframe.

### Funding Rate (Binance)

Solo per crypto Binance. Il funding rate è il pagamento periodico tra long e short nei futures perpetui. Un funding rate positivo indica che i long pagano i short (mercato in contango, sentiment bullish). Viene usato come segnale di bias.

---

## 8. Context extraction — classificazione mercato

File: `backend/app/services/context_extraction.py`

Questo step prende le `CandleFeature` (già calcolate) e produce una classificazione del **contesto di mercato** per ogni barra, usando una finestra di barre precedenti.

### Classificazioni prodotte

```
market_regime    : trend | range | neutral | choppy | volatile
volatility_regime: high  | normal | low
candle_expansion : expansion | normal | compression
direction_bias   : bullish | bearish | neutral
```

### Logica di classificazione

La funzione `_classify_context(current, window, timeframe)` prende la barra corrente e una finestra di N barre precedenti (il `lookback` del request). Le soglie variano per timeframe tramite `thresholds_for_timeframe(tf)`.

**market_regime:**
- Si calcola quanto si muove il prezzo rispetto alla sua volatilità. Un trend ha directional movement sostenuto; un range ha oscillazione senza progressione; neutral è intermedio; choppy e volatile indicano condizioni confuse o di alta volatilità senza direzione.

**volatility_regime:**
- Basato sull'ATR relativo o sull'ampiezza media dei range della finestra. Se le barre sono ampie rispetto alla norma storica = high volatility. Se strette = low.

**candle_expansion:**
- `expansion`: la barra corrente ha range significativamente superiore alla media della finestra (indice di forza direzionale)
- `compression`: range molto inferiore alla media (indice di lateralizzazione / squeeze)
- `normal`: nella norma

**direction_bias:**
- Analizza la serie dei rendimenti `pct_return_1` nella finestra. Una predominanza di ritorni positivi → bullish; negativi → bearish; misto → neutral.

---

## 9. Pattern extraction — tutti i pattern rilevati

File: `backend/app/services/pattern_extraction.py` (~2324 righe)

È il motore di rilevamento pattern. Per ogni serie, carica le ultime N `CandleFeature` con i relativi `CandleContext` e `CandleIndicator`, poi esegue in sequenza tutti i detector via `_run_detectors`.

### Come funziona `pattern_strength` (0–1)

Ogni detector produce un valore `pattern_strength` tra 0 e 1. **Questo NON è il quality score da backtest** (quello è calcolato separatamente in `pattern_quality.py`). La strength è un punteggio euristico che misura quanto è "pulito" o "forte" il segnale nella barra specifica, usando combinazioni lineari di:
- `body_size` (quanto è grande il corpo della candela)
- `close_position_in_range` (dove chiude nella barra)
- `volume_ratio_vs_prev` (se il volume conferma)
- `direction_bias` allineato
- `volatility_regime` favorevole
- RS vs SPY (se disponibile)
- CVD trend confermante

Il valore è sempre clippato a `min(1.0, ...)`.

### Tabella completa dei pattern

| Pattern Name | Direzione | Tipo | Condizioni principali | Come si calcola la strength |
|---|---|---|---|---|
| `impulsive_bullish_candle` | bullish | Momentum | `body_ratio >= 0.62`, `close_pos >= 0.72`, no bias bearish, vol >= normal | `0.5*body + 0.3*close_pos + 0.2*vol_bonus` |
| `impulsive_bearish_candle` | bearish | Momentum | `body_ratio >= 0.62`, `close_pos <= 0.28`, no bias bullish | Speculare al bullish |
| `range_expansion_breakout_candidate` | direzionale | Breakout | `market_regime = range`, `candle_expansion = expansion`, `body >= 0.38`, close nella metà direzionale | Combinazione body + expansion |
| `compression_to_expansion_transition` | direzionale | Transizione | Barra precedente `compression`, barra corrente `expansion`, mercato trend/range, body >= 0.42 | Body + allineamento bias/close |
| `trend_continuation_pullback` | direzionale | Trend | `market_regime = trend`, bias direzionale, ultime 2 barre hanno pullback in `pct_return_1`, barra corrente riprende la direzione | Strength da ripresa + bias |
| `ema_pullback_to_support` | bullish | Mean Rev | Trend bullish, prezzo ritorna vicino EMA20 (fascia %), RSI in zona media (es. 40–60), EMA20 > EMA50 | RSI distance + EMA alignment |
| `ema_pullback_to_resistance` | bearish | Mean Rev | Speculare: downtrend, prezzo ritorna a EMA20 dall'alto | Speculare |
| `rsi_momentum_continuation` | direzionale | Momentum | Trend, RSI sopra 50 (bullish) o sotto 50 (bearish), volume ratio > 1, body minimo | RSI + volume |
| `engulfing_bullish` | bullish | Reversal | Candela bullish che "ingoia" la precedente ribassista (open < prev_close, close > prev_open), soglia corpo minimo | `body_ratio * close_pos` |
| `engulfing_bearish` | bearish | Reversal | Speculare | Speculare |
| `hammer_reversal` | bullish | Reversal | `lower_wick >= 2 * body`, `upper_wick <= 0.3 * body`, vicino swing low, RSI in zona ipervenduto | `lower_wick / (body + eps)` |
| `shooting_star_reversal` | bearish | Reversal | `upper_wick >= 2 * body`, `lower_wick <= 0.3 * body`, vicino swing high, RSI in zona ipercomprato | Speculare |
| `morning_star` | bullish | Reversal 3-barre | Prima candela bearish forte, seconda piccola (doji o inside), terza bullish forte che recupera | Media dei contributi delle 3 barre |
| `evening_star` | bearish | Reversal 3-barre | Speculare | Speculare |
| `bull_flag` | bullish | Continuazione | Impulso bullish forte (barra 1-3 prima), poi consolidamento con barre piccole, poi barra di breakout | Rapporto impulso / consolidamento |
| `bear_flag` | bearish | Continuazione | Speculare | Speculare |
| `inside_bar_breakout_bull` | bullish | Breakout | Barra precedente è "inside bar" (high < prev_high, low > prev_low), barra corrente rompe al rialzo | Ampiezza breakout |
| `support_bounce` | bullish | Mean Rev | Prezzo vicino allo swing low strutturale (entro %), RSI in zona bassa, rimbalzo con close alta nel range | Vicinanza swing + RSI |
| `resistance_rejection` | bearish | Mean Rev | Speculare con swing high | Speculare |
| `breakout_with_retest` | direzionale | Breakout | Rottura di un livello strutturale seguita da retest entro una % (definita dalla soglia del detector) | Forza del breakout + qualità retest |
| `vwap_bounce_bull` | bullish | Mean Rev | Prezzo entro % dal VWAP, close sopra VWAP, bias favorevole | Distanza dal VWAP |
| `vwap_bounce_bear` | bearish | Mean Rev | Speculare | Speculare |
| `opening_range_breakout_bull` | bullish | Breakout | Solo Yahoo. Prezzo supera `or_high` con una percentuale soglia | `(close - or_high) / or_high` |
| `opening_range_breakout_bear` | bearish | Breakout | Speculare | Speculare |
| `fibonacci_bounce` | direzionale | Mean Rev | Prezzo vicino a un livello Fibonacci chiave (38.2%, 50%, 61.8%), bias confermante | Vicinanza al livello Fib |
| `fvg_retest_bull` | bullish | Gap | FVG bullish presente, prezzo ritorna nella zona del gap | Qualità del gap + forza del retest |
| `fvg_retest_bear` | bearish | Gap | Speculare | Speculare |
| `ob_retest_bull` | bullish | Order Block | OB bullish identificato, prezzo ritorna nella zona OB | Forza OB + retest quality |
| `ob_retest_bear` | bearish | Order Block | Speculare | Speculare |
| `nr7_breakout` | direzionale | Volatilità | Range delle ultime 7 barre è il minimo del periodo (NR7 = Narrow Range 7), barra corrente ha expansion | Expansion vs NR7 ratio |
| `liquidity_sweep_bull` | bullish | SMC | Sweep del minimo precedente (bassa liquidity pool) con wick lungo, poi close nel range superiore, RSI in ipervenduto | Ampiezza sweep + recupero |
| `liquidity_sweep_bear` | bearish | SMC | Speculare | Speculare |
| `rsi_divergence_bull` | bullish | Divergenza | Due swing low nel prezzo (il secondo più basso), ma RSI forma un secondo minimo più alto. Lookback max 30 barre. Differenza RSI minima configurata. | Ampiezza divergenza |
| `rsi_divergence_bear` | bearish | Divergenza | Speculare (doppio massimo prezzo, RSI più basso) | Speculare |
| `volatility_squeeze_breakout` | direzionale | Volatilità | ATR era compresso (sotto media) per N barre, poi esplosione ATR + candela espansiva | Ratio ATR_current / ATR_compressed |
| `double_bottom` | bullish | Reversal | Due swing low entro tolleranza % (es. 1–2%), recovery minima dopo il secondo minimo | Qualità della doppia base |
| `double_top` | bearish | Reversal | Speculare | Speculare |
| `macd_divergence_bull` | bullish | Divergenza | MACD approssimato con EMA9–EMA20. Due swing in prezzo e MACD in divergenza bullish | Ampiezza divergenza MACD |
| `macd_divergence_bear` | bearish | Divergenza | Speculare | Speculare |

### Persistenza

I pattern vengono salvati nella tabella `candle_patterns` con `ON CONFLICT DO NOTHING` su `(candle_feature_id, pattern_name)`. Se il pattern per quella candela esiste già, non viene sovrascritto.

---

## 10. Pattern staleness — età e freschezza

File: `backend/app/services/pattern_staleness.py`

Un pattern è "fresco" quando è stato rilevato poche barre fa rispetto al contesto corrente. Diventa "stale" (vecchio) quando è trascorso troppo tempo.

### Calcolo dell'età in barre

```
delta_seconds = (context_timestamp - pattern_timestamp).total_seconds()
bar_minutes   = {5m: 5, 1h: 60, 1d: 1440}[timeframe]
age_bars      = floor(delta_seconds / (bar_minutes * 60))
```

Se `pattern_timestamp > context_timestamp` (caso anomalo o barra live parziale), l'età è 0 e il pattern è considerato fresco.

### Soglie per timeframe

| Timeframe | Soglia stale (barre) | Equivalente temporale |
|-----------|----------------------|-----------------------|
| `1m` | 10 | 10 minuti |
| `5m` | 8 | 40 minuti |
| `15m` | 5 | 75 minuti |
| `1h` | 8 | 8 ore |
| `1d` | 2 | 2 giorni |
| altri | 5 (default) | — |

Un pattern `1h` rilevato 9 barre fa (9 ore) è stale. Lo stesso pattern rilevato 6 ore fa è ancora fresco.

### Perché importa

Lo staleness influenza lo **score finale** tramite un decay (vedi sezione 13) e influenza anche l'**ordinamento delle query DB** in `pattern_query.py`: i pattern validati hanno penalità 0h, quelli non validati 4h, quelli bloccati 8h.

---

## 11. Pattern quality score — formula completa

File: `backend/app/services/pattern_quality.py`  
File backtest: `backend/app/services/pattern_backtest.py`

Il quality score misura quanto un pattern ha funzionato **storicamente** su tutte le sue occorrenze nel database. È calcolato una volta (o periodicamente) e cached.

### Fonte dati: backtest pattern

`run_pattern_backtest` esegue una simulazione forward su tutte le occorrenze storiche (max 5000) di ogni `(pattern_name, timeframe)`. Per ogni occorrenza:

1. Individua il candle con il pattern
2. Calcola il **forward return firmato** a +1, +3, +5, +10 barre:
   ```
   Per direzione bullish/neutral:
   signed_return = (fwd_close - entry_close) / entry_close * 100
   
   Per direzione bearish:
   signed_return = (entry_close - fwd_close) / entry_close * 100
   ```
3. `is_win = signed_return > 0`

Orizzonti: `HORIZONS = (1, 3, 5, 10)`. L'orizzonte **primario** è 5 (barre), poi 3 come fallback.

### Formula del quality score

```
wr  = win_rate orizzonte primario (0–1)
ar  = avg_return % orizzonte primario

# Normalizzazione del return medio
ar_clamped = clamp(ar, -1.0, 2.0)
ar_norm    = (ar_clamped + 1.0) / 3.0     # mappa [-1,2] → [0,1]

# Normalizzazione del campione
n_eff      = max(n5, n3)
n_norm     = min(n_eff / 80.0, 1.0)       # satura a 80 osservazioni

# Score finale
score = 45 * wr + 35 * ar_norm + 20 * n_norm   (range 0–100)
score = clamp(score, 0, 100)
```

**Pesi e motivazioni:**
- **45% al win rate**: il fattore più importante — quante volte il pattern porta a un trade positivo
- **35% al return medio**: distingue un pattern con WR=60% ma return minuscoli da uno con WR=60% e return significativi
- **20% alla dimensione del campione**: premia i pattern con molte occorrenze storiche (più affidabili statisticamente)

### Etichette

```
None       → "insufficient" (n < 30, campione troppo piccolo)
score >= 70 → "high"
score >= 40 → "medium"
else        → "low"
```

### Test statistici

Oltre allo score, vengono calcolati:
- **Wilson Confidence Interval** (95%): intervallo di confidenza sul win rate
- **Test binomiale vs 50%**: verifica se il WR è significativamente superiore al caso
- **T-test expectancy vs 0**: verifica se il return medio è significativamente > 0

I risultati vengono usati nella pagina backtest per mostrare la significatività statistica.

---

## 12. Screener scoring — punteggio strutturale

File: `backend/app/services/screener_scoring.py`

Lo screener score misura la **qualità strutturale del mercato** in quel momento, indipendentemente dal pattern. È il building block fondamentale del final score.

### Blocco strutturale (max 9 punti)

```
market_regime:
  trend   → +3  (mercato direzionale, contesto ideale per pattern di continuazione)
  range   → +2  (lateralizzazione definita, buona per mean reversion)
  neutral → +1  (indefinito, non sfavorevole)
  choppy  → +0  (caotico, penalizzato)
  volatile → +0 (alta volatilità senza direzione, penalizzato)

volatility_regime:
  high    → +3  (movimento amplificato, opportunità più grandi)
  normal  → +2  (standard)
  low     → +1  (movimenti ridotti)

candle_expansion:
  expansion   → +3  (candela espansiva = forza direzionale)
  normal      → +2
  compression → +1  (candela compressa = poco movimento, meno opportunità)
```

Somma: `structural_points = regime_pts + vol_pts + expansion_pts` (range 0–9)

### Gambe direzionali (max 3 punti ciascuna)

La stessa struttura viene valutata per **due direzioni** — long e short:

```
long_bonus:
  direction_bias = bullish → +3
  direction_bias = neutral → +2
  direction_bias = bearish → +1  (penalizzato ma non a zero)

short_bonus:
  direction_bias = bearish → +3
  direction_bias = neutral → +2
  direction_bias = bullish → +1
```

```
score_long  = structural_points + long_bonus   (range 0–12)
score_short = structural_points + short_bonus  (range 0–12)

score_final = max(score_long, score_short)
direction   = "bullish" se score_long > score_short
            = "bearish" se score_short > score_long
            = "neutral" se parità
```

### Perché questa struttura

La separazione tra blocco strutturale e gambe direzionali permette di capire:
1. Quanto è "buono" il mercato indipendentemente dalla direzione (struttura)
2. In quale direzione il mercato sta favorendo le operazioni (gamba dominante)

Un mercato in trend con alta volatilità e candle espansive in direzione bullish ottiene il massimo: 9+3=12.

### Bande di score

```
score >= 10 → "strong"
score >= 7  → "moderate"
score >= 4  → "mild"
else        → "weak"
```

`score_label = f"{band}_{direction}"` (es. `"strong_bullish"`, `"moderate_bearish"`)

---

## 13. Final opportunity score — formula completa v2

File: `backend/app/services/opportunity_final_score.py`  
Orchestrazione: `backend/app/services/opportunities.py`

Il final opportunity score è il **numero che determina l'ordine** in cui le opportunità appaiono nella UI. È un numero continuo solitamente tra 0 e 92 (range pratico).

### Step 1: score base (in `compute_final_opportunity_score`)

```
base = screener_score * 5.0
       (max 60 se screener_score = 12)

alignment_bonus:
  "aligned"     → +10.0
  "mixed"       → 0.0
  "conflicting" → -10.0

  L'allineamento è "aligned" se score_direction == latest_pattern_direction
  (entrambi bullish o entrambi bearish). "mixed" se una delle due è neutral
  o mancante. "conflicting" se si contraddicono.

quality_bonus:
  Se pattern_quality_score è disponibile (numerico 0–100):
    bonus = (pq / 100) * 14.0           (max +14)
  Altrimenti, dalla banda testuale:
    "high"    → +10.0
    "medium"  → +5.0
    "low"     → +2.0
    altri     → 0.0

strength_bonus:
  bonus = pattern_strength * 8.0        (max +8)
  (strength è il valore 0–1 del detector)

total = base + alignment_bonus + quality_bonus + strength_bonus
final = max(0.0, round(total, 2))
```

**Range teorico:** -10 (peggior caso: screener=0, conflicting, quality=0, strength=0) a 92 (screener=12, aligned, pq=100, strength=1.0 → 60+10+14+8=92).

**Range pratico:** la maggior parte dei segnali operativi cade in 40–80.

### Step 2: pattern timeframe policy (in `apply_pattern_timeframe_policy`)

Questo step applica una penalità basata sulla **qualità del pattern su quello specifico timeframe** (non sulla qualità assoluta che è già nel quality_bonus):

```
pq >= 45:      nessun malus,  gate="ok",       tf_ok=True
34 <= pq < 45: malus -7,      gate="marginal", tf_ok=False
pq < 34:       malus -16,     gate="poor",     tf_ok=False, filtered_candidate=True
pq is None:    malus -6,      gate="unknown",  tf_ok=False

adj = max(0.0, base - penalty)
```

**Perché due penalty per la qualità?** Il `quality_bonus` nello step 1 premia la qualità assoluta del pattern. Il `pattern_timeframe_policy` penalizza specificamente i pattern che **su quel timeframe** performano male. Sono logiche complementari: un pattern può essere buono in generale ma funzionare male su 5m e bene su 1h.

### Step 3: trade plan backtest adjustment (in `adjust_final_score_for_trade_plan_backtest`)

Aggiustamento soft basato sui risultati backtest del **piano di trade** generato (entry/stop/TP specifici), non del pattern generico:

```
reliability_weight(n):
  n <= 5:  w = 0             (campione insufficiente, nessun aggiustamento)
  n > 5:   w = min(1, (n-5)/30)   (cresce linearmente fino a 30+ samples → w=1)

Se expectancy <= 0:
  raw_delta -= 3.5 * w       (malus per expectancy negativa)
  
Se expectancy > 0 e n >= 28:
  raw_delta += 2.0 * w       (bonus per expectancy positiva con campione grande)

delta = clamp(raw_delta, -4, 4)
final = max(0.0, round(score + delta, 2))
```

Il range è ±4 punti massimi, ponderati per l'affidabilità del campione backtest.

### Step 4: staleness decay

Se il pattern è stale (supera la soglia di età per quel timeframe):

```
age_beyond  = max(0, age_bars - stale_threshold_bars)
decay_ratio = min(1.0, age_beyond / max(1, stale_threshold_bars))
final       = max(0.0, round(final * (1.0 - 0.20 * decay_ratio), 2))
```

Un pattern con `age_bars = 2 * stale_threshold` ha `decay_ratio = 1.0` e perde il 20% del suo score. La penalità è proporzionale a quanto è oltre la soglia.

### Label finale

```
final >= 70 → "strong"   (verde nella UI)
final >= 45 → "moderate" (ambra)
final >= 20 → "weak"     (grigio)
else        → "minimal"  (grigio scuro)
```

### Criteri candidato alert

Una riga è candidata alert se **tutte** le seguenti condizioni sono vere:
1. Allineamento = "aligned" (screener e pattern concordano sulla direzione)
2. `pattern_timeframe_quality_ok = True` (pq >= 45 su quel TF)
3. `pattern_quality_label` in {"high", "medium"}
4. `final_opportunity_score >= 45`

Se tutte vere: `alert_candidate = True`
- Se score >= 70: `alert_level = "alta_priorita"`
- Altrimenti: `alert_level = "media_priorita"`

---

## 14. Trade plan engine — costruzione entry/stop/TP

File: `backend/app/services/trade_plan_engine.py`

Per ogni opportunità operativa, viene generato un piano di trade con livelli precisi.

### Prerequisito: richiede uno score sufficiente

Il trade plan viene generato solo se:
```
final_label in {"strong", "moderate"}  OPPURE  final_score >= 28
```
Sotto questa soglia, il segnale è troppo debole per giustificare un piano operativo.

### Step 1: risoluzione della direzione

```
Se score_direction = "neutral" → direction = "none" (nessun trade)

Se score_direction = "bullish":
  Se pattern_direction = "bullish" o assente → direction = "long"
  Se pattern_direction = "bearish" → CONFLICT_PENALTY → direction = "none"
  
Se score_direction = "bearish":
  Simmetrico → direction = "short"
```

### Step 2: strategia di ingresso

Il nome del pattern determina il tipo di ingresso:

```
Se "impulsive" o "breakout" nel nome   → "breakout"
  (si entra sopra/sotto il range della barra, massimizzando il momentum)

Se "compression" nel nome              → "retest"
  OPPURE candle_expansion = "expansion" → "retest"
  (si aspetta un ritorno verso l'ingresso per un prezzo migliore)

Altrimenti                             → "close"
  (si entra al prezzo di chiusura)
```

### Step 3: prezzo di ingresso

```
"close":           entry = close

"long breakout":   entry = (high + close) / 2
"long retest":     entry = (low + close) / 2

"short breakout":  entry = (low + close) / 2
"short retest":    entry = (high + close) / 2
```

La strategia breakout entra a metà tra il massimo e la chiusura — più aggressiva, presuppone continuazione. La retest entra a metà tra il minimo e la chiusura — aspetta un pull-back leggero.

### Step 4: stop buffer (dimensione dello stop)

```
rng  = high - low
       (se rng <= 0: rng = |close| * 0.0024 come minimo)

base = max(rng * 0.32, |close| * 0.0012)
       (il 32% del range della barra, con floor di 0.12% del prezzo)

Moltiplicatore volatilità:
  volatility_regime = "high" → * 1.18  (stop più ampio per la volatilità)
  volatility_regime = "low"  → * 0.92  (stop più stretto in bassa vol)
  normal/altro               → * 1.00

Override per pattern specifici (PATTERN_SL_TP_CONFIG):
  buf *= sl_mult del pattern
```

### Step 5: calcolo stop loss

```
Long:
  stop = low - buf
  Se stop >= entry: stop = low * 0.9995  (garanzia di stop sotto entry)
  risk = entry - stop

Short:
  stop = high + buf
  Se stop <= entry: stop = high * 1.0005
  risk = stop - entry
```

### Step 6: take profit e R/R

```
Default:
  TP1 = entry + tp1_r * risk   (dove tp1_r = 1.5)
  TP2 = entry + tp2_r * risk   (dove tp2_r = 2.5, o 2.0 in mercati range)

Short: stessa logica con direzione invertita
  TP1 = entry - tp1_r * risk

R/R = (|TP1 - entry|) / risk

Override per pattern specifici: tp1_r e tp2_r da PATTERN_SL_TP_CONFIG
```

**Perché TP1=1.5R e TP2=2.5R?** Sono multipli di rischio standard nel trading discrezionale. Un R/R di 1.5 significa che il guadagno atteso è 1.5 volte il rischio accettato. Con un win rate del 40%, un sistema 1.5R è breakeven. I valori esatti sono configurabili via `PATTERN_SL_TP_CONFIG` per pattern specifici.

---

## 15. Trade plan backtest — simulazione storica

File: `backend/app/services/trade_plan_backtest.py`

Simula il comportamento del piano di trade generato su ogni occorrenza storica del pattern nel database.

### Algoritmo di simulazione

Per ogni occorrenza storica del pattern:

1. **Carica il piano:** ricostruisce il trade plan con `build_trade_plan_v1` per quella specifica barra storica (usando i prezzi di quella barra, non quelli correnti).

2. **Scan ingresso (max 20 barre):**
   ```
   Per strategia "close": inizia dalla barra successiva al pattern
   Per breakout/retest: può iniziare dalla stessa barra del pattern
   
   Cerca la prima barra dove: low <= entry_price <= high
   Se non trovata entro 20 barre: trade saltato (no entry)
   ```

3. **Simulazione post-ingresso (max 48 barre):**
   - Ogni barra: controlla se stop o TP vengono toccati
   - Regola di priorità nella stessa candela: **stop prima di TP2** (più conservativo)
   - Se sia stop che TP1 toccati nella stessa barra: stop vince (regola conservativa)

4. **Calcolo PnL in R:**
   ```
   cost_r = cost_rate * (entry_price / risk)
   
   Se stop → PnL = -1.0 - cost_r
   Se TP2  → PnL = +tp2_r - cost_r
   Se TP1  → PnL = +tp1_r - cost_r
   Se timeout → PnL = ((exit_price - entry) / risk) - cost_r
   ```

5. **Aggregati per `(pattern_name, timeframe, entry_strategy, stop_profile, tp_profile)`:**
   - Win rate, PnL medio in R (expectancy), sample size
   - Questi aggregati alimentano il `trade_plan_live_adjustment`

**Costi standard:** 0.10% fee round-trip + 0.05% slippage = **0.15% totale** (costante `BACKTEST_TOTAL_COST_RATE_DEFAULT`).

**Nota look-ahead bias:** il quality score del pattern usato per decidere se generare il trade plan è calcolato sull'intero storico. Per pattern molto vecchi, c'è un bias perché i dati futuri a quel punto erano già disponibili. Per analisi OOS (Out-Of-Sample) rigorose, usare le funzionalità dedicate nella pagina backtest.

---

## 16. Trade plan variant backtest

File: `backend/app/services/trade_plan_variant_backtest.py`

Estende il backtest standard testando **tutte le combinazioni** di parametri del piano di trade per trovare la variante ottimale per ogni `(pattern_name, timeframe)`.

### Dimensioni delle varianti

```
entry_strategy: ["breakout", "retest", "close"]      → 3 opzioni
stop_profile:   ["tighter", "structural", "wider"]    → 3 opzioni
                 moltiplicatori: 0.72, 1.00, 1.32 rispetto allo stop base
tp_profile:     da TP_PROFILE_CONFIGS, es:
                  "tp_1.5_2.5" → TP1=1.5R, TP2=2.5R
                  "tp_2.0_3.0" → TP1=2.0R, TP2=3.0R
                  ... (N configurazioni)
```

**Combinazioni totali:** 3 × 3 × N (dove N è il numero di profili TP configurati).

### Selezione della variante migliore

Per ogni `(pattern, timeframe)`:
1. Calcola expectancy media per ogni combinazione
2. Richiede campione minimo `TRADE_PLAN_VARIANT_MIN_SAMPLE = 20`
3. Seleziona la combinazione con la massima expectancy positiva
4. La variante selezionata viene usata in live per quel pattern/TF (se ha sample sufficiente)

Questa variante live è cachata in `variant_best_cache` e viene applicata quando si costruisce il trade plan per un'opportunità corrente.

---

## 17. Trade plan live adjustment

File: `backend/app/services/trade_plan_live_adjustment.py`

Applica un aggiustamento soft allo score finale basato sui risultati backtest del piano di trade aggregato.

### Funzione di affidabilità del campione

```python
def _reliability_weight(n: int) -> float:
    if n <= 5:
        return 0.0                      # campione troppo piccolo, ignora
    return min(1.0, (n - 5) / 30.0)   # cresce linearmente da 0 a 1
    # raggiunge w=1 con n=35 samples
```

### Aggiustamento score

```
Se no bucket (nessun backtest disponibile):
  delta = 0, label = "no_bucket"

Se expectancy <= 0:
  raw_delta -= 3.5 * reliability_weight(n)
  (malus per expectancy negativa, pesato per affidabilità)

Se expectancy > 0 e n >= 28:
  raw_delta += 2.0 * reliability_weight(n)
  (bonus solo con sample grande e expectancy positiva)

delta = clamp(raw_delta, -4.0, +4.0)
final_adjusted = max(0, round(original_score + delta, 2))
```

### Etichetta confidenza operativa

```
n < 8 o expectancy None → "unknown"
expectancy <= 0          → "low"
expectancy > 0 e n >= 28 → "high"
else                     → "medium"
```

Questa etichetta appare nella UI quando si espande una card (campo `operational_confidence`).

---

## 18. Opportunity validator — decisione operativa

File: `backend/app/services/opportunity_validator.py`

Questo modulo prende tutte le informazioni calcolate e produce la **decisione operativa finale**: `execute`, `monitor`, o `discard`.

### Filtri in ordine (il primo filtro che scatta vince)

```
1. ORE ESCLUSE (solo Yahoo Finance):
   Se ora UTC corrente è in EXCLUDED_HOURS_UTC_YAHOO
   → DISCARD: "fuori orario mercato"

2. TIMEFRAME NON VALIDATO:
   Se timeframe non in VALIDATED_TIMEFRAMES (lista configurata)
   → DISCARD

3. SIMBOLO NON IN UNIVERSO:
   Yahoo: se symbol non in VALIDATED_SYMBOLS_YAHOO
   Binance: se symbol non in VALIDATED_SYMBOLS_BINANCE
   → DISCARD

4. PATTERN MANCANTE:
   Se latest_pattern_name = None
   → DISCARD

5. PATTERN BLOCCATO:
   Se pattern in PATTERNS_BLOCKED (WR < 40% o altri criteri oggettivi)
   → DISCARD: "pattern con performance insufficiente"

6. PATTERN NON IN LISTA PER QUEL TF:
   1h: controlla VALIDATED_PATTERNS_1H
   5m: controlla VALIDATED_PATTERNS_5M
   → DISCARD se non presente

7. DIREZIONE NON DEFINITA:
   Se pattern_direction non è "bullish" o "bearish"
   → DISCARD

8. FILTRO REGIME:
   Se regime_filter abilitato e provider in {yahoo, binance}:
     Verifica che la direzione del pattern sia coerente con le
     direzioni permesse dal regime corrente (da regime_filter_service)
     Se non coerente: regime_ok = False

9. PATTERN BEAR-REGIME-ONLY IN REGIME NON BEAR:
   Se pattern in PATTERNS_BEAR_REGIME_ONLY e regime non bearish
   → MONITOR: "pattern valido solo in regime bearish"
   (questi pattern hanno EV documentata solo in mercati ribassisti)

10. EXECUTE (condizioni tutte soddisfatte):
    - pattern in lista validata
    - regime_ok = True
    - confluenza >= SIGNAL_MIN_CONFLUENCE (2) pattern per quel symbol/TF
    - pattern_strength >= SIGNAL_MIN_STRENGTH (0.70)
    → EXECUTE con rationale completo

11. MONITOR PER REGIME:
    Se pattern ok ma regime non favorevole
    → MONITOR

12. FALLBACK:
    → MONITOR
```

### Rationale testuale

Ogni decisione produce un array `decision_rationale: list[str]` con spiegazioni leggibili. Per un EXECUTE tipico:
```json
[
  "Pattern rsi_momentum_continuation validato su 1h",
  "Win Rate storico: 64% (n=87)",
  "EV media: +1.8R",
  "Confluenza: 2 pattern attivi",
  "Regime: trend bullish - allineato",
  "Strength: 0.82"
]
```

Questo array appare nella UI quando si espande la card.

---

## 19. Sistema alert — Telegram e Discord

L'applicazione ha due livelli indipendenti di notifica.

### Livello 1: `alert_service` (alert legacy per pattern)

File: `backend/app/services/alert_service.py`

Inviato da `maybe_send_pattern_alerts_after_pipeline` dopo ogni ciclo.

**Deduplicazione:** chiave univoca `(symbol, timeframe, provider, pattern_name, direction, bar_hour_utc)`.  
Questo significa che per lo stesso pattern sulla stessa barra (stessa ora), l'alert viene inviato **una sola volta**, anche se il pipeline gira più volte in quella stessa ora.

**Filtri di invio:**
1. Canali configurati (token/webhook non vuoti)
2. Per Yahoo: ora UTC non in `EXCLUDED_HOURS_UTC_YAHOO`
3. `strength >= settings.alert_min_strength`
4. Se `quality_score` disponibile: `quality_score >= settings.alert_min_quality_score`
5. Se `alert_regime_filter` abilitato: direzione pattern allineata con regime (o regime neutral)

**Formato messaggio:** Markdown con simbolo, direzione, pattern, strength, qualità, link deep al frontend.

### Livello 2: `alert_notifications` (notifiche post-pipeline)

File: `backend/app/services/alert_notifications.py`

Inviato da `maybe_notify_after_pipeline_refresh`. Più selettivo del livello 1.

**Deduplicazione:** chiave `(exchange, symbol, timeframe, context_timestamp)`.  
Finché il contesto di mercato per quella serie non cambia (`context_timestamp` uguale), non viene reinviata la notifica.

**Candidati:** solo opportunità con `alert_level = "alta_priorita"` (score >= 70 + tutte le condizioni di candidato). Opzionalmente anche `"media_priorita"` se `ALERT_INCLUDE_MEDIA_PRIORITA = true`.

**Modalità:**
- **Mirata** (se il body del refresh specifica symbol+TF): notifica solo per quella serie
- **Globale** (refresh generico): batch fino a 1000 righe, notifica tutte le alta_priorita

**Successo:** richiede che entrambi i canali (Telegram E Discord) abbiano risposto OK. Se uno fallisce, viene loggato un warning ma non viene marcata come inviata.

---

## 20. Auto-execute TWS (Interactive Brokers)

File: `backend/app/services/auto_execute_service.py`

Permette l'esecuzione automatica di ordini bracket su Interactive Brokers via TWS socket (`ib_insync`).

### Prerequisiti per l'attivazione

```
settings.tws_enabled = True
settings.ibkr_auto_execute = True
pipeline refresh con provider = "yahoo_finance"
```

Se una delle condizioni non è soddisfatta, il servizio si disattiva silenziosamente.

### Flusso di esecuzione

```
1. Carica lista opportunità con decision="execute" per il provider/symbol/TF del refresh
2. Per ogni riga con operational_decision="execute" e trade_plan valido:

   a. Verifica short: se direction="short" e non IBKR_MARGIN_ACCOUNT → skip
   b. Verifica max posizioni: se posizioni aperte >= IBKR_MAX_SIMULTANEOUS_POSITIONS → stop
   c. Verifica no posizione esistente su quel symbol → skip se già aperto
   
3. Calcola position size:
   net_liquidation = NetLiquidation TWS (o fallback IBKR_MAX_CAPITAL)
   risk_amount = net_liquidation * (IBKR_MAX_RISK_PER_TRADE_PCT / 100)
   stop_distance = |entry_price - stop_loss|
   qty = floor(risk_amount / stop_distance)
   Se qty < 1 → skip

4. Esegue execute_signal(symbol, direction, entry, stop, tp1, qty)
   → place_bracket_order su TWS:
     - Ordine principale: LMT a entry_price
     - Take Profit: LMT GTC a tp1
     - Stop Loss: STP GTC a stop_loss

5. Salva ExecutedSignal con order IDs e status TWS
6. Break dopo il primo ordine eseguito per ciclo (non esegue più trade in una singola run)
```

### Sizing del rischio

La dimensione della posizione è calcolata in modo che se il prezzo raggiunge lo stop, la perdita sia esattamente `IBKR_MAX_RISK_PER_TRADE_PCT`% del capitale:

```
risk_amount  = capital * risk_pct / 100
stop_distance = |entry - stop|
qty          = floor(risk_amount / stop_distance)
max_loss     = qty * stop_distance ≈ risk_amount   (+ commissioni)
```

---

## 21. Machine Learning scorer (opzionale)

File: `backend/app/services/ml_signal_scorer.py`

Un filtro aggiuntivo basato su LightGBM che può ridurre i falsi positivi nella lista `execute`.

### Quando è attivo

```
settings.ml_model_path è configurato e il file .pkl esiste
```

Se il modello non è trovato, il scorer si disabilita automaticamente senza errori.

### Feature del modello

```python
features = {
    "screener_score": float,
    "pattern_strength": float,
    "pattern_quality_score": float,
    "market_regime_encoded": int,    # trend=3, range=2, neutral=1, altri=0
    "volatility_regime_encoded": int,
    "candle_expansion_encoded": int,
    "timeframe_encoded": int,        # 5m=0, 1h=1, 1d=2
    "symbol_group_encoded": int,     # raggruppamento settore/tipo
    "body_size": float,
    "close_position_in_range": float,
    "volume_ratio_vs_prev": float,
}
```

### Utilizzo

Il modello produce un score [0,1]. Se lo score è sotto `settings.ml_min_score` (o `ml_min_score_short` per short), la decisione `execute` viene degradata a `monitor`:

```python
if ml_score < threshold and decision == "execute":
    decision = "monitor"
    rationale.append(f"ML score {ml_score:.2f} sotto soglia {threshold}")
```

Questo avviene **dopo** il validator, come strato aggiuntivo di filtraggio.

---

## 22. Monte Carlo

File: `backend/app/services/monte_carlo_service.py`

Analisi statistica della robustezza di una strategia tramite bootstrap Monte Carlo.

### Input

- `pnl_r_list`: lista dei PnL in multipli di R da storico backtest (es. `[-1.0, +1.5, -1.0, +2.5, +1.5, ...]`)
- `n_simulations`: numero di simulazioni (default 1000)
- `n_trades`: trade per simulazione (default = len(pnl_r_list))
- `initial_capital`: capitale iniziale (default 10000)
- `risk_per_trade_pct`: rischio percentuale per trade (default 1.0%)

### Algoritmo

```python
for _ in range(n_simulations):
    sample = random.choices(pnl_r_list, k=n_trades)  # bootstrap con replacement
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    
    for pnl_r in sample:
        equity *= (1 + pnl_r * risk_fraction)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        max_dd = max(max_dd, dd)
    
    drawdowns.append(max_dd)
    returns.append((equity - initial_capital) / initial_capital * 100)
```

### Output

```
dd_median_pct      Drawdown massimo mediano
dd_p95_pct         Drawdown massimo nel 95° percentile (worst 5%)
dd_p99_pct         Drawdown massimo nel 99° percentile (tail risk)
dd_max_ever_pct    Drawdown massimo assoluto registrato
ret_median_pct     Rendimento finale mediano
ret_p5_pct         Rendimento finale nel 5° percentile (worst case)
ret_p95_pct        Rendimento finale nel 95° percentile (best case)
pct_simulations_positive  % simulazioni con rendimento > 0
pct_simulations_ruin      % simulazioni con drawdown > 50% (rovina)
```

**Nota:** il bootstrap i.i.d. non preserva le dipendenze temporali tra trade. Per sequenze molto correlate, sovrastima la diversificazione. Per un'analisi più rigida, usare walk-forward.

---

## 23. Cache sistema

File: `backend/app/core/cache.py`

La cache evita di ricalcolare operazioni costose (backtest su 5000 righe, quality score) ad ogni richiesta API.

### Architettura TTLCache

```python
class TTLCache:
    _store: dict[str, tuple[value, expires_at_monotonic]]
    _lock: asyncio.Lock (per chiave)
    
    async def get_or_compute(key, compute_fn, ttl=None):
        if key in _store and not expired:
            return cached_value
        value = await compute_fn()
        _store[key] = (value, monotonic() + ttl)
        return value
    
    async def invalidate_keys_containing(needle: str):
        # rimuove tutte le chiavi che contengono la stringa
    
    async def invalidate_all():
        # svuota completamente
```

**TTL default:** `settings.opportunity_lookup_cache_ttl_seconds`

### Tre istanze globali

| Istanza | Cosa casha | Chiave |
|---------|-----------|--------|
| `pattern_quality_cache` | Quality score per `(pattern_name, timeframe)` | `pattern_quality\|symbol\|tf\|...` |
| `trade_plan_backtest_cache` | Aggregati backtest trade plan | `tpb\|symbol\|tf\|entry_strategy\|...` |
| `variant_best_cache` | Miglior variante per `(pattern, tf)` | `variant\|pattern\|tf\|...` |

### Generazione chiave

```python
def opportunity_lookup_key(kind, symbol, exchange, provider, asset_type, timeframe, ...):
    parts = [kind, symbol or "*", exchange or "*", provider or "*",
             asset_type or "*", timeframe or "*", ...]
    return "|".join(parts)
```

### Invalidazione post-pipeline

Dopo ogni ciclo pipeline:
```python
invalidate_opportunity_lookups_after_pipeline(provider, exchange, timeframe):
    if timeframe == "":
        # invalidazione totale
        await all_caches.invalidate_all()
    else:
        # invalidazione selettiva per chiavi che contengono provider|exchange|timeframe
        needle = f"|{provider}|{exchange}|{timeframe}|"
        await all_caches.invalidate_keys_containing(needle)
```

### Pre-warm post-pipeline

Dopo l'invalidazione, la cache viene ri-popolata in anticipo per le 3 combinazioni più comuni:

```python
combos = [
    {"provider": "yahoo_finance", "timeframe": "1h"},
    {"provider": "binance",       "timeframe": "1h"},
    {"provider": None,            "timeframe": None},  # query "tutti"
]
# tutte e tre in parallelo
await asyncio.gather(*[_prewarm_combo(c) for c in combos])
```

Questo garantisce che la prima richiesta della UI dopo un ciclo pipeline trovi già i dati precalcolati.

---

## 24. API endpoints — riferimento completo

### Router `/api/v1/screener`

| Metodo | Path | Parametri query | Response |
|--------|------|-----------------|----------|
| GET | `/screener/latest` | `symbol`, `exchange`, `provider`, `asset_type`, `timeframe` | `LatestScreenerResponse` con snapshot per serie |
| GET | `/screener/ranked` | stessi + `limit` (1–1000, default 100) | `RankedScreenerResponse` — ordinato per screener score |
| GET | `/screener/opportunities` | `symbol`, `exchange`, `provider`, `asset_type`, `timeframe`, `limit` (1–1000), `decision` (execute/monitor/discard + alias IT), `min_confluence` | `OpportunitiesResponse` — lista completa |
| GET | `/opportunities` | stessi di `/screener/opportunities` | Alias per retrocompatibilità |
| GET | `/screener/executed-signals` | `symbol` (opzionale), `limit` 1–500 (default 50) | `ExecutedSignalsResponse` |

### Router `/api/v1/market-data`

| Metodo | Path | Note |
|--------|------|------|
| GET | `/candles` | OHLCV raw, limit 1–10000 |
| GET | `/features` | Feature candele, limit 1–1000 |
| GET | `/indicators` | Indicatori tecnici, limit 1–5000 |
| GET | `/context` | Classificazione contesto, limit 1–1000 |
| GET | `/patterns` | Pattern rilevati (+ filtro `pattern_name`), limit 1–5000 |
| POST | `/ingest` | Avvia ingest OHLCV manuale (`MarketDataIngestRequest`) |
| POST | `/features/extract` | Estrazione feature on-demand |
| POST | `/indicators/extract` | Estrazione indicatori on-demand |
| POST | `/context/extract` | Estrazione contesto on-demand |
| POST | `/patterns/extract` | Estrazione pattern on-demand |

### Router `/api/v1/ibkr`

| Metodo | Path | Note |
|--------|------|------|
| GET | `/ibkr/status` | Stato generale IBKR (gateway, capital, config) |
| GET | `/ibkr/tws/status` | Stato connessione TWS |
| GET | `/ibkr/tws/quote/{symbol}` | Quote live da TWS |
| GET | `/ibkr/tws/portfolio` | Posizioni aperte |
| POST | `/ibkr/tws/test-order` | Test ordine what-if su TWS |
| POST | `/ibkr/tws/test-bracket` | Test bracket order reale |
| POST | `/ibkr/tws/cancel-all-orders` | Cancella tutti gli ordini aperti del backend |
| GET | `/ibkr/conid/{symbol}` | Debug lookup contract ID |
| GET | `/ibkr/positions` | Posizioni via Client Portal REST |
| GET | `/ibkr/orders` | Ordini aperti via Client Portal REST |
| POST | `/ibkr/test-order` | Test esecuzione ordine (usa prezzi sintetici) |

### Router `/api/v1/health`

| Metodo | Path | Note |
|--------|------|------|
| GET | `/health` | Liveness + check DB |
| GET | `/settings` | Config pubblica + statistiche cache |
| POST | `/cache/invalidate` | Svuota tutte le cache (utile dopo cambio dati manuali) |

### Router `/api/v1/pipeline`

| Metodo | Path | Note |
|--------|------|------|
| POST | `/pipeline/refresh` | Avvia ciclo pipeline completo manualmente |

---

## 25. Frontend — pagina opportunità

File: `frontend/app/opportunities/page.tsx`

### Struttura della pagina

La pagina principale `http://localhost:3000/opportunities` mostra tutte le opportunità rilevate.

### Ciclo di vita dei dati

```
Mount → load():
  Promise.all([
    fetchOpportunities({ limit: 500 }),
    fetchIbkrStatus(),
    fetchExecutedSignals(50)
  ])
  → aggiorna stato React
  → ogni 60 secondi: auto-refresh automatico
  → countdown visivo "Prossimo refresh tra Xs"
```

### Filtri client-side

L'utente può filtrare per:
- **Decisione:** Tutti / Solo ESEGUI / Solo MONITORA
- **Timeframe:** Tutti / 5m / 1h / 1d
- **Direzione:** Tutti / BULLISH / BEARISH

Questi filtri sono applicati **lato client** sul dataset già caricato (500 righe) — non richiedono una nuova chiamata API.

### Ordinamento e raggruppamento

Il dataset viene:
1. Diviso in 3 gruppi: `execute`, `monitor`, `discard`
2. All'interno di ogni gruppo, ordinato per `final_opportunity_score` decrescente (default)
3. Mostrato in sezioni separate nella UI

```
SEZIONE "ESEGUI"  → verde, animate-glow
SEZIONE "MONITORA" → ambra
SEZIONE "SCARTI"   → grigio, compatti (DiscardedCard)
```

### Componente SignalCard

Per ogni opportunità nella lista execute/monitor viene renderizzato un `SignalCard` con:

**Header (sempre visibile):**
- Badge decisione: "✅ ESEGUI" o "👁 MONITOR"
- Badge direzione + timeframe: es. "BEARISH ↓ · 5m"
- **Score pill:** es. "72 · forte" colorato per label (verde/ambra/grigio)
- Prezzo live corrente

**Body (sempre visibile):**
- Simbolo e nome esteso
- Grid Entry / Stop / TP1 / R:R
- Rischio € e Guadagno atteso € (dal position sizing)
- Barra pattern strength (nome pattern + %)
- Prima riga del decision_rationale (italic, compresso)

**Footer (sempre visibile):**
- Bottone "Copia parametri" (copia testo formattato per broker)
- Link "Pagina serie →"

**Pannello espanso (al click):**
- Istruzioni broker (IBKR/XTB/Altro) con passi operativi
- Grid: Pattern / Qualità / Regime SPY / Prezzo vs entry
- Lista completa `decision_rationale`

### Pagina serie (dettaglio)

Path: `/opportunities/[symbol]/[timeframe]`

Mostra per un singolo simbolo/TF:
- Snapshot opportunità corrente
- Candele recenti con grafico (SeriesCandleChart)
- Contesto, pattern, indicatori (ultimi 50)
- Trade plan con position sizing interattivo (TradePlanPositionSizingCard)
- Score breakdown, backtest TPB, dati ML

---

## 26. Position sizing (frontend)

File: `frontend/lib/positionSizing.ts`

### Formula base

```typescript
risk_amount   = accountCapital * (riskPercent / 100)
stop_distance = Math.abs(entry_price - stop_loss)
qty           = Math.floor(risk_amount / stop_distance)

// Verifica leva (se margine account)
position_value = qty * entry_price
margin_required = position_value / leverage
if (margin_required / accountCapital > maxMarginPercent) {
    qty = Math.floor(accountCapital * maxMarginPercent * leverage / entry_price)
}
```

### Calcoli PnL con costi

```
cost_rate = 0.001  (0.1% commissioni + slippage stimato)

loss_at_stop   = qty * stop_distance * (1 + cost_rate)
profit_tp1     = qty * |tp1 - entry| * (1 - cost_rate)
rr_net         = profit_tp1 / loss_at_stop

profit_tp2     = qty * |tp2 - entry| * (1 - cost_rate)
```

### Raccomandazione rischio automatica

```typescript
function computeRecommendedRiskPct(finalScore, variantStatus, stopDistance, rr):
  base_risk = 0.5%
  
  // Aggiustamenti per score
  if finalScore >= 70:  base_risk += 0.3%
  if finalScore >= 55:  base_risk += 0.1%
  
  // Aggiustamento per variante backtest
  if variantStatus == "promoted":  base_risk += 0.2%
  
  // Penalità R/R basso
  if rr < 1.2:  base_risk -= 0.2%
  
  return clamp(base_risk, 0.25%, 2.0%)
```

### Persistenza preferenze

Le preferenze sono salvate in `localStorage` sotto la chiave `positionSizingUserInputV2`:

```json
{
  "accountCapital": 10000,
  "riskMode": "percent",
  "riskPercent": 0.5,
  "riskFixed": 50,
  "leverage": 1,
  "maxMarginPercent": 0.8
}
```

Il broker preferito è in `trader_prefs_broker_v1` (values: `"ibkr"`, `"xtb"`, `"other"`).

---

## 27. Configurazione completa (.env)

Tutte le variabili d'ambiente che l'applicazione riconosce:

### Applicazione

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `ENVIRONMENT` | `development` | Ambiente: `development`, `production` |
| `BACKEND_HOST` | `0.0.0.0` | Host uvicorn |
| `BACKEND_PORT` | `8000` | Porta backend |
| `SQLALCHEMY_ECHO` | `False` | Log SQL queries |
| `FRONTEND_PORT` | `3000` | Porta frontend |

### Database

| Variabile | Significato |
|-----------|-------------|
| `DATABASE_URL` | URL completo (sovrascrive i singoli) |
| `POSTGRES_USER` | Username PostgreSQL |
| `POSTGRES_PASSWORD` | Password |
| `POSTGRES_DB` | Nome database |
| `POSTGRES_HOST` | Host (default: `localhost`) |
| `POSTGRES_PORT` | Porta (default: `5432`) |

### Pipeline

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `PIPELINE_SCHEDULER_ENABLED` | `True` | Abilita scheduler automatico |
| `PIPELINE_REFRESH_INTERVAL_SECONDS` | `300` | Intervallo tra cicli (300s = 5 minuti) |
| `PIPELINE_SCHEDULER_SOURCE` | `validated_1h` | Modalità risoluzione job |
| `PIPELINE_UNIVERSE_TAGS` | `""` | Tag filtro per registry_full |
| `PIPELINE_SYMBOLS` | lista default | Simboli per modalità legacy |
| `PIPELINE_TIMEFRAMES` | lista default | Timeframe per modalità legacy |
| `PIPELINE_INGEST_LIMIT` | `200` | Barre da scaricare per ciclo |
| `PIPELINE_INGEST_LIMIT_5M` | `500` | Barre per timeframe 5m (più dati) |
| `PIPELINE_EXTRACT_LIMIT` | `100` | Barre da rielaborare per ciclo |
| `PIPELINE_LOOKBACK` | `50` | Finestra per context extraction |

### CORS

| Variabile | Significato |
|-----------|-------------|
| `CORS_ORIGINS` | Lista URL permessi, separati da virgola (es. `http://localhost:3000`) |

### Opportunità

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `OPPORTUNITY_LOOKUP_CACHE_TTL_SECONDS` | `120` | TTL cache opportunità |
| `OPPORTUNITY_PRICE_STALENESS_PCT` | `0.5` | Soglia % distanza prezzo vs entry |

### Alert

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `ALERT_LEGACY_ENABLED` | `False` | Alert livello 1 (alert_service) |
| `ALERT_NOTIFICATIONS_ENABLED` | `False` | Alert livello 2 (alert_notifications) |
| `ALERT_INCLUDE_MEDIA_PRIORITA` | `False` | Includi media priorità nelle notifiche |
| `ALERT_FRONTEND_BASE_URL` | `""` | URL frontend per deep link negli alert |
| `DISCORD_WEBHOOK_URL` | `""` | Webhook Discord |
| `TELEGRAM_BOT_TOKEN` | `""` | Token bot Telegram |
| `TELEGRAM_CHAT_ID` | `""` | Chat ID Telegram |
| `ALERT_MIN_QUALITY_SCORE` | `40` | Score minimo per alert |
| `ALERT_MIN_STRENGTH` | `0.65` | Strength minima per alert |
| `ALERT_REGIME_FILTER` | `True` | Filtra alert per regime |

### Interactive Brokers

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `IBKR_ENABLED` | `False` | Abilita integrazione IBKR |
| `IBKR_PAPER_TRADING` | `True` | Usa account paper (simulato) |
| `IBKR_GATEWAY_URL` | `https://localhost:5000` | URL Client Portal Gateway |
| `IBKR_ACCOUNT_ID` | `""` | ID account IBKR |
| `IBKR_AUTO_EXECUTE` | `False` | Esecuzione automatica ordini |
| `IBKR_MARGIN_ACCOUNT` | `False` | Permetti short (richiede margine) |
| `IBKR_MAX_RISK_PER_TRADE_PCT` | `1.0` | Rischio max per trade (% capitale) |
| `IBKR_MAX_CAPITAL` | `10000` | Capitale max (fallback se no TWS) |
| `IBKR_MAX_SIMULTANEOUS_POSITIONS` | `5` | Posizioni aperte max |
| `IBKR_MAX_SPREAD_PCT` | `0.5` | Spread bid/ask max ammesso |

### TWS (Interactive Brokers Workstation)

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `TWS_ENABLED` | `False` | Abilita connessione TWS socket |
| `TWS_HOST` | `127.0.0.1` | Host TWS |
| `TWS_PORT` | `7497` | Porta TWS (7497=paper, 7496=live) |
| `TWS_CLIENT_ID` | `1` | Client ID connessione |

### Alpaca

| Variabile | Significato |
|-----------|-------------|
| `ALPACA_ENABLED` | Abilita ingest Alpaca |
| `ALPACA_API_KEY` | API Key |
| `ALPACA_API_SECRET` | Secret |
| `ALPACA_BASE_URL` | URL API (paper o live) |
| `ALPACA_FEED` | Feed dati (iex, sip) |

### Machine Learning

| Variabile | Default | Significato |
|-----------|---------|-------------|
| `ML_MODEL_PATH` | `""` | Path al file .pkl del modello |
| `ML_MIN_SCORE` | `0.5` | Score minimo ML per long |
| `ML_MIN_SCORE_SHORT` | `0.4` | Score minimo ML per short |

---

## 28. Scheduler — comportamento temporale

### Ciclo principale

```
Ogni PIPELINE_REFRESH_INTERVAL_SECONDS (default 300s = 5 minuti):

1. Risolve la lista job (da modalità configurata)
2. Esegue fino a 4 job in parallelo (asyncio.Semaphore(4))
3. Ogni job ha timeout 120s
4. Log risultati (ok/failed/timeout)
5. Pre-warm cache opportunità (parallelo su 3 combinazioni)
   - Invalida cache esistente
   - Ricalcola e ricarica le 3 combo principali
```

### Job tipici (modalità `validated_1h`)

```python
[
  {"provider": "yahoo_finance", "timeframe": "1h",  "symbols": VALIDATED_SYMBOLS_YAHOO},
  {"provider": "binance",       "timeframe": "1h",  "symbols": VALIDATED_SYMBOLS_BINANCE},
  {"provider": "yahoo_finance", "timeframe": "1d",  "symbols": [subset per regime SPY]},
  # Alpaca 5m se ALPACA_ENABLED
]
```

### Job TWS live candles (se TWS abilitato)

```
Ogni 2 minuti, solo in orario di mercato (lun-ven, 13:30–20:00 UTC):
→ update_live_candles() per i simboli Yahoo 1h configurati
→ aggiorna la candela 1h corrente con dati parziali live
```

### Job cleanup alert

```
Ogni 24 ore:
→ cleanup_old_alerts(days_to_keep=7)
→ DELETE FROM alerts_sent WHERE sent_at < now() - interval '7 days'
```

### Avvio e shutdown

All'avvio dell'applicazione FastAPI (`lifespan`):
1. Crea tabelle DB (se non esistono)
2. Verifica connessione DB
3. Avvia scheduler
4. Pre-warm cache asincrono (task in background, non bloccante)

Allo shutdown:
1. `shutdown_pipeline_scheduler()` — aspetta completamento job in corso
2. `engine.dispose()` — chiude connection pool DB

---

## Appendice: flusso completo di una singola opportunità

Per capire come una riga della UI viene generata, ecco il percorso completo:

```
1. APScheduler avvia il ciclo

2. YahooFinanceIngestionService scarica ultime 200 candele di META/1h
   → INSERT OR IGNORE in candles

3. extract_features calcola body, wick, return per ogni barra
   → UPSERT in candle_features

4. extract_indicators calcola EMA9/20/50, RSI, ATR, swing, VWAP, ecc.
   → UPSERT in candle_indicators

5. extract_context classifica mercato per ogni barra (finestra 50 barre)
   META/1h barra corrente → market_regime="trend", volatility="normal",
   candle_expansion="expansion", direction_bias="bullish"
   → UPSERT in candle_contexts

6. extract_patterns esegue i 32+ detector sulla barra corrente
   Detector rsi_momentum_continuation:
   - regime=trend ✓
   - direction_bias=bullish ✓
   - RSI=62 (> 50) ✓
   - volume_ratio=1.4 ✓
   - body_size=0.68 (> min) ✓
   → CandlePattern(pattern_name="rsi_momentum_continuation",
                   strength=0.81, direction="bullish")
   → UPSERT in candle_patterns

7. Cache invalidata per yahoo_finance|NASDAQ|1h

8. GET /opportunities chiamato dal frontend (auto-refresh 60s)

9. list_opportunities():
   a. Carica ultimi contesti META/1h → context
   b. Carica ultimo pattern META/1h → rsi_momentum_continuation
   c. score_snapshot(context) → screener_score=9, direction="bullish", label="strong_bullish"
   d. pattern_quality_cache lookup → pq=67 (backtest 87 trade, WR=64%, EV=+1.8R)
   e. compute_final_opportunity_score:
      base        = 9 * 5.0   = 45.0
      alignment   = aligned   = +10.0
      quality     = 67/100*14 = +9.38
      strength    = 0.81 * 8  = +6.48
      total       = 70.86
   f. apply_pattern_timeframe_policy:
      pq=67 >= 45 → nessun malus
      score = 70.86
   g. adjust_for_trade_plan_backtest:
      expectancy=+1.8R, n=87, w=min(1,(87-5)/30)=1.0
      delta = +2.0 * 1.0 = +2.0 (capped a +4)
      score = 72.86
   h. pattern_stale:
      age_bars=0 (pattern sulla barra corrente), non stale
      score invariato = 72.86
   i. final_opportunity_label_from_score(72.86) = "strong"
   j. compute_alert_candidate_fields:
      aligned=True, tf_ok=True, quality="high", score=72.86 >= 45
      → alert_candidate=True, alert_level="alta_priorita"
   k. validate_opportunity:
      ore ok (mercato aperto), TF in lista, META in universo,
      pattern non bloccato, pattern in VALIDATED_PATTERNS_1H,
      confluenza=2 (rsi_momentum + ema_pullback_to_support),
      strength=0.81 >= 0.70, regime ok
      → operational_decision="execute"
      → rationale=["Pattern validato su 1h", "WR: 64% (n=87)", "EV: +1.8R", ...]
   l. build_live_trade_plan (variante backtest ottimale: entry=breakout, stop=structural, tp=1.5_2.5)
      entry = (high + close) / 2 = $574.24
      stop  = low - buffer       = $573.37
      TP1   = entry + 1.5 * risk = $578.45 (R/R = 1.50)
   m. Prezzo corrente = $574.24 (dal close barra corrente)
   n. Distanza entry: 0% (coincide, non stale)

10. Risposta JSON → frontend

11. SignalCard renderizzata:
    ✅ ESEGUI | BULLISH ↑ · 1h | 72 · forte | $574.24 ▼
    META
    Entry: $574.24 | Stop: $573.37 | TP1: $578.45 | R/R: 1.50
    Rischio: €4.35 · Guadagno TP1: €6.52
    [rsi momentum continuation ============================] 81%
    ↳ "Pattern validato su 1h, WR 64%, EV +1.8R"
    [📋 Copia parametri] [Pagina serie →]
```

---

## Appendice B — Limitazioni note e decisioni consapevoli

Questa sezione documenta le limitazioni conosciute del sistema che sono state valutate e accettate intenzionalmente. Lo scopo è evitare che vengano riscoperte e debuggate come bug ignoti in futuro.

### B.1 Festività US nel calcolo VWAP e sessione

**Limitazione:** `_is_us_session()` e `_session_date()` in `indicator_extraction.py`, e `_is_market_hours()` in `tws_live_candle_service.py`, gestiscono correttamente il cambio ora legale EST/EDT tramite `zoneinfo`, ma **non gestiscono le festività USA** (Thanksgiving, Memorial Day, Independence Day, Christmas, mezze giornate di chiusura anticipata alle 13:00 ET).

**Effetto pratico:** nei giorni festivi NYSE, il VWAP di sessione viene calcolato su dati assenti o scarsissimi (volume quasi zero), producendo valori numericamente non significativi. Il live candle updater potrebbe tentare di girare anche in giorni di mercato chiuso. Non genera errori — produce semplicemente indicatori irrilevanti per quella giornata.

**Perché non è stato fixato:** richiederebbe la dipendenza `exchange_calendars` o `pandas_market_calendars`. Il costo in complessità supera il beneficio per uso personale intraday (le festività sono rare e facilmente riconoscibili visivamente sul grafico).

**Fix futuro:** integrare `exchange_calendars.get_calendar("XNYS")` in `_is_us_session()` e `_is_market_hours()` per escludere i giorni di chiusura NYSE.

---

### B.2 Correlazione temporale nel campione di backtest

**Limitazione:** `run_pattern_backtest()` tratta ogni occorrenza storica di un pattern come osservazione indipendente. Due occorrenze dello stesso pattern sullo stesso simbolo a 3 giorni di distanza durante lo stesso trend macro sono altamente correlate — ma il sistema le conta come 2 osservazioni indipendenti.

**Effetto pratico:** gli intervalli di confidenza Wilson mostrati nella pagina backtest sono sistematicamente troppo stretti. La significatività statistica (`***`, `**`, `*`) è probabilmente sovrastimata. Pattern classificati come "statisticamente significativi" potrebbero non esserlo dopo decorrelazione.

**Stesso problema cross-simbolo:** se 10 tech stocks scattano `bull_flag` lo stesso giorno, il backtest vede 10 osservazioni ma è un solo evento macro.

**Fix futuro:** introdurre un gap minimo di N barre tra osservazioni dello stesso pattern/simbolo prima di includerle nel campione, e/o clustering per evento temporale.

---

### B.3 Pesi del sistema di scoring non derivati statisticamente

**Limitazione:** le costanti numeriche che governano il `final_opportunity_score` (quality bonus max, strength bonus, penalità alignment, penalità policy) sono state calibrate qualitativamente, non su un dataset di validazione con esito noto.

**Effetto pratico:** i pesi riflettono giudizio intuitivo ("il quality score dominava troppo") più che ottimizzazione empirica. Possono essere modificati in sessioni successive senza convergenza verso un ottimo misurabile.

**Fix futuro:** costruire un dataset di 100-300 opportunità storiche con esito verificato (TP raggiunto, SL toccato, limbo) e usarlo come baseline per misurare l'effetto di ogni modifica ai pesi prima di applicarla.

---

### B.4 Quality score non stop-aware

**Limitazione:** `run_pattern_backtest()` calcola il win rate confrontando il forward return all'orizzonte primario con zero, senza simulare se lo stop-loss avrebbe interrotto il trade prima. Un trade che scende del 3% (sotto lo stop tipico) ma recupera e chiude positivo viene contato come "win".

**Effetto pratico:** il quality score e il pattern WR tendono a essere ottimistici rispetto alla performance operativa reale. Il sistema sovrastima la qualità dei pattern con alta volatilità intraday.

**Fix futuro:** unificare la logica di `trade_plan_backtest` (stop-aware) con `pattern_backtest` (forward return), oppure aggiungere una penalità basata sulla frequenza di drawdown intraday superiore alla distanza stop tipica.

---

### B.5 ML scorer strutturalmente unidirezionale

**Limitazione:** il ML scorer (`ml_signal_scorer.py`) può solo degradare decisioni `execute → monitor`, mai promuovere `monitor → execute`. È addestrato su dati già filtrati dal validator.

**Effetto pratico:** il modello non può recuperare opportunità che il validator ha scartato anche se statisticamente valide. Il suo valore atteso si limita al filtraggio di falsi positivi. Se il modello tende ad approvare sempre, il suo contributo netto è zero.

**Decisione consapevole:** approccio conservativo accettato per ora. Da valutare empiricamente misurando la frequenza con cui il modello cambia effettivamente la decisione rispetto al suo input.

---

### B.6 Notifiche Telegram/Discord non differenziate per canale

**Limitazione:** gli alert di mercato (nuovi segnali) e gli alert operativi (errori TWS, skip auto-execute, degradi di sistema) usano lo stesso canale Telegram/Discord senza distinzione.

**Effetto pratico:** un errore operativo critico ("TWS non connesso, ordini saltati") appare nella stessa notifica dei segnali di trading normali, con priorità percepita identica.

**Fix futuro:** aggiungere un prefisso `🚨 SYSTEM:` o un canale separato per gli alert operativi, permettendo di distinguere i "segnali di mercato da valutare" dagli "errori di sistema che richiedono intervento".

---

*Documento generato da analisi automatica del codice sorgente. Per aggiornamenti, rilanciare l'analisi dopo modifiche significative alla codebase.*
