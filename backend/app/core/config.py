"""
MineGuardAI backend configuration.

All configuration comes from environment variables (or a local `.env` file).
NEVER hardcode secrets in source control. See `backend/.env.example`.
"""
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    APP_NAME: str = "MineGuardAI API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api"

    # --- CORS (comma-separated origins) ---
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # --- Database ---
    # Supabase Postgres connection string, e.g.
    #   postgresql://postgres:<PASSWORD>@db.<project-ref>.supabase.co:5432/postgres
    # Falls back to a local SQLite file for development only when unset.
    DATABASE_URL: str = "sqlite:///./mineguardai.dev.db"

    # --- Supabase (project URL + keys; used for Auth adapter & storage) ---
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # --- Auth / JWT ---
    # When True the backend issues its own JWTs (local dev without Supabase).
    # When Supabase credentials are configured, Supabase-issued JWTs are verified.
    AUTH_PROVIDER: str = "local"  # "local" | "supabase"
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # --- MSG91 OTP Widget (server-side only; NEVER exposed to the frontend) ---
    # MSG91_AUTHKEY comes from .env and is verified present.
    MSG91_AUTHKEY: str = ""
    # The OTP Widget id (MSG91 panel -> OTP -> Widgets). The widget's own
    # default SMS template/sender configuration delivers the OTP — no custom
    # DLT template is required.
    MSG91_WIDGET_ID: str = ""
    MSG91_BASE_URL: str = "https://control.msg91.com"
    MSG91_OTP_LENGTH: int = 6
    MSG91_OTP_EXPIRY_MINUTES: int = 10
    MSG91_OTP_MAX_ATTEMPTS: int = 5
    MSG91_OTP_RESEND_COOLDOWN_SECONDS: int = 60
    MSG91_SEND_TIMEOUT_SECONDS: int = 10
    # Dev/test helper (below) is the only code path that consults a fixed
    # code; see services/msg91.py TEST_OTP_CODE.
    # Test helper (CI/dev): when True, /api/auth/... endpoints skip the real
    # SMS call entirely. Never enable in production. Actual OTPs are always
    # bcrypt-hashed at rest and never logged.
    OTP_SMS_DISABLED: bool = False

    # --- Seeded admin (created by the seed command) ---
    SEED_ADMIN_EMAIL: str = "admin@mineguard.ai"
    SEED_ADMIN_PASSWORD: str = "Admin@123"

    # --- AI / Computer vision ---
    # "simulated" -> labelled simulated events (fallback/testing mode).
    # "yolo"      -> real Ultralytics YOLO inference for uploaded media.
    AI_DETECTOR: str = "simulated"
    YOLO_MODEL_PATH: str = "ai/yolo/models/yolo11n.pt"
    # Auto-download the pretrained model when missing (explicit opt-in).
    YOLO_AUTO_DOWNLOAD: bool = False
    # Default inference settings (per-request overrides supported).
    YOLO_CONFIDENCE: float = 0.35
    YOLO_IMGSZ: int = 640
    # Video frame sampling: process every Nth frame.
    YOLO_FRAME_STRIDE: int = 5
    # Safety rule: persons detected in one frame/scene before a crowd alert.
    YOLO_CROWD_THRESHOLD: int = 4
    # --- PPE two-stage thresholds (benchmark-validated, Part 4/5) -------------
    # CAPTURE threshold: what the model may report at all (low -> candidate
    # detections become visible). Defaults to YOLO_CONFIDENCE (current behaviour).
    YOLO_CAPTURE_CONFIDENCE: float | None = None
    # VIOLATION (alert) thresholds: a NO-* detection only becomes a violation
    # event + alert when its confidence passes this bar. Defaults to
    # YOLO_CONFIDENCE (current behaviour). Separate values per class are
    # supported via PPE_THRESHOLDS_JSON; keys are lowercased model classes
    # (e.g. "no-hardhat").
    PPE_VIOLATION_CONFIDENCE: float | None = None
    PPE_THRESHOLDS_JSON: str | None = None
    # --- Live multi-person anchor strategy (OPT-IN) -------------------------
    # "default"      -> exactly the pre-anchor behaviour (Vyra only, global
    #                   event cooldown, synchronous evidence upload).
    # "person_anchor"-> live endpoint adds a COCO yolo11n PERSON anchor with
    #                   ByteTrack IDs and per-person PPE attribution. PPE still
    #                   comes ONLY from the configured Vyra model; policy code,
    #                   thresholds, DB schema and upload detection are unchanged.
    AI_DETECTOR_STRATEGY: str = "default"
    # Anchor weights (COCO person detector) used only by the anchor strategy.
    PERSON_ANCHOR_MODEL_PATH: str = "tmp_diag/alt_models/yolo11n.pt"
    # OPT-IN comparison switch: when set, the person_anchor strategy uses this
    # model for PPE instead of the production one (benchmarking only — e.g.
    # Hansung-PPE). Empty string = production Vyra (never changes by default).
    PERSON_ANCHOR_PPE_MODEL_PATH: str = ""
    # ADDITIVE per-person crop PPE inference (off by default; enable after the
    # live diagnosis showed full-frame letterboxing hides head-level evidence).
    # The hi-res crop pass costs ~0.8s/person on CPU, so by default it runs
    # every 3rd frame of a session for the 2 largest (nearest) persons; the
    # full-frame pass still runs on EVERY frame.
    PERSON_ANCHOR_CROP_PPE: bool = False
    PERSON_ANCHOR_CROP_IMGSZ: int = 1280
    PERSON_ANCHOR_CROP_PADDING: float = 0.12
    PERSON_ANCHOR_CROP_EVERY_N: int = 3
    PERSON_ANCHOR_CROP_MAX_PERSONS: int = 2
    # Temporal confirmation for live alerts (req. 11): alert only when the
    # same (camera, person, event_type) violation is seen in N of the last M
    # frames. N<=1 disables (single-frame alerting, ~0.6s alert latency kept).
    LIVE_TEMPORAL_CONFIRM_N: int = 1
    LIVE_TEMPORAL_CONFIRM_M: int = 3
    PERSON_ANCHOR_CONF: float = 0.25
    # Upload limits (bytes) for /api/ai/detect endpoints.
    MAX_IMAGE_UPLOAD_MB: int = 10
    MAX_VIDEO_UPLOAD_MB: int = 100
    # Live-webcam frame endpoint: per-frame upload cap (single JPEG, base64)
    # and alert dedupe window (a live feed re-detecting the same violation
    # every second must not spam the Alerts page; matches the 60-minute
    # camera-pipeline dedupe used by uploads).
    MAX_FRAME_UPLOAD_MB: int = 5
    LIVE_EVENT_COOLDOWN_SECONDS: int = 60
    CAMERA_SNAPSHOT_DIR: str = "snapshots"

    # --- Supabase Storage (media uploads; requires SUPABASE_URL + key) ---
    SUPABASE_MEDIA_BUCKET: str = "mineguard-media"
    # When False (default) the service accepts a pluggable storage backend and
    # returns local dev URLs instead of failing without credentials.
    STORAGE_PROVIDER: str = "supabase"  # "supabase" | "local"

    # --- Data ingestion (external / government sources) ---
    # Leave empty in development: the ingestion layer then uses the
    # simulated external source. No government API is connected by default.
    EXTERNAL_INGESTION_PROVIDER: str = "simulated"
    EXTERNAL_INGESTION_API_URL: str = ""
    EXTERNAL_INGESTION_API_KEY: str = ""

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _split_origins(cls, value: str) -> List[str]:
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
