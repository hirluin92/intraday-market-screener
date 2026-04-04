# Backend (FastAPI)

Requires PostgreSQL and an async URL: `postgresql+asyncpg://user:pass@host:port/db`.

If `DATABASE_URL` is unset, it is built from `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, and `POSTGRES_DB`.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

Configure environment (see repository root `.env.example`).

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

OpenAPI docs: `http://localhost:8000/docs` when `ENVIRONMENT` is not `production`.

Health: `GET /api/v1/health` (checks DB connectivity; `503` if down).

## Docker

Build and run from the repository root (see `docker-compose.yml`) or:

```bash
docker build -t intraday-market-screener-api -f Dockerfile .
```

(from this directory)
