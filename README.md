# intraday-market-screener

MVP full-stack application for **intraday market screening**: ingest OHLCV (via ccxt), derive features and context, detect patterns, rank **opportunities**, optional **alert notifications** (Discord/Telegram), and a Next.js dashboard.

> 📐 **Project structure**: see [`STRUCTURE.md`](./STRUCTURE.md) for the directory layout and conventions (organized May 2026).

## Project overview

| Layer | Role |
|--------|------|
| **Backend** | FastAPI (`/api/v1`), SQLAlchemy + PostgreSQL, async pipeline (ingest → features → context → patterns), screener scoring, opportunity ranking, in-process scheduler (APScheduler). |
| **Frontend** | Next.js (App Router), calls the public API via `NEXT_PUBLIC_API_URL`. |
| **Database** | PostgreSQL 16; schema created at startup (`create_all`, no Alembic in MVP). |

## Architecture summary

```
┌─────────────┐     HTTP      ┌─────────────┐     asyncpg    ┌────────────┐
│  Next.js    │ ───────────► │   FastAPI   │ ─────────────► │ PostgreSQL │
│  (browser)  │   REST API   │   backend   │                │            │
└─────────────┘              └──────┬──────┘                └────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              ccxt (ingest)   extractors    scheduler
              market data     features /    (optional
                              context /      pipeline
                              patterns       refresh)
```

