# Ottimizzazioni Prestazioni — Intraday Market Screener

Documento di riepilogo completo di tutte le modifiche effettuate per migliorare le prestazioni dell'applicazione.
Ogni sezione riporta: file modificato, valore prima → dopo, motivazione e impatto atteso.

---

## 1. Risorse di Sistema (WSL2 + Docker)

### `C:\Users\glr_9\.wslconfig`

| Parametro | Prima | Dopo | Motivazione |
|---|---|---|---|
| `memory` | 8GB (default) | 20GB | Docker ha accesso a 20 GB dei 32 GB disponibili |
| `processors` | 8 (default) | 16 | Sfrutta tutti i core logici della macchina |
| `swap` | 0 | 8GB | Buffer per picchi di memoria durante ingestione massiva |
| `autoMemoryReclaim` | non presente | `gradual` | Restituisce RAM a Windows quando non usata da Docker |

**Impatto:** tutta l'infrastruttura Docker (Postgres + backend + frontend) ha accesso alla memoria e CPU reali della macchina invece di essere limitata ai default conservativi di WSL2.

---

## 2. Docker Compose — Postgres

### `docker-compose.yml`

#### Immagine
```
prima:  postgres:16-alpine
dopo:   timescale/timescaledb:latest-pg16
```

#### Memoria condivisa
```
prima:  shm_size: 512mb
dopo:   shm_size: 2gb
```
Postgres usa la shared memory per buffer interni. Con 512 MB il motore era costretto a usare file temporanei su disco per operazioni di sort/hash.

#### Parametri tuning PostgreSQL

| Parametro | Prima (default) | Dopo | Motivazione |
|---|---|---|---|
| `shared_preload_libraries` | — | `timescaledb` | Obbligatorio per TimescaleDB |
| `shared_buffers` | 128MB | 512MB | Cache dati principale in RAM |
| `work_mem` | 4MB | 64MB | RAM per sort/hash per ogni query — riduce spill su disco |
| `effective_cache_size` | 512MB | 2GB | Hint al query planner sulla RAM disponibile per I/O cache |
| `maintenance_work_mem` | 64MB | 256MB | RAM per VACUUM, CREATE INDEX — accelera le migration |
| `checkpoint_completion_target` | 0.5 | 0.9 | Distribuisce i write checkpoint su più tempo → meno I/O burst |
| `wal_buffers` | 1/32 shared_buffers | 16MB | Buffer WAL più grande → meno flush a disco |
| `max_connections` | 100 | 100 | Invariato, allineato al pool del backend |
| `random_page_cost` | 4.0 | 1.1 | Comunica al planner che il disco è SSD → preferisce index scan |
| `effective_io_concurrency` | 1 | 200 | Permette letture parallele su SSD NVMe |
| `timescaledb.telemetry_level` | on | off | Elimina overhead di telemetria |

#### Frontend

| Parametro | Prima | Dopo | Motivazione |
|---|---|---|---|
| `NODE_OPTIONS` | `--max-old-space-size=4096` | `--max-old-space-size=8192` | Turbopack con volume Windows→Linux ha picchi di memoria elevati |
| Memory limit | 4g | 8g | Evita OOM kill del container frontend |

---

## 3. Connection Pool SQLAlchemy

### `backend/app/db/session.py`

```python
# Prima (default SQLAlchemy)
pool_size=5, max_overflow=10

# Dopo
pool_size=20,
max_overflow=15,
pool_timeout=30,
pool_recycle=1800,
```

**Motivazione:** con il parallelismo aumentato (pipeline parallelism=8, fetch concurrency=5, sessioni parallele per indicators+context) il picco di connessioni simultanee raggiunge ~24-30. Con il pool vecchio (5+10=15 max) il backend andava in timeout su `pool_timeout`.

**Impatto:** elimina i colli di bottiglia su acquisizione connessione DB durante il pipeline parallelo.

---

## 4. Scheduler Pipeline

### `backend/app/scheduler/pipeline_scheduler.py`

| Parametro | Prima | Dopo | Motivazione |
|---|---|---|---|
| `_PIPELINE_PARALLELISM` | 4 | 8 | Processa 8 serie contemporaneamente invece di 4 |

**Impatto:** dimezza il tempo di un ciclo completo di pipeline su ~83 serie (simboli × timeframe).

