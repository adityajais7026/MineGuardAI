# MineGuardAI

AI-powered mining safety, environmental monitoring and compliance governance platform.

> **Status: Phase 1 (project structure & configuration)** — backend FastAPI shell,
> frontend React/Vite toolchain and the shared folder layout are in place. Database
> schema, APIs, compliance engine and UI arrive in subsequent phases.

## Stack

| Layer     | Technology                                                        |
|-----------|-------------------------------------------------------------------|
| Frontend  | React 18 + TypeScript, Vite, React Router, Recharts               |
| Backend   | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2                   |
| Database  | Supabase PostgreSQL (SQLite fallback for local dev)               |
| Auth      | Supabase Auth adapter / local JWT (development)                   |
| AI        | YOLO/OpenCV integration interface with simulated detector (default) |

## Layout

```
MineGuardAI/
├── backend/          FastAPI application (app/, requirements.txt, .env.example)
│   └── app/
│       ├── api/          Routers (added Phase 4+)
│       ├── core/         Config & security
│       ├── database/     Engine, session, ORM models
│       ├── models/       ORM models package
│       ├── schemas/      Pydantic request/response schemas
│       ├── services/     Business logic (compliance, risk, dashboard)
│       ├── ai/           Detector interface, simulated + YOLO implementations
│       └── utils/        Seeding, helpers
├── frontend/         React + Vite + TypeScript client
├── database/         schema.sql / seed.sql for Supabase (Phase 2)
├── ai/               yolo/ and opencv/ integration modules (Phase 10)
└── .gitignore
```

## Quick start (development)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # fill values (works with defaults for dev)
uvicorn app.main:app --reload --port 8000
```

- API docs (Swagger): http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Frontend

```bash
cd frontend
npm install
npm run dev
```

- App: http://localhost:5173 (dev server proxies `/api` and `/health` to :8000)

## Environment variables

See `backend/.env.example` and `frontend/.env.example`. Key variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Supabase Postgres connection string; unset → local SQLite dev file |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_KEY` | Supabase project credentials (service key: backend only) |
| `AUTH_PROVIDER` | `local` (dev JWT) or `supabase` (verify Supabase tokens) |
| `JWT_SECRET_KEY` | Signing secret for local JWTs — change in production |
| `AI_DETECTOR` | `simulated` (default) or `yolo` (real model) |
| `EXTERNAL_INGESTION_PROVIDER` | `simulated` until a real government endpoint + key exists |

## Honesty notes

- Camera/AI detections are **simulated** unless `AI_DETECTOR=yolo` with a real model
  file — the UI will label simulated events as such.
- No government data source is connected; the ingestion layer is a pluggable
  interface that currently returns simulated readings.
- Risk scores are a project-level heuristic, **not** a scientifically validated model.
