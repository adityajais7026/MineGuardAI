# Deployment Guide

MineGuardAI ships with production-ready configuration, but **nothing in this repository
has been deployed** — the steps below must be performed by an operator with the relevant
accounts. Every secret comes from environment variables; none are committed.

> **Fast path (recommended):** for a public URL via Render.com using the
> blueprint, follow [RENDER_DEPLOY.md](RENDER_DEPLOY.md) — it wraps the same
> Dockerfiles with `render.yaml` and a step-by-step dashboard walkthrough.

## 1. Database — Supabase PostgreSQL

1. Create a Supabase project (region close to your users).
2. **Project Settings → Database → Connection string → Session mode (port 5432)**.
3. Set it in the backend environment:
   ```
   DATABASE_URL=postgresql://postgres:<PASSWORD>@db.<ref>.supabase.co:5432/postgres
   ```
4. Apply the schema: run `database/schema.sql` in the Supabase SQL editor
   (or start the backend once — `Base.metadata.create_all` builds the verified-identical schema).
5. Optional demo data: `database/seed.sql` in the SQL editor, or `python -m app.utils.seed_demo`.
6. Verify: `GET /api/health/db` → `{"database":"postgresql","connected":true}`.

### 1b. Supabase Storage — camera media bucket (YOLO uploads)

1. **Dashboard → Storage → New bucket**
   - Name: `mineguard-media` (configurable via `SUPABASE_MEDIA_BUCKET`)
   - **Public bucket: OFF** — mine camera media must stay private.
2. The backend uploads via the service-role key (server-side only) under:
   ```text
   camera/{mine_id}/images/{uuid}.jpg    original uploaded images
   camera/{mine_id}/videos/{uuid}.mp4    original uploaded videos
   camera/{mine_id}/results/{uuid}.png   YOLO-annotated images
   camera/{mine_id}/results/{uuid}.mp4   YOLO-annotated videos
   ```
3. Access: PRIVATE bucket → the backend mints **time-limited signed URLs**
   (default 1 h) per request. No public ACLs; no service key ever reaches the browser.
4. Required env: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, optional
   `SUPABASE_MEDIA_BUCKET` (default `mineguard-media`), `STORAGE_PROVIDER=supabase`.
5. No SQL policies needed for the bucket: all access flows through the backend
   (service role bypasses RLS; anon/authenticated roles get no direct storage access).
6. Without credentials the backend transparently falls back to gitignored local
   storage (`backend/snapshots/media`, served at `/media/...`) and labels every
   response `storage_provider: "local"` — uploads never fail silently or pretend.

### 1c. YOLO model weights

Weights are NOT in git. Either download once:
```bash
curl -L -o ai/yolo/models/yolo11n.pt \
  https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt
```
or set `YOLO_AUTO_DOWNLOAD=true` (explicit opt-in) and start the backend.
Then set `AI_DETECTOR=yolo` + `YOLO_MODEL_PATH` (see `backend/.env.example`).
Container images: mount weights at `ai/yolo/models/` or bake a custom layer —
never push weights to a public registry.

## 2. Backend — FastAPI

**Environment variables (required in production):**

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Supabase Postgres string (SSL enforced by the app) |
| `JWT_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` — rotate periodically |
| `CORS_ORIGINS` | Exact frontend origin(s), comma-separated. Never `*` with credentials |
| `DEBUG` | `false` |
| `AI_DETECTOR` | `simulated` (default) or `yolo` + `YOLO_MODEL_PATH` |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` | Only needed when enabling the Supabase Auth adapter / storage. Service key: backend env only, never frontend |

**Docker (any container host):**
```bash
docker build -f Dockerfile.backend -t mineguardai-api .
docker run -p 8000:8000 --env-file backend/.env mineguardai-api
```

**Free PaaS options** (Render / Railway / Fly.io): use the `Dockerfile.backend`,
set the env vars above in the dashboard, health check path `/health`.

## 3. Frontend — React/Vite

```bash
cd frontend
npm ci
npm run build          # outputs dist/
```

- **Same-origin setup (recommended):** serve `dist/` behind a reverse proxy that
  forwards `/api/*` to the backend (see `frontend/nginx.conf` for the pattern).
  `VITE_API_BASE_URL` stays empty.
- **Separate origin:** set `VITE_API_BASE_URL=https://api.example.com` at build time
  and add that origin to backend `CORS_ORIGINS`.
- Static hosts (Vercel/Netlify/Firebase): build command `npm run build`, publish `dist/`,
  SPA rewrite `/* → /index.html`.

## 4. Docker Compose (full local production-style stack)

```bash
cp backend/.env.example .env    # then set POSTGRES_PASSWORD + JWT_SECRET_KEY in it
docker compose up --build
# frontend: http://localhost:8080   API: http://localhost:8000/docs
```

## 5. Production hardening checklist

- [ ] Unique `JWT_SECRET_KEY` generated per environment; rotate on staff changes
- [ ] `DEBUG=false`, generic error responses active (already enforced by handlers)
- [ ] `CORS_ORIGINS` lists only real deployment origins
- [ ] HTTPS/TLS at the edge (Supabase enforces TLS for Postgres; the app requires it)
- [ ] Demo accounts from seed data **removed or repassworded** (`users` table)
- [ ] Supabase RLS remains enabled; backend connects via server-side credentials only
- [ ] Change the seeded admin email/password via `SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD`
- [ ] Restrict the Users admin page to real administrators (role `admin`)
- [ ] Never place `SUPABASE_SERVICE_KEY` in frontend env — it is server-only
- [ ] Database backups enabled (Supabase → Database → Backups)

## 6. What is NOT deployed / not claimed

- No live deployment exists from this repo — all URLs above are placeholders for the operator.
- Camera detections remain **simulated** unless the YOLO prerequisites in the README are met.
- No government data feeds are configured; ingestion stays `simulated` until a real,
  credentialed endpoint is provided.