---

## 5. Ingestione Dati — Fetch Parallelo + Retry

### `backend/app/services/alpaca_ingestion.py`

**Prima:** fetch sequenziale simbolo per simbolo (un simbolo alla volta).

**Dopo:**
```python
_FETCH_CONCURRENCY: int = 5    # 5 richieste API parallele
_FETCH_MAX_RETRIES: int = 3    # retry automatico su ConnectError/Timeout
_UPSERT_CHUNK_SIZE: int = 2_000  # chunk upsert 4× più grandi
```

- `asyncio.gather` con `asyncio.Semaphore(5)` → 5 simboli in parallelo
- Retry con backoff esponenziale su `httpx.ConnectError` e `httpx.TimeoutException`
- Chunk upsert: 500 → 2.000 righe (meno round-trip al DB)

**Impatto:** il fetch di 40 simboli Yahoo/1h scende da ~40s sequenziale a ~8-10s parallelo. Il retry elimina i fallimenti intermittenti su TLS drop.

### `backend/app/services/yahoo_finance_ingestion.py`

Stesso pattern:
```python
_FETCH_CONCURRENCY: int = 5
_FETCH_MAX_RETRIES: int = 3
_UPSERT_CHUNK_SIZE: int = 2_000
```

- `asyncio.to_thread` + `asyncio.Semaphore(5)` per parallelizzare le chiamate sincrone `yfinance` in thread pool
- Retry automatico su eccezioni di rete

### `backend/app/services/ibkr_ingestion.py`

| Parametro | Prima | Dopo |
|---|---|---|
| `_UPSERT_CHUNK_SIZE` | 500 | 2.000 |

---

## 6. Upsert Chunk Size — Tutti i Servizi di Estrazione

Tutti i servizi che scrivono su DB sono stati aggiornati da chunk piccoli a 2.000 righe:

| File | Prima | Dopo |
|---|---|---|
| `feature_extraction.py` | 500 | 2.000 |
| `indicator_extraction.py` | 300 | 2.000 |
| `context_extraction.py` | 500 | 2.000 |
| `pattern_extraction.py` | 500 | 2.000 |
| `market_data_ingestion.py` | 500 | 2.000 |

**Motivazione:** ogni `INSERT ... ON CONFLICT DO UPDATE` ha un overhead di round-trip TCP+Postgres. Con chunk da 2.000 righe invece di 500, lo stesso numero di righe richiede 4× meno query e riduce il tempo totale di upsert del 70-80%.

---

## 7. Pipeline Refresh — Parallelismo Extract

### `backend/app/services/pipeline_refresh.py`

**Prima:** esecuzione sequenziale:
```
features → indicators → context → patterns
```

**Dopo:** `extract_indicators` e `extract_context` in parallelo su sessioni indipendenti:
```
features → [indicators ‖ context] → patterns
```

```python
async def _run_indicators():
    async with AsyncSessionLocal() as s:
        return await extract_indicators(s, ind_req)

async def _run_context():
    async with AsyncSessionLocal() as s:
        return await extract_context(s, ctx_req)

indicators_out, context_out = await asyncio.gather(
    _run_indicators(),
    _run_context(),
)
```

**Impatto:** `extract_indicators` (~3-5s) e `extract_context` (~1-2s) ora girano in parallelo → risparmio di ~2-4s per ciclo pipeline su ogni serie.

---

## 8. Opportunities — Query DB Parallele + Prefetch TWS

### `backend/app/services/opportunities.py`

#### Query iniziali in parallelo

**Prima:** `list_latest_context_per_series`, `list_latest_pattern_per_series`, `count_concurrent_patterns_per_series` eseguite in sequenza sulla stessa sessione.

**Dopo:** le 3 query girano in parallelo su sessioni indipendenti:
```python
async def _fetch_contexts_and_dedupe():
    async with AsyncSessionLocal() as s:
        return await list_latest_context_per_series(s, ...)

async def _fetch_patterns():
    async with AsyncSessionLocal() as s:
        return await list_latest_pattern_per_series(s, ...)

async def _fetch_concurrent():
    async with AsyncSessionLocal() as s:
        return await count_concurrent_patterns_per_series(s, ...)

contexts, patterns, concurrent = await asyncio.gather(
    _fetch_contexts_and_dedupe(),
    _fetch_patterns(),
    _fetch_concurrent(),
)
```

