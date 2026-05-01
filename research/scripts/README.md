# Research Scripts

Script di analisi/ricerca/audit non in produzione, categorizzati per scopo.

## `monte_carlo/` (19 script)

Simulazioni Monte Carlo per stimare equity finale, drawdown, edge degradation.

| Script | Scope |
|---|---|
| **`monte_carlo_v6.py`** | ✅ ATTIVO — bootstrap mensile + slot cap reali + risk per ora |
| **`mc_3k_realistic.py`** | ✅ ATTIVO — €3k start + €200/m + slot variabili per capitale |
| `mc_definitivo_post_audit.py` | post-audit con MIDDAY filter |
| `final_mc_oos.py` | OOS specific |
| `triple_config_mc.py` | confronto Config A/B/C |
| `monte_carlo_v[2-5]*.py` | versioni precedenti (riferimento) |
| `mc_finale_ep.py`, `mc_aggiornato.py`, ... | versioni intermedie |

## `audit/` (11 script)

Verifiche correttezza calcoli, validazione OOS, pool TRIPLO REALE.

| Script | Scope |
|---|---|
| **`audit_calc_chain.py`** | ✅ ATTIVO — verifica catena di calcolo eff_r |
| **`verify_5m_findings.py`** | ✅ ATTIVO — confronta finding su pool TRIPLO |
| **`verify_top_findings_oos.py`** | ✅ ATTIVO — OOS verification dei top finding |
| **`is_oos_compare_1h.py`** | ✅ ATTIVO — confronto IS vs OOS forward 1h |
| **`evaluate_candidates_oos.py`** | ✅ ATTIVO — promotion decision per nuovi simboli |
| `oos_validation.py`, `oos_test_2026.py` | OOS legacy |
| `crossval_check.py`, `validate_full_dataset.py`, ecc. | varie validation |

## `analysis/` (45 script)

Analisi specifiche per dimensione (volume, ora, simbolo, pattern, regime, ecc.).

Top picks attivi:
- **`research_31_improvements.py`** — testbed 31 ipotesi miglioramento
- **`universe_analysis.py`** — profilo simboli, correlazioni, drag/wins
- **`find_5m_alpha.py`** — exploration alpha 5m
- **`alternative_strategies.py`** — confronto strategie
- **`ottimizzazione_trailing.py`** — trailing stop varie config
- **`test_risk_sizing_5m.py`** — risk size dinamico
- **`test_triplo_alternatives.py`** — varianti TRIPLO

Resto (`analisi_*.py`, `analyze_*.py`): analisi storiche, riferimento.

## `onboarding/` (4 script)

Pipeline completa per aggiungere nuovi simboli all'universo.

Sequenza:
1. **`check_candidate_symbols.py`** — verifica disponibilità Alpaca + profilo (ATR%, vol, prezzo)
2. **`pipeline_candidates.py`** — backfill + features + contexts + **indicators** + patterns
3. **`evaluate_candidates_oos.py`** — pool TRIPLO + Config D + decisione promote
4. **`promote_candidates.py`** — modifica `SYMBOLS_BLOCKED_ALPACA_5M` per i promossi

`build_production_2026.py`: utility build dataset filtered.

## `pre_live/` (3 script)

Smoke test pre-deploy production.

- **`preliive_check.py`** — verifica config + DB + universo
- `quick_check.py` — sanity check veloce
- `close_positions_monday.py` — script week-end close

## `_archive/` (0 file attualmente)

Riservato per script obsoleti che non hanno più valore documentale.

---

## Convenzioni

- Path **assoluti Windows** (`r"C:\Lavoro\Trading\..."`) sono ok per dev locale
- `PYTHONIOENCODING=utf-8` per evitare cp1252 issues con caratteri Unicode
- Connessione DB: `psycopg2.connect(host="localhost", port=5432, ...)` direttamente sul host (postgres exposed on 5432)
- Per script che richiedono backend FastAPI live: sicurarsi che `docker compose up backend` sia attivo

## Workflow tipico

### Audit OOS post-implementation

```bash
PYTHONIOENCODING=utf-8 python research/scripts/audit/verify_5m_findings.py
PYTHONIOENCODING=utf-8 python research/scripts/audit/verify_top_findings_oos.py
```

### Onboarding nuovo simbolo

```bash
python research/scripts/onboarding/check_candidate_symbols.py    # 1. profilo
python research/scripts/onboarding/pipeline_candidates.py        # 2. backfill + pipeline
python research/scripts/onboarding/evaluate_candidates_oos.py    # 3. validation OOS
python research/scripts/onboarding/promote_candidates.py         # 4. promote (modifica symbols.py)
```

### Stima MC realistica

```bash
PYTHONIOENCODING=utf-8 python research/scripts/monte_carlo/mc_3k_realistic.py
```
