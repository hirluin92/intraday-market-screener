# intraday-market-screener

Full-stack scaffold for an intraday market screening application.

## Repository layout

| Path | Description |
|------|-------------|
| `backend/` | FastAPI application |
| `frontend/` | Next.js application (App Router) |
| `docs/` | Project documentation |
| `scripts/` | Automation and helper scripts |
| `docker/` | Container images (frontend; backend image lives in `backend/Dockerfile`) |

## Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16+ (local dev) or Docker Compose (stack with Postgres)
- Docker and Docker Compose (optional, for containerized runs)

## Quick start (local)

### Backend

Copy `.env.example` to `.env` at the repository root. For local runs (not Docker), point `DATABASE_URL` / `POSTGRES_HOST` at `localhost`. Start PostgreSQL, then:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/api/v1/health` (returns `503` if the database is unreachable).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Environment

- **`.env.example`** è solo un modello: non viene letto automaticamente da Docker Compose.
- Devi **creare un file `.env`** nella root del repository (ad esempio `copy .env.example .env` su Windows, oppure copia manuale) e adattare i valori.
- **`docker-compose.yml`** usa `env_file: .env`: senza `.env` reale le variabili (es. credenziali Postgres) non sono disponibili come previsto.
- **Sviluppo locale** (backend sulla macchina, Postgres in ascolto su localhost): imposta `POSTGRES_HOST=localhost` e `DATABASE_URL` con host `localhost` invece di `postgres`.
- **Docker Compose**: l’host del database per il backend deve essere il nome del servizio **`postgres`** (come in `.env.example`).

## Docker Compose

From the repository root:

```bash
docker compose up --build
```

Services: `postgres` (persistent volume), `backend`, `frontend`. The backend waits until Postgres is healthy before starting. The frontend starts after the backend container starts (`depends_on` does **not** wait for the API to be “ready”, only for the container to be created).

## License

Specify your license here.