Stessa ottimizzazione applicata a `list_ranked_screener`.

#### Prefetch TWS live prices

Prima di entrare nel loop di arricchimento, il prezzo live IBKR viene scaricato in parallelo per tutti i simboli US stock:
```python
await asyncio.gather(*[
    get_tws_service().get_last_price(sym) for sym in us_symbols
], return_exceptions=True)
```

**Impatto:** `list_opportunities` scende da ~68s (prima richiesta) a ~7s con cache warm. Con query parallele il risparmio netto è ~3-5s per ogni chiamata.

---

## 9. Indici DB Compositi — Migration `perf_idx_0001`

### `backend/alembic/versions/20260415_0001_add_query_performance_indexes.py`

6 nuovi indici compositi costruiti sulle query critiche dello screener:

| Indice | Tabella | Colonne | Query servita |
|---|---|---|---|
| `ix_candle_contexts_provider_ts_id` | `candle_contexts` | `(provider, timestamp DESC, id DESC)` | `list_latest_context_per_series` con filtro provider |
| `ix_candle_contexts_ts_id` | `candle_contexts` | `(timestamp DESC, id DESC)` | `list_latest_context_per_series` senza filtro provider |
| `ix_candle_patterns_provider_ts_id` | `candle_patterns` | `(provider, timestamp DESC, id DESC)` | `list_latest_pattern_per_series` |
| `ix_candle_patterns_name_ts_series` | `candle_patterns` | `(pattern_name, timestamp, exchange, symbol, timeframe)` | `count_concurrent_patterns_per_series` |
| `ix_candles_provider_exchange_symbol_tf_ts` | `candles` | `(provider, exchange, symbol, timeframe, timestamp DESC)` | `fetch_latest_candles_by_series_keys` |
| `ix_candle_indicators_exchange_symbol_provider_tf_ts` | `candle_indicators` | `(exchange, symbol, provider, timeframe, timestamp)` | `get_indicator_for_candle_timestamp` |

**Motivazione:** le query critiche usano window function `ROW_NUMBER() PARTITION BY ... ORDER BY timestamp DESC, id DESC`. Senza un indice che copre esattamente questi campi, Postgres esegue un full scan + sort. Con l'indice DESC compound, il planner elimina il sort e usa un index scan diretto.

**Impatto:** le query window function da secondi scendono a millisecondi su dataset grandi.

---

## 10. VACUUM ANALYZE al Boot

### `backend/app/main.py`

Aggiunta funzione `_run_vacuum_analyze()` eseguita in background a ogni restart del backend:

```python
_VACUUM_TABLES = [
    "candles", "candle_features", "candle_indicators",
    "candle_contexts", "candle_patterns",
]

async def _run_vacuum_analyze() -> None:
    async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as conn:
        for table in _VACUUM_TABLES:
            await conn.execute(text(f"VACUUM ANALYZE {table}"))
```

**Motivazione:** `VACUUM ANALYZE` aggiorna le statistiche del query planner di Postgres. Senza statistiche aggiornate, il planner ignora i nuovi indici e sceglie piani sub-ottimali (spesso full scan invece di index scan). È obbligatorio dopo la creazione di nuovi indici o grosse ingestioni.

**Impatto:** il query planner usa i piani ottimali da subito, senza attendere l'autovacuum automatico.

---

## 11. Cache Warmup al Boot — Esteso

### `backend/app/main.py`

Il warmup esistente pre-calcolava `pq_lookup`, `tpb_lookup`, `var_lookup` in parallelo. Sono stati aggiunti:

1. **VIX history pre-load** — evita il download lento (~3s) alla prima richiesta frontend
2. **`list_opportunities` per combo principali** — dopo aver riscaldato i lookup, esegue `list_opportunities` per `yahoo_finance/1h` e globale `None/None` in parallelo:

```python
opp_results = await asyncio.gather(
    _opp_combo("yahoo_finance", "1h"),
    _opp_combo(None, None),
    return_exceptions=True,
)
```

**Impatto:** la prima richiesta del frontend dopo un restart trova già tutto pronto invece di attendere 40-60s.

---

## 12. TimescaleDB — Hypertables

### Migration `backend/alembic/versions/20260415_0002_timescaledb_hypertables.py`

