"""Environment-driven settings for the local Phase 1 worker.

Everything is opt-in via env vars: the bearer token is required and must be a
random secret stored only in the environment (never in source or git).
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class WorkerSettings:
    """Simple env-backed config; no MineGuardAI coupling."""

    def __init__(self) -> None:
        self.token: str | None = os.environ.get("AI_WORKER_TOKEN") or None
        self.model_path: str = (
            os.environ.get("AI_WORKER_MODEL_PATH")
            or str(REPO_ROOT / "ai" / "yolo" / "models" / "vyra_yolov8m_ppe.pt")
        )
        self.max_image_mb: float = float(os.environ.get("AI_WORKER_MAX_IMAGE_MB", "10"))
        self.host: str = os.environ.get("AI_WORKER_HOST", "127.0.0.1")
        self.port: int = int(os.environ.get("AI_WORKER_PORT", "8081"))
        # query param default mirrors backend YOLO_IMGSZ/confidence settings
        self.default_confidence: float = 0.35
        self.default_imgsz: int = 640
        self.request_timeout_secs: int = int(os.environ.get("AI_WORKER_TIMEOUT_SECS", "60"))
        self.return_annotated: bool = not ("AI_WORKER_UNANNOTATED" in os.environ)


settings = WorkerSettings()
