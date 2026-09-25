"""
FastAPI application factory for MineGuardAI.

Phase 1: application shell with configuration, CORS, health check and
API documentation. Routers, database and services are added in later phases.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_exception_handlers

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
# Never log at a level that would expose credentials; keep noisy libs quiet.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "AI-powered mining safety, environmental monitoring and compliance "
            "governance platform.\n\n"
            "**Note:** AI camera detections are *simulated* in this build unless a "
            "real YOLO model is configured via `AI_DETECTOR=yolo`."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # --- CORS: restricted to configured origins (no wildcard in production) ---
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(application)

    # --- Routers are registered here as phases progress ---

    @application.get("/", tags=["Health"])
    def root() -> dict:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }

    @application.get("/health", tags=["Health"])
    @application.get(f"{settings.API_PREFIX}/health", tags=["Health"])
    def health() -> dict:
        """Liveness probe used by the frontend and deployment targets."""
        return {"status": "ok"}

    logger.info(
        "MineGuardAI backend initialised (app=%s, version=%s, detector=%s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.AI_DETECTOR,
    )
    return application


app = create_app()