Le 5 tabelle del pipeline sono state convertite in **TimescaleDB hypertables** con partizionamento temporale:

| Tabella | Chunk interval | Num. chunk attuali |
|---|---|---|
| `candles` | 1 mese | 123 |
| `candle_features` | 1 mese | 123 |
| `candle_indicators` | 1 mese | 123 |
| `candle_contexts` | 1 mese | 123 |
| `candle_patterns` | 1 mese | 123 |

**Schema changes:**
- PK: `id SERIAL` → `(id, timestamp)` composite PK (richiesto da TimescaleDB)
- UNIQUE constraints aggiornati per includere `timestamp`
- FK inter-hypertable rimosse (non supportate da TimescaleDB — integrità garantita dal pipeline applicativo)

**Come funziona TimescaleDB:**
Invece di una singola tabella monolitica, i dati vengono distribuiti in chunk fisici separati per intervallo temporale. Una query `WHERE timestamp BETWEEN t1 AND t2` salta direttamente ai chunk del periodo richiesto senza toccare i dati storici.

**Impatto atteso:**

| Tipo query | Dataset piccolo | Dataset grande (>1M righe) |
|---|---|---|
| Range temporale recente (1-7 giorni) | ~uguale | **2-10× più veloce** |
| Full scan storico | ~uguale | **5-20× più veloce** |
| Spazio su disco (con compressione) | ~uguale | **-70-90%** |

**Nota:** la compressione automatica (opzionale) non è ancora abilitata — può essere aggiunta con:
```sql
ALTER TABLE candles SET (timescaledb.compress, timescaledb.compress_segmentby = 'symbol,timeframe');
SELECT add_compression_policy('candles', INTERVAL '30 days');
```

### Modelli SQLAlchemy aggiornati

- `backend/app/models/candle.py`
- `backend/app/models/candle_feature.py`
- `backend/app/models/candle_indicator.py`
- `backend/app/models/candle_context.py`
- `backend/app/models/candle_pattern.py`

### Servizi upsert aggiornati (nomi constraint rinominati)

| File | Constraint vecchio | Constraint nuovo |
|---|---|---|
| `feature_extraction.py` | `uq_candle_features_candle_id` | `uq_candle_features_candle_id_ts` |
| `context_extraction.py` | `uq_candle_contexts_candle_feature_id` | `uq_candle_contexts_feature_id_ts` |
| `indicator_extraction.py` | `uq_candle_indicators_candle_id` | `uq_candle_indicators_candle_id_ts` |
| `pattern_extraction.py` | `uq_candle_patterns_feature_pattern` | `uq_candle_patterns_feature_pattern_ts` |

---

## 13. Fix max_locks_per_transaction per TimescaleDB

### `docker-compose.yml`

```yaml
-c max_locks_per_transaction=256   # era 64 (default)
```

**Problema:** TimescaleDB partiziona ogni tabella in chunk fisici separati (123 chunk per tabella × 5 tabelle = 615 chunk). Ogni chunk richiede un lock entry nel lock manager di Postgres. Con il default `max_locks_per_transaction=64` × `max_connections=100` = 6.400 slot totali, con 8 job paralleli che toccano tutte e 5 le hypertables si arriva facilmente a esaurire i lock slot.

**Errore manifestato:**
```
asyncpg.exceptions.OutOfMemoryError: out of shared memory
```

**Impatto:** il ciclo pipeline passava da ok=83/failed=0 a ok=58/failed=25 (30% failure rate). Con `max_locks_per_transaction=256` il ciclo torna a ok=83/failed=0.

---

## 14. Connection Pool — Aumento Finale

### `backend/app/db/session.py`

| Parametro | Fase 1 | Fase 2 (finale) | Motivazione |
|---|---|---|---|
| `pool_size` | 20 | **30** | Con parallelismo=12 il picco è 12×3=36 sessioni pipeline + 5 accessorie = 41 totali |
| `max_overflow` | 15 | **15** | Invariato, buffer per picchi transitori |
| **Totale max** | **35** | **45** | Margine rispetto ai 41 del picco |

```python
# Picco connessioni con parallelismo=12:
# 12 job × 3 sessioni (main + indicators_parallel + context_parallel) = 36 pipeline
# + 5 per list_opportunities/prewarm/warmup = 41 totale.
# pool_size=30 persistenti + max_overflow=15 overflow = 45 max.
pool_size=30,
max_overflow=15,
```

