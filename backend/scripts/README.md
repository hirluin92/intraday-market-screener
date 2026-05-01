# Backend Scripts

Tool standalone per il backend, organizzati per scopo.

## `build/` — Dataset builders

Script che generano dataset CSV per l'analisi (validation/production):

- **`build_validation_dataset.py`** — costruisce dataset OOS da DB con simulazione trade plan completa. Args: `--timeframe`, `--output`, `--holdout-days`, `--limit`.
- **`build_production_dataset.py`** — applica filtri produzione al dataset grezzo per ottenere il pool finale.

### Uso tipico

```bash
# Da host
docker exec intraday-market-screener-backend-1 \
  python scripts/build/build_validation_dataset.py \
  --timeframe 5m --output data/val_5m_xxx.csv --holdout-days 0 --limit 200000
```

## `utils/` — Utility operative

Script per gestione manuale ordini, posizioni, candele live:

- **`cancel_all_orders.py`** — cancella tutti gli ordini aperti su TWS
- **`check_and_cancel_orders.py`** — query + cancel selettivo
- **`check_live_candles.py`** — verifica freshness dati live
- **`check_opps.py`** — query opportunità correnti
- **`check_positions.py`** — query posizioni TWS
- **`place_order_mdb.py`** — esempio piazzamento ordine manuale
- **`test_order_roundtrip.py`** — smoke test full roundtrip

### Uso tipico

```bash
docker exec intraday-market-screener-backend-1 python scripts/utils/check_positions.py
```

## Note

- Tutti gli script richiedono che il backend sia running (per credenziali + DB session).
- Path nel container: `/app/scripts/build/`, `/app/scripts/utils/`.
- Dal host: `backend/scripts/build/`, `backend/scripts/utils/`.
