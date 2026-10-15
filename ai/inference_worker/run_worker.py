"""Run the local Phase 1 Vyra inference worker (backend venv, one command).

    cd backend
    .venv/Scripts/python.exe ../ai/inference_worker/run_worker.py
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_DIR = Path(__file__).resolve().parent
# Worker packages are `worker.*` — the repo also has a backend/app package, so a
# distinct name keeps the two processes unambiguous no matter the cwd.
sys.path.insert(0, str(WORKER_DIR))

os.environ.setdefault(
    "AI_WORKER_MODEL_PATH",
    str(REPO_ROOT / "ai" / "yolo" / "models" / "vyra_yolov8m_ppe.pt"),
)

import uvicorn  # noqa: E402

from worker.settings import settings  # noqa: E402

if __name__ == "__main__":
    if not os.environ.get("AI_WORKER_TOKEN"):
        print("ERROR: AI_WORKER_TOKEN env var is required (random secret, not in git).")
        raise SystemExit(2)
    uvicorn.run(
        "worker.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
        timeout_keep_alive=30,
    )