- **Opportunities** are computed on read from latest context + latest pattern per series (not a separate stored snapshot table).
- **Alert notifications** run at the end of `POST /api/v1/pipeline/refresh` (and the same code path from the optional scheduler): targeted series (exchange + symbol + timeframe), or **global** when symbol and timeframe are omitted (see [Alert notifications](#alert-notifications-discord--telegram)).

## Main backend endpoints

Base URL: `http://<host>:<BACKEND_PORT>/api/v1`

| Area | Method | Path | Purpose |
|------|--------|------|---------|
| Health | GET | `/health` | Liveness; DB check (`503` if DB down). |
| Market data | GET | `/market-data/candles` | Stored OHLCV. |
| | GET | `/market-data/features` | Feature rows. |
| | GET | `/market-data/context` | Context rows. |
| | GET | `/market-data/patterns` | Pattern rows. |
| | POST | `/market-data/ingest` | Ingest OHLCV from exchange. |
| | POST | `/market-data/features/extract` | Extract features. |
| | POST | `/market-data/context/extract` | Extract context. |
| | POST | `/market-data/patterns/extract` | Extract patterns. |
| Pipeline | POST | `/pipeline/refresh` | Full pipeline: ingest → features → context → patterns (shared filters). |
| Screener | GET | `/screener/latest` | Latest context snapshots. |
| | GET | `/screener/ranked` | Ranked screener rows. |
| | GET | `/screener/opportunities` | Opportunities (scores, patterns, alert flags). |
| Backtest | GET | `/backtest/patterns` | Pattern backtest aggregates (quality). |

Interactive docs: `/docs` (disabled when `ENVIRONMENT=production`).

## Frontend pages

| Route | Description |
|-------|-------------|
| `/` | Home / landing. |
| `/opportunities` | Opportunities table, filters, pipeline refresh controls. |
| `/opportunities/[symbol]/[timeframe]` | Series detail (snapshot, candle chart, context/pattern history). |
| `/backtest` | Backtest summary UI. |
| `/diagnostica` | Diagnostics / aggregates. |

## How to run with Docker

From the **repository root**:

```bash
cp .env.example .env   # then edit .env
docker compose up --build
```

- **Postgres**: port `POSTGRES_PORT` (default `5432`).
- **Backend**: `http://localhost:${BACKEND_PORT:-8000}`.
- **Frontend**: `http://localhost:${FRONTEND_PORT:-3000}`.

`depends_on` waits for the Postgres container to be healthy; the frontend does not wait for HTTP readiness of the API.

**Local backend without Docker** (Postgres on `localhost`): set `POSTGRES_HOST=localhost` and `DATABASE_URL` with host `localhost` in `.env`.

## Environment variables

Create `.env` at the repo root (Compose loads it). Names map to `backend/app/core/config.py` (Pydantic `Settings`).

| Variable | Purpose |
|----------|---------|
| `ENVIRONMENT` | e.g. `development` / `production` (affects OpenAPI docs). |
| `BACKEND_PORT` | Host port mapped to the API container. |
| `FRONTEND_PORT` | Host port mapped to the Next.js container. |
| `POSTGRES_*` | Postgres credentials and host (`postgres` in Compose, `localhost` locally). |
| `DATABASE_URL` | Full async URL (`postgresql+asyncpg://...`). Overrides built URL from `POSTGRES_*` when set. |
| `CORS_ORIGINS` | Comma-separated browser origins allowed by the API. |
| `NEXT_PUBLIC_API_URL` | Public API base URL for the frontend (browser). |
| `PIPELINE_SCHEDULER_ENABLED` | `true` to run periodic pipeline refresh in-process. |
| `PIPELINE_REFRESH_INTERVAL_SECONDS` | Interval between scheduler cycles. |
| `PIPELINE_SYMBOLS` | Comma-separated pairs; empty = defaults in code. |
| `PIPELINE_TIMEFRAMES` | Comma-separated; empty = defaults. |
| `PIPELINE_INGEST_LIMIT` / `PIPELINE_EXTRACT_LIMIT` / `PIPELINE_LOOKBACK` | Pipeline limits / context lookback. |
| `ALERT_NOTIFICATIONS_ENABLED` | Enable outbound alerts after pipeline refresh. |
| `ALERT_FRONTEND_BASE_URL` | Base URL for detail links in messages (no trailing slash). |
| `DISCORD_WEBHOOK_URL` | Optional Discord incoming webhook. |
| `TELEGRAM_BOT_TOKEN` | Optional Telegram bot token. |
| `TELEGRAM_CHAT_ID` | Optional Telegram chat ID for `sendMessage`. |

See `.env.example` for a ready-to-copy template.

## Alert notifications (Discord / Telegram)

1. Set `ALERT_NOTIFICATIONS_ENABLED=true` and at least one channel: **`DISCORD_WEBHOOK_URL`** and/or **`TELEGRAM_BOT_TOKEN`** + **`TELEGRAM_CHAT_ID`**.
2. Set **`ALERT_FRONTEND_BASE_URL`** (e.g. `http://localhost:3000`) so messages can include a link to the series detail page.
3. **When notifications fire**: after a successful `POST /api/v1/pipeline/refresh`.
   - **Targeted** body: `exchange`, `symbol`, and `timeframe` set → evaluates that series; sends according to alert rules (see code: `alert_notifications` service).
   - **Global** body: no `symbol` and no `timeframe` → loads up to N opportunities (see `GLOBAL_NOTIFY_OPPORTUNITIES_LIMIT` in code) and sends for **high-priority** (`alta_priorita`) candidates only; dedupe is per `(exchange, symbol, timeframe, context_timestamp)`.
4. Scheduler cycles use the same `execute_pipeline_refresh` hook (with exchange + symbol + timeframe per pair).

Logs are prefixed with `alert_notifications:` for troubleshooting.

## Current capabilities (MVP)

- Ingest and store candles; extract features, context, and patterns; unified **pipeline refresh** (HTTP + optional scheduler).
- **Screener** snapshots and **opportunity** ranking with signal alignment, pattern quality, timeframe policy, and **alert candidate** / **alert level** fields exposed on `/screener/opportunities`.
- **Dashboard** for opportunities, series detail with **candle chart** (recent bars) and pattern markers.
- **Alert notifications** (Discord/Telegram) with deduplication and structured logging.
- **Backtest** aggregates for pattern quality on timeframes.
- **Market identity** (`asset_type`, `provider`, optional `market_metadata` JSON) on candles and downstream rows; default path remains **crypto** via **Binance/ccxt**. See `app/core/market_identity.py` and `app/providers/` for future non-crypto providers.

## Known limitations / next steps

- No Alembic migrations; schema evolves via `create_all` at startup. **Existing databases** need manual DDL when new columns are added (e.g. `scripts/add_market_identity_columns.sql`) or a fresh Postgres volume.
- Scheduler runs inside the API process (no distributed queue).
- Alert rules and rate limits are intentionally simple; tune constants in code (e.g. `alert_candidates`, `alert_notifications`).
- Production hardening (auth, secrets, metrics, separate worker) is out of scope for this MVP milestone.

## Repository layout

| Path | Description |
|------|-------------|
| `backend/` | FastAPI app |
| `frontend/` | Next.js app |
| `docs/` | Extra documentation |
| `docker/` | Frontend Dockerfile |
| `docker-compose.yml` | Postgres + backend + frontend |
| `scripts/` | Helper SQL (e.g. additive columns for upgrades) |

## License

Specify your license here.