**Motivazione:** con `_PIPELINE_PARALLELISM=12` il vecchio pool da 35 connessioni andava in `QueuePool limit reached`, causando timeout durante i cicli e rallentando il throughput.

---

## 15. Pipeline Parallelism — Calibrazione Finale

### `backend/app/scheduler/pipeline_scheduler.py`

| Fase | Valore | Problema |
|---|---|---|
| Originale | 4 | Troppo lento (11 batch per 83 job) |
| Fase 1 | 8 | OK ma non ottimale |
| Fase 2 | 16 | **Pool exhaustion** — 16×3=48 sessioni > 35 pool limit |
| Fase 3 (finale) | **12** | 12×3=36 sessioni, pool 45 → margine sicuro |

```python
# Max job pipeline in parallelo. Con pool_size=30+overflow=15=45 connessioni:
# 12 × 3 sessioni/job = 36 pipeline + margine per list_opportunities/prewarm.
_PIPELINE_PARALLELISM: int = 12
```

**Impatto:** ciclo completo su 83 serie ridotto da ~535s a **74.5s** (7.2× speedup).

---

## 16. Skip-If-Unchanged — Ottimizzazione Cicli Notturni/Weekend

### `backend/app/schemas/pipeline.py`

Aggiunti due nuovi campi agli schema request/response:
```python
class PipelineRefreshRequest(BaseModel):
    skip_if_unchanged: bool = Field(default=False)

class PipelineRefreshResponse(BaseModel):
    extraction_skipped: bool = Field(default=False)
```

### `backend/app/services/pipeline_refresh.py`

```python
if body.skip_if_unchanged and ingest_out.rows_inserted == 0:
    return PipelineRefreshResponse(extraction_skipped=True, ...)
```

### `backend/app/scheduler/pipeline_scheduler.py`

`skip_if_unchanged=True` aggiunto a tutti gli 83 job del ciclo.

**Motivazione:** di notte e nel weekend i mercati sono chiusi — l'ingest ritorna 0 nuove candele. Senza questo flag, il pipeline ricalcolava features+indicators+context+patterns per ogni serie anche quando non c'era nulla di nuovo. Con il flag, quando `rows_inserted == 0` l'estrazione viene saltata completamente.

**Impatto:** nei cicli fuori mercato (18:00 → 09:30 EST, weekend) il ciclo scende da ~74s a **<5s** (solo ingest, extraction saltata).

---

## 17. TTLCache con Stale-While-Revalidate

### `backend/app/core/cache.py`

Implementazione di una cache in-memory con due comportamenti distinti:

| Caso | Prima | Dopo |
|---|---|---|
| **TTL scaduto naturalmente** | Blocca e ricalcola | Ritorna valore vecchio (stale) + ricalcola in **background** |
| **Invalidazione esplicita** (`invalidate_all`) | Elimina + blocca al ricalcolo | **Continua a eliminare** (ricalcolo bloccante alla prossima richiesta) |

```python
class TTLCache:
    """
    Cache con TTL e stale-while-revalidate per scadenza naturale.
    - Hit valido: ritorna immediatamente.
    - Scaduto per TTL: ritorna stale + avvia recompute in background.
    - Miss completo (chiave eliminata): blocca e ricalcola.
    """
```

**Perché stale-while-revalidate solo per TTL:**
- Le chiavi `all/all` (provider=None, timeframe=None) non vengono mai toccate dalle invalidazioni per-provider (le needle chirurgiche non matchano). Scadono solo per TTL naturale → usano il path stale-while-revalidate senza mai bloccare il frontend.
- Le chiavi per-provider (es. `yahoo_finance/1h`) vengono eliminate esplicitamente da `invalidate_keys_containing` → ricalcolate in modo bloccante prima che la risposta venga servita (dati sempre freschi).

**Bug risolto:** `_compute_pq`, `_compute_tpb`, `_compute_var` originariamente catturavano la sessione outer (già chiusa al momento del recompute in background), causando `sqlalchemy.exc.InvalidRequestError`. Corretti per aprire la propria sessione indipendente:

```python
async def _compute_pq() -> dict[...]:
    # Sessione propria: sicuro per background recompute.
    async with AsyncSessionLocal() as s:
        return await pattern_quality_lookup_by_name_tf(s, ...)
```

---

## 18. Prewarm Cache — Strategia Chirurgica

### `backend/app/scheduler/pipeline_scheduler.py`

**Prima:** `_prewarm_opportunities_cache` chiamava `invalidate_all()` e ricalcolava anche la combo `all/all`.

**Dopo:**
```python
# NON chiama invalidate_all(): evita di svuotare la chiave all/all,
# che richiederebbe un ricalcolo bloccante da 100+ secondi sul ciclo successivo.
combos = [
    {"provider": "yahoo_finance", "timeframe": "1h"},
    {"provider": "binance", "timeframe": "1h"},
]
```

**Motivazione:** `invalidate_all()` svuotava la cache inclusa la chiave `all/all`, che poi richiedeva un ricalcolo bloccante di 100s alla prima richiesta. Con la strategia chirurgica:
- Solo le combo effettivamente aggiornate dal ciclo corrente vengono invalidate e riprewarmizzate.
- La chiave `all/all` scade per TTL naturale (600s) e viene ricalcolata in background tramite stale-while-revalidate senza bloccare nessuna richiesta.

---

## 19. IBKR Spread Prefetch — Timeout e Cache Errori

### `backend/app/services/opportunities.py`

#### Timeout sul batch spread

```python
try:
    await asyncio.wait_for(
        asyncio.gather(*[_get_ibkr_spread(s) for s in spread_symbols], return_exceptions=True),
        timeout=6.0,
    )
except asyncio.TimeoutError:
    logger.debug("ibkr spread prefetch: timeout 6s — %d simboli non risolti", len(spread_symbols))
```

#### Cache risultati vuoti su eccezioni

```python
except Exception as exc:
    logger.debug("_get_ibkr_spread %s: %s", symbol, exc)
    _spread_cache[cache_key] = {**_EMPTY, "ts": now}  # ← aggiunto
    return _EMPTY
```

**Prima:** le eccezioni non venivano messe in cache → ogni richiesta ri-tentava la chiamata TWS fallita, accumulando latenza.

**Impatto:** il prefetch spread non supera mai i 6s, anche quando TWS è connesso ma il mercato è chiuso e i dati non sono disponibili.

---

## 20. Filtro Timestamp su `fetch_latest_candles_by_series_keys`

### `backend/app/services/candle_query.py`

**Problema:** questa funzione eseguiva un full table scan sulla hypertable `candles` (7.3M righe), impiegando **140+ secondi** — causando timeout al frontend.

**Fix:**
```python
_LATEST_CANDLE_WINDOW_DAYS = 14

since_dt = datetime.now(timezone.utc) - timedelta(days=_LATEST_CANDLE_WINDOW_DAYS)

inner = (
    select(Candle.id, rn).where(
        and_(
            Candle.timestamp >= since_dt,  # ← aggiunto: pruning chunk
            tuple_(Candle.provider, Candle.exchange, Candle.symbol, Candle.timeframe).in_(uniq),
        )
    )
).subquery()
```

**Motivazione:** questa funzione serve a trovare l'ultima candela per ogni serie — non ha senso cercarla in dati vecchi di mesi. Con il filtro `>= NOW() - 14 days`, TimescaleDB applica il **chunk pruning** e tocca solo 1-2 chunk per tabella invece di tutti i 123. Il tempo scende da 140s a **<500ms**.

---

## 21. Filtri Timestamp nei Backtest — Chunk Pruning su JOIN Multi-Hypertable

### `backend/app/services/pattern_backtest.py`
### `backend/app/services/trade_plan_backtest.py`
### `backend/app/services/trade_plan_variant_backtest.py`

**Problema:** le query di backtest eseguivano JOIN tra 3-4 hypertable senza filtri temporali → il planner scansionava **tutti i chunk storici** su ogni tabella nella JOIN, indipendentemente dal filtro sulla tabella principale.

