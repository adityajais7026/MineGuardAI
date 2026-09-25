"""
FastAPI application factory for MineGuardAI.

Phase 3/4: full application with database connectivity check and CRUD API
routers for all entities. Compliance engine, risk scoring, auth/RBAC and the
AI detector arrive in later phases.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.database.session import engine
from app.api.v1 import all_routers

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

    # --- CRUD API routers (Phase 4) ---
    for router_module in all_routers:
        application.include_router(router_module, prefix=settings.API_PREFIX)

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

    @application.get(f"{settings.API_PREFIX}/health/db", tags=["Health"])
    def health_db() -> dict:
        """Database connectivity probe (SELECT 1). Never exposes credentials."""
        from sqlalchemy.exc import SQLAlchemyError

        db_kind = "sqlite" if settings.is_sqlite else "postgresql"
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "ok", "database": db_kind, "connected": True}
        except SQLAlchemyError as exc:
            # Log details server-side; report a generic message externally.
            logger.error("Database health check failed: %s", exc.__class__.__name__)
            return {"status": "error", "database": db_kind, "connected": False}

    logger.info(
        "MineGuardAI backend initialised (app=%s, version=%s, detector=%s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.AI_DETECTOR,
    )
    return application


app = create_app()
