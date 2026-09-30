# Public Deployment on Render.com — step-by-step operator guide

Public URL goal: one frontend link for teammates, backed by the FastAPI API and
Supabase PostgreSQL. **Vyra stays the production detector** — nothing here
changes the model, taxonomy, database, or any existing feature.

Everything is codified in [`render.yaml`](render.yaml); the steps below are
what the operator clicks/types. Time: ~20 minutes + one image build.

---

## 0. Prerequisites

- GitHub repo `adityajais7026/MineGuardAI` with the deploy branch pushed
  (`render.yaml`, `Dockerfile.backend`, `frontend/` present).
- Supabase project credentials (they already exist in `backend/.env` locally):
  `DATABASE_URL` (session mode, port **5432**), `SUPABASE_URL`,
  `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`.
- A fresh `JWT_SECRET_KEY` for the public environment:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

## 1. Vyra weights — private download link (5 min)

Weights are ~52 MB and the repo is **public**, so they must never be committed.
Render's free tier has no persistent-disk option, so the backend re-fetches the
weights into the container's ephemeral `/data/weights` on every start (~10 s on
Render's network — acceptable on free).

1. Upload `ai/yolo/models/vyra_yolov8m_ppe.pt` to **Google Drive** (or Dropbox).
2. Share → *Anyone with the link* → copy the link.
3. Convert to a **direct-download** URL (Drive):
   `https://drive.google.com/uc?export=download&id=<FILE_ID>`
   (Dropbox: change the trailing `?dl=0` to `?dl=1`).
4. Test the URL downloads the file:
   ```bash
   curl -L -o /tmp/test.pt "<YOUR_DIRECT_URL>" && ls -la /tmp/test.pt
   ```

> Alternative (no expiring links, ever): upload the weights as a **Private Git
> LFS object** or to any private object storage that yields a stable secret URL.
> The entrypoint just needs one HTTPS URL in `WEIGHTS_URL`.

## 2. Push the deploy branch (done by the agent unless git was restricted)

```bash
git checkout -b public-deploy
git add render.yaml Dockerfile.backend docker/entrypoint.sh RENDER_DEPLOY.md \
        DEPLOYMENT.md <other pending feature files>
git commit -m "Add Render.com public deployment (Vyra production)"
git push -u origin public-deploy
```

## 3. Render dashboard — create the services (~10 min)

1. Go to <https://dashboard.render.com> → sign in **with GitHub** → authorize
   Render for the `MineGuardAI` repository (All repositories or just this one).
2. **New → Blueprint**, select `adityajais7026/MineGuardAI`, branch
   `public-deploy` → Render reads `render.yaml` and shows **two services**:
   `mineguardai-api` (Docker) and `mineguardai-web` (static).
3. Before clicking *Apply*, fill the `sync: false` fields:
   - `DATABASE_URL` — the Supabase **session-mode 5432** string
   - `JWT_SECRET_KEY` — generated above
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` — from
     Supabase → Project Settings → API (service key **backend env only**)
   - `WEIGHTS_URL` — the direct link from step 1
4. Apply. The API image builds (~5–8 min, CPU-torch + ultralytics).

### 3a. Finalise the origins (two quick edits)

The frontend URL contains a random suffix on free static sites, so after the
first deploy, in Render:

1. `mineguardai-web` → copy the real URL, e.g.
   `https://mineguardai-web-xxxx.onrender.com`.
2. `mineguardai-api` → Environment → edit `CORS_ORIGINS` →
   `https://mineguardai-web-xxxx.onrender.com,http://localhost:5173` → Save
   (service redeploys automatically).
3. `mineguardai-web` → Environment → set `VITE_API_BASE_URL` to the API URL
   (`https://mineguardai-api-xxxx.onrender.com`) → Save & rebuild. (If the API
   URL is exactly `https://mineguardai-api.onrender.com`, leave it — already set.)

> Name note: with blueprints, service names usually get the plain URLs
> (`mineguardai-api.onrender.com`); if a name was taken, Render appends a
> suffix — use whatever Render shows in 3a.

## 4. What the blueprint guarantees (already wired)

- Backend listens on **0.0.0.0:$PORT** (`docker/entrypoint.sh`) — Render
  injects `PORT`.
- `healthCheckPath: /health` — public, no auth (`GET /health` → `{"status":"ok"}`).
- `AI_DETECTOR=yolo`, `AI_DETECTOR_STRATEGY=default`,
  `YOLO_MODEL_PATH=/data/weights/vyra_yolov8m_ppe.pt` → **Vyra is production**;
  custom PPE v1/v2 are not referenced anywhere in the deploy config.
- CORS restricted to the exact frontend origin (never `*`).
- Database is the existing Supabase PostgreSQL — no schema changes, no
  destructive migrations; SQLAlchemy only connects.
- All secrets live in Render's encrypted env store; nothing secret is in git,
  the image, or the frontend bundle.
- Frontend is a static SPA with `/assets/*` immutable caching and a rewrite
  route so deep links work.

## 5. Verify (the checklist from the request)

| # | Check | How |
|---|---|---|
| 13 | Health public | `curl https://mineguardai-api.onrender.com/health` |
| 14 | DB connectivity | `curl .../api/health/db` → `{"connected":true,"database":"postgresql"}` |
| 15 | Vyra live | `curl .../api/ai/status` → `detector: yolo`, model `vyra_yolov8m_ppe.pt`; then login → POST an image to `/api/ai/detect/image` → detections labelled `yolo` |
| 7/8 | Frontend wiring | Open the web URL from a phone on mobile data, login, run live webcam detection |

## 6. Free-tier realities (read once)

- **API spins down after ~15 min idle**; first request afterwards takes ~50 s.
  Teammates just refresh once. Upgrade to Starter ($7/mo) for always-on.
- **512 MB RAM.** Vyra (YOLOv8m) inference fits, but if you ever see OOM
  restarts, bump the plan — no config change needed.
- **Ephemeral disk:** the weights re-download on each deploy/restart (kept the
  entrypoint idempotent for this). Persistent disks require a paid plan; the
  blueprint keeps the disk stanza commented accordingly.
- Supabase free tier keeps the DB alive independently of Render.

## 7. Rollback / teardown

- Rollback: Render → service → *Manual Deploy* → pick an earlier deploy.
- Teardown: delete the two services. Supabase data is untouched by Render.