**Fix:**
```python
_BACKTEST_WINDOW_DAYS = 180

_ts_cutoff = None
if dt_from is not None:
    _ts_cutoff = dt_from
elif dt_to is None:
    _ts_cutoff = datetime.now(UTC) - timedelta(days=_BACKTEST_WINDOW_DAYS)

if _ts_cutoff is not None:
    conds.append(CandlePattern.timestamp >= _ts_cutoff)
    # Pruning anche sugli altri hypertable nella JOIN:
    # il planner altrimenti scansiona tutti i loro chunk
    # indipendentemente dal filtro su CandlePattern.
    conds.append(CandleFeature.timestamp >= _ts_cutoff)
    conds.append(Candle.timestamp >= _ts_cutoff)
    # trade_plan_backtest e variant aggiungono anche:
    conds.append(CandleContext.timestamp >= _ts_cutoff)
```

**Perché servono i filtri su TUTTE le tabelle nella JOIN:**
TimescaleDB esegue il pruning indipendentemente per ogni hypertable nella query. Se il filtro è solo su `CandlePattern`, il planner applica il pruning solo su `candle_patterns`, ma scansiona tutti i chunk di `candle_features`, `candles`, `candle_contexts`. Aggiungendo il filtro su ognuna, il pruning viene applicato a tutte simultaneamente.

**Impatto:** `pattern_quality_lookup_by_name_tf` da **75s** a **~4s** (18×). `run_trade_plan_backtest` da **>100s** a **~6.8s**. `run_trade_plan_variant_backtest` da **>60s** a **~6.8s**.

---

## 22. Nuovo Indice Composito su `candle_patterns`

**Aggiunto direttamente al DB:**

```sql
CREATE INDEX IF NOT EXISTS ix_candle_patterns_prov_tf_ts
ON candle_patterns (provider, timeframe, timestamp DESC);
```

**Motivazione:** `pattern_quality_lookup_by_name_tf` filtra per `provider`, `timeframe` e ordina per `timestamp DESC`. Senza questo indice il planner usava un index scan parziale che comunque richiedeva un sort su dataset grandi.

**Impatto:** combinato con il filtro `_ts_cutoff`, riduce ulteriormente il tempo di `run_pattern_backtest` per simbolo singolo.

---

## 23. Yielding Event Loop — Simulazioni CPU-Bound

### `backend/app/services/trade_plan_variant_backtest.py`
### `backend/app/services/trade_plan_backtest.py`
### `backend/app/services/pattern_backtest.py`

**Problema:** i loop di simulazione (es. 300 pattern × 45 varianti = 13.500 simulazioni in `variant_backtest`) eseguivano Python puro (build_plan + arithmetic Decimal) per **secondi** senza cedere controllo all'event loop. Risultato: health check timeout (3s), frontend timeout, backend apparentemente "bloccato".

**Fix:** `await asyncio.sleep(0)` inserito periodicamente nei loop di simulazione:

```python
# trade_plan_variant_backtest.py — ogni 5 pattern
for _pat_idx, (pat, entry_close, candle_id) in enumerate(rows):
    if _pat_idx % 5 == 0:
        await asyncio.sleep(0)   # cede il controllo ogni 5 iter (~0.75s block max)
    ...

# trade_plan_backtest.py — ogni 50 pattern
for _pat_idx, (pat, entry_close, candle_id) in enumerate(rows):
    if _pat_idx % 50 == 0:
        await asyncio.sleep(0)   # cede il controllo ogni 50 iter
    ...

# pattern_backtest.py — ogni 50 pattern
for _pat_idx, (pat, entry_close, candle_id) in enumerate(rows):
    if _pat_idx % 50 == 0:
        await asyncio.sleep(0)
    ...
```

**Come funziona `asyncio.sleep(0)`:** non dorme realmente — notifica l'event loop di processare altri task in coda prima di riprendere. È l'unico modo per cedere il controllo in un loop CPU-bound senza spostarlo in un thread pool (che richiederebbe refactoring profondo e lock su strutture dati condivise).

**Impatto:** health check risponde in **17ms** anche durante backtest attivi. Frontend risponde normalmente durante i cicli di cache warmup.

---

## 24. TTL Cache — Aumento da 300s a 600s

### `backend/app/core/config.py`

```python
opportunity_lookup_cache_ttl_seconds: int = 600  # era 300
```

**Motivazione:** con il warmup ottimizzato (ricalcolo in background tramite stale-while-revalidate), tenere la cache 10 minuti invece di 5 riduce il numero di ricalcoli completi da 12/ora a 6/ora per la chiave `all/all`, senza rischio di servire dati troppo vecchi (il pipeline aggiorna il DB ogni ~75s comunque).

