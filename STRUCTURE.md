# Project Structure

Last reorganized: 2026-05-01

```
intraday-market-screener/
├── README.md                       # Overview progetto
├── DOCUMENTAZIONE_TECNICA.md       # Doc architettura completa
├── STRUCTURE.md                    # Questo file
├── docker-compose.yml              # Stack principale
├── docker-compose-ibkr.yml         # Override IBKR TWS
│
├── backend/                        # FastAPI backend (Python 3.12)
│   ├── app/                        # Codice produzione
│   │   ├── api/v1/routes/         # Endpoint REST
│   │   ├── core/                  # Config + costanti
│   │   ├── models/                # SQLAlchemy ORM
│   │   ├── schemas/               # Pydantic
│   │   ├── services/              # Business logic
│   │   ├── scheduler/             # APScheduler jobs
│   │   ├── db/                    # Session + bootstrap
│   │   └── main.py                # ASGI entry
│   ├── alembic/                    # DB migrations
│   ├── tests/                      # Pytest
│   ├── scripts/                    # Tool standalone
│   │   ├── build/                 # Dataset builders (val/production)
│   │   └── utils/                 # Operatività (cancel/check positions/orders)
│   ├── data/                       # Output runtime/scratch (gitignored)
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                       # Next.js 14 + TypeScript
│   ├── src/                        # Componenti, hooks, libs
│   ├── public/
│   └── package.json
│
├── research/                       # Codice di ricerca (non production)
│   ├── scripts/                    # Script analisi categorizzati
│   │   ├── monte_carlo/           # MC simulators (v1...v6, finale_ep, etc.)
│   │   ├── audit/                 # Verifiche calcoli, OOS, pool TRIPLO
│   │   ├── analysis/              # Analisi singola dimensione (volume, ora, simbolo, ecc.)
│   │   ├── onboarding/            # Pipeline new symbols (check, ingest, evaluate, promote)
│   │   ├── pre_live/              # Smoke test pre-deploy
│   │   └── _archive/              # Script obsoleti (riferimento storico)
│   └── datasets/                   # CSV/parquet per analisi
│       └── _archive/              # Dataset legacy (gitignored)
│
├── scripts/                        # Pipeline shell PowerShell
│   └── pipeline/                  # backfill, extract, indicators_patterns
│
├── docs/                           # Documentazione
│   ├── baseline.md
│   └── legacy/                    # Doc obsoleta (CONTESTO, OTTIMIZZAZIONI, paper_log)
│
├── docker/                         # Dockerfile dedicati
├── ibkr-config/                    # IBKR TWS config files
└── archive/                        # File obsoleti da root (gitignored)
    ├── legacy_root/               # .py loose root (test, place_order_, optimize_)
    └── legacy_logs/               # Log files vecchi
```

## Convenzioni

### Backend (`backend/app/`)

Strutturato come pacchetto Python standard:

- `core/`: costanti immutabili, configurazione (no logica DB/IO)
- `models/`: SQLAlchemy ORM (1 file per tabella)
- `schemas/`: Pydantic request/response (1 file per dominio)
- `services/`: business logic (1 file per servizio)
- `api/v1/routes/`: route handlers (1 file per dominio API)

### Research (`research/scripts/`)

Categorizzazione semantica:

| Cartella | Scope |
|---|---|
| `monte_carlo/` | Simulazioni Monte Carlo, edge degradation, MC v1...v6 |
| `audit/` | Verifiche correttezza calcoli, OOS, pool TRIPLO REALE |
| `analysis/` | Analisi singola dimensione (volume, ora, simbolo, pattern) |
| `onboarding/` | Pipeline aggiunta nuovi simboli (check + ingest + evaluate + promote) |
| `pre_live/` | Smoke test prima del deploy live |
| `_archive/` | Script obsoleti — leggibili come riferimento storico, non eseguibili |

### Naming

- Codice production: snake_case
- Script research one-shot: prefisso descrittivo (`mc_*`, `verify_*`, `analyze_*`, `audit_*`)
- File obsoleti: prefisso `_` (es. `_check_wr.py`)

## Esecuzione comandi tipici

### Build dataset validation 5m

```bash
docker exec intraday-market-screener-backend-1 \
  python scripts/build/build_validation_dataset.py \
  --timeframe 5m --output data/val_5m_xxx.csv --holdout-days 0 --limit 200000
```

### Pipeline extract simboli

```powershell
# Pipeline completa per simboli scheduler
pwsh scripts/pipeline/pipeline_extract.ps1
pwsh scripts/pipeline/pipeline_indicators_patterns.ps1
```

### Onboarding nuovi simboli

```bash
# 1. Check fattibilità
python research/scripts/onboarding/check_candidate_symbols.py

# 2. Backfill + pipeline (4 fasi: features+contexts+indicators+patterns)
python research/scripts/onboarding/pipeline_candidates.py

# 3. Validazione OOS
python research/scripts/onboarding/evaluate_candidates_oos.py

# 4. Promozione
python research/scripts/onboarding/promote_candidates.py
```

### MC con config attuale (Config D + Risk per ora)

```bash
python research/scripts/monte_carlo/monte_carlo_v6.py
python research/scripts/monte_carlo/mc_3k_realistic.py  # con €3k start + €200/m
```

## Cosa è gitignored

- `__pycache__/`, virtualenvs, build artifacts
- `archive/` — file legacy locali, non versionati
- `research/datasets/_archive/` — dataset legacy
- `research/datasets/_tmp_*` — scratch
- `research/datasets/_ppr_cache_5m.parquet` — cache JOIN DB
- `backend/data/*.txt`, `*.log` — output script
- `node_modules/`, `.next/`, etc.
- `.env`, `.env.local` — credenziali

## Note

- I file in `_archive/` o `archive/` **non vanno modificati** — sono freezati per riferimento storico/debug.
- I path nei script research possono usare `r"C:\Lavoro\..."` assoluto (ok per dev locale) o relativo dal root.
- Per spostare uno script da archive a attivo, copia (non muovere) e applica refactor.
