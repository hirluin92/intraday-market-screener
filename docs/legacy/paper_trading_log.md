# Paper Trading Log — intraday-market-screener

**Account:** U21629924  
**Inizio paper trading:** 2026-04-15  
**Cadenza rilevazione:** ogni 2 settimane  
**Obiettivo:** 60–90 giorni di osservazione pulita, senza modifiche al sistema

---

## Come fare una rilevazione

```bash
# Dal terminale con il backend attivo, chiama i 4 endpoint e salva l'output:
curl -s "http://localhost:8000/api/v1/monitoring/execution-stats?days=14" | python -m json.tool
curl -s "http://localhost:8000/api/v1/monitoring/fill-stats?days=14"      | python -m json.tool
curl -s "http://localhost:8000/api/v1/monitoring/slippage-stats?days=14"  | python -m json.tool
curl -s "http://localhost:8000/api/v1/monitoring/auto-execute-config"     | python -m json.tool
```

Incolla i valori chiave nella sezione della rilevazione corrispondente.

---

## Rilevazione #1 — 2026-04-15 (baseline)

**Stato connessione TWS:** ✓ connesso — account U21629924, polling `/health/ibkr` 200 OK  
**Posizioni aperte rilevate nei log:**
- NVDA: LONG 6 pezzi, avgCost 196.42, marketPrice 195.92, unrealizedPNL −2.99
- LLY: SHORT 2 pezzi, avgCost 921.69, marketPrice 926.00, unrealizedPNL −8.62

### execution-stats (days=14)

```json
{
  // incolla output reale al momento della rilevazione
}
```

### fill-stats (days=14)

```json
{
  // incolla output reale al momento della rilevazione
}
```

### slippage-stats (days=14)

```json
{
  // incolla output reale al momento della rilevazione
}
```

### auto-execute-config

```json
{
  // incolla output reale al momento della rilevazione
}
```

### Note qualitative

- Prima rilevazione, usata come baseline. Sistema appena avviato, nessun trade eseguito ancora.
- **2026-04-15:** attivati abbonamenti dati di mercato IBKR richiesti. Errori `10089` (OKLO, NVDA, LLY, NNE, SMR) e `10167` attesi in via di risoluzione dal prossimo ciclo pipeline.
- Warning `tick_size.resolve_asset_class` su exchange `YAHOO_US` / `ALPACA_US` = cosmetic, fallback corretto a `us_stock`.
- **2026-04-15:** aggiunto `range_expansion_breakout_candidate` a `_PATTERN_ENTRY_STRATEGY` per eliminare warning ripetuto nei log (10 occorrenze per ciclo).

---

## Rilevazione #2 — 2026-04-29

### execution-stats (days=14)

| Campo | Valore |
|-------|--------|
| total_attempts | |
| successfully_submitted | |
| failed_attempts | |
| success_rate_pct | |
| breakdown_by_status | |

### fill-stats (days=14)

| Campo | Valore |
|-------|--------|
| total_fills | |
| full_fills | |
| partial_fills | |
| rejected | |

### slippage-stats (days=14)

| Campo | Valore |
|-------|--------|
| trades_with_close | |
| avg_realized_r | |
| avg_nominal_r | |
| avg_slippage_r | |

### Note qualitative

---

## Rilevazione #3 — 2026-05-13

### execution-stats (days=14)

| Campo | Valore |
|-------|--------|
| total_attempts | |
| successfully_submitted | |
| failed_attempts | |
| success_rate_pct | |

### fill-stats (days=14)

| Campo | Valore |
|-------|--------|

### slippage-stats (days=14)

| Campo | Valore |
|-------|--------|

### Note qualitative

---

## Rilevazione #4 — 2026-05-27

### execution-stats (days=14)

| Campo | Valore |
|-------|--------|

### fill-stats (days=14)

| Campo | Valore |
|-------|--------|

### slippage-stats (days=14)

| Campo | Valore |
|-------|--------|

### Note qualitative

---

## Rilevazione #5 — 2026-06-10

### execution-stats (days=14)

| Campo | Valore |
|-------|--------|

### fill-stats (days=14)

| Campo | Valore |
|-------|--------|

### slippage-stats (days=14)

| Campo | Valore |
|-------|--------|

### Note qualitative

---

## Rilevazione #6 — 2026-06-24 (fine periodo 60–90 giorni)

### execution-stats (days=70)

| Campo | Valore |
|-------|--------|
| total_attempts | |
| successfully_submitted | |
| failed_attempts | |
| success_rate_pct | **TARGET: ≥ 95%** |
| breakdown_by_status | |

### fill-stats (days=70)

| Campo | Valore |
|-------|--------|

### slippage-stats (days=70)

| Campo | Valore |
|-------|--------|
| avg_slippage_r | **TARGET: valutare se > −0.1R sistematico** |

### Riepilogo finale

| Metrica | Valore | Target | Esito |
|---------|--------|--------|-------|
| success_rate_pct | | ≥ 95% | |
| avg_realized_r | | > 0 | |
| segnali execute/giorno (media) | | ≥ 1 | |
| segnali confluence bloccati/giorno | | da misurare | |

### Decisioni post paper trading

- [ ] Abilitare 5m se dataset OOS costruito
- [ ] Valutare abbonamento real-time IBKR per live capital
- [ ] Rivalutare `SIGNAL_MIN_CONFLUENCE` se volume segnali troppo basso
- [ ] Rivalutare varianti watchlist che hanno fatto male in live