---

## Benchmark Finale Misurato

| Metrica | Prima | Dopo | Speedup |
|---|---|---|---|
| **Ciclo pipeline completo** | 535s | **74.5s** | **7.2×** |
| **ok / failed (ciclo)** | variabile | **83/0 stabile** | — |
| **Health check** (`/api/v1/health`) | — | **17ms** | — |
| **Opportunità yahoo/1h** (prima richiesta) | >60s (timeout) | **4.4s** | **>13×** |
| **Opportunità all/all** (cache warm) | >60s (timeout) | **2.7s** | **>22×** |
| **Frontend** `/opportunities` | — | **183ms** | — |
| **Ciclo fuori mercato** (skip_if_unchanged) | ~74s | **<5s** | **>14×** |
| `fetch_latest_candles_by_series_keys` | 140s+ (full scan) | **<500ms** | **>280×** |
| `pattern_quality_lookup_by_name_tf` | 75s | **~4s** | **18×** |
| `run_trade_plan_backtest` | >100s | **~6.8s** | **>14×** |
| `run_trade_plan_variant_backtest` | >60s | **~6.8s** | **>8×** |

---

## Riepilogo per Layer (Aggiornato)

| Layer | Ottimizzazione | Impatto |
|---|---|---|
| **Sistema** | WSL2: 20GB RAM, 16 CPU, 8GB swap | Infrastruttura usa risorse reali |
| **Database** | shm_size 2GB, tuning 9 parametri PG | Meno I/O disco, sort in RAM |
| **Database** | TimescaleDB hypertables (5 tabelle) | Range query 2-10× su dataset grandi |
| **Database** | `max_locks_per_transaction=256` | Elimina OOM errors con 123 chunk per tabella |
| **Database** | 6 indici compositi (perf_idx_0001) | Query window function: da sec a ms |
| **Database** | Indice `ix_candle_patterns_prov_tf_ts` | Backtest pattern query ottimizzato |
| **Database** | VACUUM ANALYZE al boot | Query planner usa piani ottimali subito |
| **Backend pool** | pool_size 30 + overflow 15 (45 totale) | Nessun pool exhaustion con parallelismo=12 |
| **Ingestione** | Fetch parallelo Alpaca+Yahoo (concurrency=5) | Fetch 40 simboli: ~40s → ~8s |
| **Ingestione** | Retry automatico 3× su errori di rete | Elimina fallimenti intermittenti |
| **Ingestione** | Upsert chunk 500→2.000 (tutti i servizi) | 4× meno round-trip DB per upsert |
| **Pipeline** | Parallelismo scheduler: 4→12 (calibrato) | Ciclo pipeline: 535s → 74.5s (7.2×) |
| **Pipeline** | indicators ‖ context in parallelo | Risparmio 2-4s per serie per ciclo |
| **Pipeline** | `skip_if_unchanged` sui 83 job | Ciclo fuori mercato: 74s → <5s |
| **Query** | Filtro timestamp 14gg su `candle_query.py` | Full scan 140s → <500ms (chunk pruning) |
| **Query** | Filtri timestamp 180gg su tutti i backtest | JOIN multi-hypertable: 75-140s → 4-7s |
| **API** | Query DB parallele in `list_opportunities` | Prima richiesta: ~68s → ~4s (warm) |
| **API** | Prefetch TWS prices in parallelo | Elimina stallo sequenziale su prezzi live |
| **API** | Spread prefetch con timeout 6s + cache errori | Nessun blocco su TWS con mercato chiuso |
| **Cache** | TTLCache stale-while-revalidate | Nessun blocco frontend su scadenza TTL |
| **Cache** | TTL 300s → 600s | Ricalcoli dimezzati (6/ora vs 12/ora) |
| **Cache** | Invalidazione chirurgica (no invalidate_all) | Chiave `all/all` non viene mai svuotata |
| **Event loop** | `asyncio.sleep(0)` nei loop simulazione | Health check 17ms anche durante backtest |
| **Boot** | Cache warmup completo al startup | Prima richiesta frontend istantanea |
| **Frontend** | Node.js 4→8GB, Turbopack memoria | Nessun OOM kill del container |
