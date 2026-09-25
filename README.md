# MineGuardAI

AI-ready mining safety, environmental monitoring and compliance governance platform.

> **⚠ SIMULATED DATA NOTICE**
> All mines, sensors, camera events and alerts in this repository are **SIMULATED DEMO DATA**.
> Nothing here represents real mines, real sensors or government data. Camera "detections" come
> from a simulated event generator — no YOLO model is executed unless you explicitly enable and
> supply one (see [AI / YOLO integration](#ai--yolo-integration)). Risk scores are a project
> heuristic, not a scientifically validated safety model, and contain no machine learning.

## Purpose

MineGuardAI demonstrates the full governance loop for mining operations:

environmental readings → compliance-rule evaluation → alerts → incidents →
inspections → corrective actions → transparent risk classification → dashboard analytics.

## Architecture

```
React (Vite, TS)  ──HTTP/JSON──▶  FastAPI  ──SQLAlchemy 2──▶  PostgreSQL
     │                              │
     └── charts only                ├── compliance engine (Phase 5)
                                    ├── risk engine (Phase 6)
                                    ├── camera pipeline (Phase 10)
                                    └── JWT auth + RBAC (Phase 11)
```

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, React Router 6, Recharts |
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 |
| Database | Supabase PostgreSQL (production) / SQLite dev fallback |
| Auth | Backend-issued JWT (bcrypt hashes) — Supabase Auth adapter ready |
| AI | Detector abstraction: SimulatedDetector (default) + optional YOLODetector |

## Folder structure

```
MineGuardAI/
├── backend/
│   ├── app/
│   │   ├── api/v1/        # routers (auth, mines, compliance, risk, dashboard, ai, ...)
│   │   ├── core/          # config, security, roles, error handlers
│   │   ├── database/      # engine/session + ORM models (source of truth: schema.sql)
│   │   ├── schemas/       # Pydantic request/response models
│   │   ├── services/      # compliance engine, risk engine, dashboard, camera pipeline, CRUD
│   │   ├── ai/            # detector abstraction + simulated/YOLO implementations
│   │   └── utils/         # seed_demo (dev seeder)
│   ├── scripts/           # smoke tests + schema consistency checker
│   ├── tests/             # pytest suite (71 tests)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/           # typed API client (client.ts, endpoints.ts, types.ts)
│       ├── components/    # Layout, RequireAuth, ui primitives
│       ├── context/       # AuthContext
│       ├── hooks/         # useApiResource
│       └── pages/         # 13 pages (dashboard, mines, alerts, ...)
├── database/
│   ├── schema.sql         # Supabase PostgreSQL DDL (verified 1:1 with ORM)
│   └── seed.sql           # clearly-labelled simulated seed data
├── ai/                    # yolo/ + opencv/ integration folders (weights gitignored)
├── docker-compose.yml     # full local stack
├── Dockerfile.*           # backend + frontend images
└── README.md
```

## Quick start (local development)

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows Git Bash; Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # optional for dev; defaults are fine
python -m app.utils.seed_demo     # creates tables + simulated demo data
uvicorn app.main:app --reload --port 8000
```

- Swagger UI: http://localhost:8000/docs (login via the Authorize button:
  `admin@mineguard.ai` / `Admin@123`)
- Health: `GET /health` and `GET /api/health/db` (reports `sqlite` or `postgresql`)

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173 (proxies /api -> :8000)
```

### 3. Demo accounts

| Email | Password | Role |
|---|---|---|
| admin@mineguard.ai | Admin@123 | admin (everything, incl. Users page) |
| manager@mineguard.ai | Manager@123 | mine_manager |
| safety@mineguard.ai | Safety@123 | safety_officer |
| env@mineguard.ai | Env@123 | environmental_officer |

## Environment variables

Copy `backend/.env.example` → `backend/.env` and `frontend/.env.example` → `frontend/.env`.
Key variables:

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres connection string. **Unset → SQLite dev file.** | `sqlite:///./mineguardai.dev.db` |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_KEY` | Supabase project credentials (service key: backend only) | empty |
| `AUTH_PROVIDER` | `local` (JWT) or `supabase` (adapter point) | `local` |
| `JWT_SECRET_KEY` | **Change in production.** Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` | insecure default |
| `CORS_ORIGINS` | Comma-separated allowed origins | localhost:5173,3000 |
| `AI_DETECTOR` | `simulated` or `yolo` | `simulated` |
| `YOLO_MODEL_PATH` | Weights file for YOLO mode | `ai/yolo/models/best.pt` |
| `EXTERNAL_INGESTION_PROVIDER` | `simulated` until a real endpoint exists | `simulated` |

Never commit `.env` files; they are gitignored.

## Supabase setup (production database)

1. Create a project at supabase.com → **Project Settings → Database** → copy the
   connection string (Session mode, port 5432).
2. `backend/.env`: `DATABASE_URL=postgresql://postgres:<PASSWORD>@db.<ref>.supabase.co:5432/postgres`
3. Apply the schema: paste `database/schema.sql` into the Supabase SQL editor and run
   (or let the backend create tables via `Base.metadata.create_all` — verified identical).
4. Optional demo data: run `database/seed.sql` in the SQL editor, or `python -m app.utils.seed_demo`.
5. Restart the backend → `GET /api/health/db` must report `"database":"postgresql","connected":true`.

**Status in this repo: REQUIRES MANUAL CONFIGURATION.** No Supabase credentials exist here;
the SQLite fallback keeps local development working. PostgreSQL compatibility is verified
(schema↔ORM consistency check + pooled/TLS engine settings).

## The compliance engine (Phase 5)

`POST /api/compliance/ingest?mine_id=...&parameter=pm2_5&value=95&unit=µg/m³`

1. Stores the reading (source `simulated`/`sensor`/`external`).
2. Picks the most specific active rule (mine-specific beats global).
3. Evaluates: **VIOLATION** (condition met) / **WARNING** (≥80% of an upper-bound threshold) /
   **COMPLIANT**.
4. On VIOLATION creates an alert — severity from the rule, `source="compliance_engine"`,
   linked via `source_reading_id` — **unless** an unresolved alert for the same mine+rule
   exists within the last 6 h (duplicate suppression).

Thresholds in the seed data are illustrative demo values, not statutory limits.
`GET /api/compliance/evaluate/{mine_id}` re-evaluates recent readings (display only).

## Risk engine (Phase 6)

`GET /api/risk/mines` / `GET /api/risk/mines/{id}` — deterministic 0–100 score:

| Factor | Points |
|---|---|
| Environmental violations (7 d) | 2 each, cap 20 |
| Active alerts by severity | 8/5/2/1, cap 25 |
| Open incidents by severity | 8/5/2/1, cap 20 |
| Failed/partial inspections (30 d) | 10/5, cap 15 |
| Overdue corrective actions | 5 each, cap 15 |
| In-progress actions | 1 each, cap 5 |

Levels: 0–24 LOW · 25–49 MEDIUM · 50–74 HIGH · 75–100 CRITICAL.
The response includes per-factor breakdown and a disclaimer that this is a project
heuristic, **not** ML and **not** a validated safety model.

## AI / YOLO integration — REAL inference on uploaded media

MineGuardAI runs **real YOLO object detection** (Ultralytics) on uploaded images and videos,
alongside the original clearly-labelled simulated event generator.

### Two detection paths

| | Simulated | **Real YOLO** |
|---|---|---|
| Endpoint | `POST /api/ai/simulate-event` | `POST /api/ai/detect/image` · `POST /api/ai/detect/video` |
| Needs | nothing | model weights + `AI_DETECTOR=yolo` |
| `detection_source` | `simulated` | `yolo` |
| Alert `source` | `camera_pipeline` | `yolo` |
| UI badge | SIMULATED | YOLO |

Both store into the same `camera_events` table and flow into alerts → risk → dashboard.

### Real detection workflow

1. User uploads image/video on the Camera Events page (mine, optional restricted zone,
   confidence threshold, frame stride for video).
2. Backend validates (MIME declaration + **magic bytes**, size caps, mine/zone binding).
3. Ultralytics YOLO runs real inference (yolo11n by default; configurable via `YOLO_MODEL_PATH`).
4. Annotated image/MP4 is produced and stored (Supabase Storage private bucket when
   credentials are configured; gitignored local storage otherwise — `storage_provider`
   in every response says which).
5. `camera_events` rows are created per detected class/safety rule with bbox, confidence,
   frame number and video timestamp.
6. Safety rules over **actual detections** raise alerts (`source="yolo"`, deduplicated):
   person/vehicle bound to a restricted zone, crowd ≥ `YOLO_CROWD_THRESHOLD`.

### Honesty: object detection ≠ safety violation detection

The pretrained COCO model detects **objects**: person, car, bus, truck, motorcycle, …
It does **NOT** detect helmets, vests, PPE compliance, falls or "restricted zones" by itself.
MineGuardAI therefore:

- reports only the classes the model really predicts (never fabricates helmet/vest events from
  YOLO output),
- derives zone violations from *legitimate rules over real detections* (a detected **person**
  inside a zone flagged by the upload context),
- keeps the architecture ready for a custom-trained model: drop weights with classes like
  `person_without_helmet` into `ai/yolo/models/` and point `YOLO_MODEL_PATH` at them — the
  pipeline, storage, events and alerts all work unchanged.

### Setup

```bash
pip install -r backend/requirements.txt          # includes ultralytics + opencv
# model weights are NOT in git — download once:
curl -L -o ai/yolo/models/yolo11n.pt \
  https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt
# or set YOLO_AUTO_DOWNLOAD=true in backend/.env
```

`backend/.env`: `AI_DETECTOR=yolo` · `YOLO_MODEL_PATH=../ai/yolo/models/yolo11n.pt`

`GET /api/ai/detector` reports both backends honestly:
`{"configured":"yolo","simulated":{...available:true},"yolo":{...available:true,classes:80}}`
— with a clear `error` string when weights are missing, and 503 (never fake results) on the
detect endpoints in that state.

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest tests/ -q          # 71 tests
.venv/Scripts/python scripts/check_schema_consistency.py   # schema.sql ↔ ORM
.venv/Scripts/python scripts/smoke_test_schema.py          # constraints/FKs
# with server running:
.venv/Scripts/python scripts/api_smoke_test.py             # 52 live HTTP checks
cd ../frontend && npm run build                    # typecheck + production build
```

## Deployment

`docker-compose.yml` builds the full stack (Postgres 16, backend on :8000, frontend on :8080).
See `DEPLOYMENT.md` for target-specific guides (Render/Railway/Fly for the API, Vercel/Netlify
for the SPA, Supabase for the database) and production hardening checklist.

## Limitations & honesty statement

- Environmental readings are **simulated** — there are no physical sensor/IoT/government
  integrations.
- **YOLO detection is real** for uploaded media (verified inference, annotated output,
  storage, events, alerts) but detects only COCO classes; specialised mining-safety classes
  (helmet/vest/PPE) require a custom-trained model, which the architecture supports.
- **Supabase PostgreSQL & Storage are fully wired but not connected in this environment**
  (no credentials) — local dev runs on the SQLite fallback + gitignored local media storage,
  and every response labels its storage provider. See `.env.example` + `DEPLOYMENT.md` for
  the exact activation steps.
- No government data source is claimed or connected.
- Risk scores are heuristic project scoring, not a certified safety model.
