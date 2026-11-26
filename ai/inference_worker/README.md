# Phase 1 — Local Vyra AI inference worker (standalone)

Local FastAPI service running the EXISTING Vyra YOLOv8m PPE model outside the
Render backend. Toys to none: it imports nothing from `backend/` and touches no
database. Vyra (`ai/yolo/models/vyra_yolov8m_ppe.pt`, production model) is
loaded from disk; nothing is trained, fine-tuned, swapped or simulated.

Run (from repo root, using the backend venv which already has FastAPI +
ultralytics):

```bash
# 1. choose a random token, store it in an env var (never in source/git)
set AI_WORKER_TOKEN=<python -c "import secrets;print(secrets.token_urlsafe(32))">

# 2. start the worker  (host/port optional: 127.0.0.1:8081)
cd backend
.venv/Scripts/python.exe ../ai/inference_worker/run_worker.py

# 3. test it (sends real images, prints real detections + latency)
.venv/Scripts/python.exe ../ai/inference_worker/test_worker.py
```

Endpoints:

* `GET  /health` — `{"status", "model_loaded", "model_path", "classes"}`
  (503 if the model failed to load — never fake detections).
* `POST /detect` — bearer-token only. Body: raw JPEG/PNG bytes.
  Query `confidence` (0-1) and `imgsz`. Returns detections + annotated PNG
  when the local disk pipeline annotates (mirrors `YoloService.detect_image_bytes`).

Rejected: missing/invalid token (401/403), non-JPEG/PNG magic bytes (415),
oversized image (413), malformed/undecodable image (400). Errors return
clear messages, never invented results.

Env config (all optional except the token):

| var                     | default                              |
|-------------------------|--------------------------------------|
| AI_WORKER_TOKEN         | — required, random, never logged     |
| AI_WORKER_MODEL_PATH    | `ai/yolo/models/vyra_yolov8m_ppe.pt` |
| AI_WORKER_MAX_IMAGE_MB  | 10                                   |
| AI_WORKER_HOST          | 127.0.0.1                            |
| AI_WORKER_PORT          | 8081                                 |
| AI_WORKER_UNANNOTATED   | unset (return annotated PNG)         |

Policy: the worker contains no MineGuardAI business logic — no users, no mines,
no RBAC, no alerts, no Supabase/Postgres. It only receives image bytes and
returns what the model actually predicted.

---

# Phase 2 runbook — connecting Render to this worker (two terminals)

The worker stays bound to `127.0.0.1:8081`; a Cloudflare Tunnel exposes it
over HTTPS and the worker's bearer token stays mandatory (verified: no token
-> 401 through the tunnel).

**Terminal 1 — start the Vyra worker** (repo root, backend venv):
```bash
# token lives in the gitignored .freebuff/ai_worker_token.tok; regenerate with:
#   python -c "import secrets;print(secrets.token_urlsafe(32))" > .freebuff/ai_worker_token.tok
export AI_WORKER_TOKEN=$(cat .freebuff/ai_worker_token.tok)
cd backend && .venv/Scripts/python.exe ../ai/inference_worker/run_worker.py
# logs "Vyra loaded ... N classes", binds 127.0.0.1:8081
```

**Terminal 2 — start the HTTPS tunnel** (REPO_ROOT/.freebuff/tools/cloudflared.exe;
no signup, free):
```bash
.freebuff/tools/cloudflared.exe tunnel --url http://127.0.0.1:8081 --no-autoupdate
# prints: https://<random>.trycloudflare.com
```

Then configure the RENDER BACKEND (dashboard env, values never in git):
```
AI_SERVICE_URL=https://<the-trycloudflare-hostname-from-terminal-2>
AI_SERVICE_TOKEN=<same value as AI_WORKER_TOKEN in terminal 1>
AI_SERVICE_TIMEOUT_SECONDS=10
```

Note: the trycloudflare hostname is new on EVERY tunnel start — update
AI_SERVICE_URL in the Render dashboard after restarting the tunnel. A stable
hostname needs either a Cloudflare-managed domain (named tunnel route, free
while you own the domain) or an ngrok free static domain (needs an ngrok
account authtoken); the worker bearer token is required either way.

What stays running on the laptop during a demo: Terminal 1 (worker) and
Terminal 2 (tunnel). Everything else (browser → frontend → Render backend →
tunnel → worker) self-heals; if the tunnel/worker dies the backend answers
503 and the UI shows "AI detection unavailable" — no fake detections.
