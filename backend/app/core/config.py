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
    # Upload limits (bytes) for /api/ai/detect endpoints.
    MAX_IMAGE_UPLOAD_MB: int = 10
    MAX_VIDEO_UPLOAD_MB: int = 100
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
