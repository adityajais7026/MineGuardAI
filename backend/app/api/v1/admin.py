"""Platform-administration API (read-mostly).

These endpoints back the redesigned Administrator area:

    GET /admin/overview       platform counters + recent administrative activity
    GET /admin/system-health  live health of API, DB, AI worker, storage, integrations
    GET /admin/roles          role/permission matrix + per-role user counts
    GET /admin/config         effective (read-only) platform configuration

Rules honoured here:
  * every route is administrator-only, enforced by the backend (not the UI);
  * every number comes from the database — nothing is invented;
  * services that are absent report NOT CONFIGURED / UNKNOWN instead of a fake
    "healthy" status;
  * no secret (password, key, token, connection string) is ever returned.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.roles import PLATFORM_ADMIN_AREAS, WRITE_ROLES
from app.core.security import require_roles
from app.database.models import AuditEvent, Mine, RoleInvitation, SensorDevice, User
from app.database.session import get_db

router = APIRouter(
    prefix="/admin",
    tags=["Platform Administration"],
    dependencies=[Depends(require_roles("admin"))],
)

DbSession = Annotated[Session, Depends(get_db)]

ROLE_LABELS: dict[str, str] = {
    "admin": "Platform Administrator",
    "environmental_officer": "Government Officer",
    "mine_manager": "Mine Manager",
    "safety_officer": "Safety Officer",
}

# A sensor is reported ONLINE only when it is active AND has communicated
# within this window; otherwise it is OFFLINE / NEVER CONNECTED. This is a
# derived connectivity view of last_seen_at, never a fabricated signal.
DEVICE_ONLINE_WINDOW_MINUTES = 15


def _count(db: Session, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    for cond in conditions:
        stmt = stmt.where(cond)
    return int(db.scalar(stmt) or 0)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _runtime_environment() -> str:
    """Describe the environment the backend is actually running in.

    DEBUG alone is unreliable (it defaults to False even for a local SQLite
    dev run), so the database engine decides: a SQLite file is a local
    development datastore, never "production".
    """
    if settings.is_sqlite:
        return "development (local SQLite)"
    if settings.DEBUG:
        return "development (debug enabled)"
    return "production"


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get("/overview")
def overview(db: DbSession) -> dict:
    """Platform-admin counters. All values are computed from live tables."""
    now = datetime.now(timezone.utc)

    mines_total = _count(db, Mine)
    mines_active = _count(db, Mine, Mine.status == "operational")
    mines_by_status = {
        status: _count(db, Mine, Mine.status == status)
        for status in ("operational", "maintenance", "suspended", "closed")
    }

    users_total = _count(db, User)
    users_active = _count(db, User, User.is_active.is_(True))
    roles = db.execute(select(User.role, func.count()).group_by(User.role)).all()
    users_by_role = {str(role): int(count) for role, count in roles}

    devices_total = _count(db, SensorDevice)
    devices_active = _count(db, SensorDevice, SensorDevice.is_active.is_(True))
    devices_never_seen = _count(db, SensorDevice, SensorDevice.last_seen_at.is_(None))
    online_since = now - timedelta(minutes=DEVICE_ONLINE_WINDOW_MINUTES)
    devices_online = _count(
        db,
        SensorDevice,
        SensorDevice.is_active.is_(True),
        SensorDevice.last_seen_at.is_not(None),
        SensorDevice.last_seen_at >= online_since,
    )

    invitations_pending = _count(
        db,
        RoleInvitation,
        RoleInvitation.is_used.is_(False),
        RoleInvitation.deleted_at.is_(None),
        RoleInvitation.expires_at > now,
    )

    recent = db.execute(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(8)
    ).scalars().all()

    return {
        "mines": {
            "total": mines_total,
            "active": mines_active,
            "inactive": mines_total - mines_active,
            "by_status": mines_by_status,
        },
        "users": {
            "total": users_total,
            "active": users_active,
            "inactive": users_total - users_active,
            "by_role": users_by_role,
        },
        "devices": {
            "total": devices_total,
            "active": devices_active,
            "inactive": devices_total - devices_active,
            "online": devices_online,
            "never_connected": devices_never_seen,
            "online_window_minutes": DEVICE_ONLINE_WINDOW_MINUTES,
        },
        "invitations": {"pending": invitations_pending},
        "audit": {"entries": _count(db, AuditEvent)},
        "recent_activity": [
            {
                "id": event.id,
                "seq": event.seq,
                "created_at": event.created_at,
                "actor_role": event.actor_role,
                "action": event.action,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "mine_id": event.mine_id,
            }
            for event in recent
        ],
        "generated_at": now,
    }


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------


def _probe_ai_worker() -> dict:
    """Probe the configured AI inference worker. Never returns its URL/token."""
    if not settings.AI_SERVICE_URL:
        return {
            "status": "NOT CONFIGURED",
            "configured": False,
            "detail": "AI_SERVICE_URL is not set; no inference worker is registered.",
        }
    import httpx

    target = settings.AI_SERVICE_URL.rstrip("/") + "/health"
    try:
        response = httpx.get(target, timeout=3.0)
        if response.status_code < 400:
            return {"status": "AVAILABLE", "configured": True,
                    "detail": f"Worker health probe returned HTTP {response.status_code}."}
        return {"status": "UNAVAILABLE", "configured": True,
                "detail": f"Worker health probe returned HTTP {response.status_code}."}
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        return {"status": "UNAVAILABLE", "configured": True,
                "detail": f"Worker health probe failed ({exc.__class__.__name__})."}


@router.get("/system-health")
def system_health(db: DbSession) -> dict:
    """Live health of each platform dependency. Unknown stays UNKNOWN."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    db_status: dict
    try:
        db.execute(text("SELECT 1"))
        db_status = {
            "status": "CONNECTED",
            "engine": "sqlite" if settings.is_sqlite else "postgresql",
            "detail": "SELECT 1 succeeded.",
        }
    except SQLAlchemyError as exc:
        db_status = {
            "status": "UNAVAILABLE",
            "engine": "sqlite" if settings.is_sqlite else "postgresql",
            "detail": f"Database probe failed ({exc.__class__.__name__}).",
        }

    storage_configured = settings.STORAGE_PROVIDER == "local" or bool(
        settings.SUPABASE_URL and (settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_ANON_KEY)
    )

    return {
        "api": {
            "status": "OPERATIONAL",
            "version": settings.APP_VERSION,
            "detail": "Serving this response.",
        },
        "database": db_status,
        "ai_worker": _probe_ai_worker(),
        "storage": {
            "status": "CONFIGURED" if storage_configured else "NOT CONFIGURED",
            "provider": settings.STORAGE_PROVIDER,
            "detail": (
                f"Provider '{settings.STORAGE_PROVIDER}' is configured."
                if storage_configured
                else f"Provider '{settings.STORAGE_PROVIDER}' has no credentials; uploads fall back to local development URLs."
            ),
        },
        "integrations": {
            "sms_otp": {
                "status": "CONFIGURED" if (settings.MSG91_AUTHKEY and settings.MSG91_WIDGET_ID) else "NOT CONFIGURED",
                "provider": "MSG91",
            },
            "ocr": {"status": settings.OCR_PROVIDER.upper() if settings.OCR_PROVIDER != "none" else "NOT CONFIGURED",
                    "provider": settings.OCR_PROVIDER},
            "voice": {"status": settings.VOICE_PROVIDER.upper() if settings.VOICE_PROVIDER != "none" else "NOT CONFIGURED",
                      "provider": settings.VOICE_PROVIDER},
            "translation": {"status": settings.TRANSLATION_PROVIDER.upper() if settings.TRANSLATION_PROVIDER != "none" else "NOT CONFIGURED",
                            "provider": settings.TRANSLATION_PROVIDER},
            "external_ingestion": {"status": settings.EXTERNAL_INGESTION_PROVIDER.upper()
                                   if settings.EXTERNAL_INGESTION_PROVIDER != "simulated" else "NOT CONFIGURED",
                                   "provider": settings.EXTERNAL_INGESTION_PROVIDER},
        },
        "error_log": {
            "status": "NOT CONFIGURED",
            "detail": "No persistent system error-log store is configured; backend errors are written to the service log only.",
        },
        "checked_at": datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# Roles & permissions
# ---------------------------------------------------------------------------


@router.get("/roles")
def role_permissions(db: DbSession) -> dict:
    """The authoritative write-permission map plus current role assignment."""
    counts = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    mine_access = {
        "admin": "All registered mines (platform-wide).",
        "mine_manager": "Only mines where the user is registered as manager (mines.manager_id).",
        "safety_officer": "Only mines in the user's permitted mine list.",
        "environmental_officer": "Only mines in the user's permitted mine list.",
    }
    return {
        "roles": [
            {
                "role": role,
                "label": ROLE_LABELS.get(role, role.replace("_", " ").title()),
                "users": int(counts.get(role, 0)),
                "mine_access": mine_access.get(role, ""),
                "write_areas": sorted(area for area, allowed in WRITE_ROLES.items() if role in allowed),
            }
            for role in ROLE_LABELS
        ],
        "write_matrix": {area: sorted(allowed) for area, allowed in sorted(WRITE_ROLES.items())},
        "notes": [
            "Administrator write access is limited to platform administration: "
            + ", ".join(sorted(PLATFORM_ADMIN_AREAS))
            + ". There is no implicit superuser bypass (RoleChecker).",
            "Mine-safety writes — inspections, alerts, incidents, corrective actions, emergency records and telemetry readings — are refused for administrators with HTTP 403.",
            "Read access is available to every authenticated user, restricted per mine by the backend.",
        ],
    }


# ---------------------------------------------------------------------------
# Effective configuration (read-only)
# ---------------------------------------------------------------------------


@router.get("/config")
def effective_config() -> dict:
    """Effective platform configuration.

    Read-only view of the values the backend is actually running with. Editing
    these requires environment/deployment changes and a settings store that
    does not exist yet, so the API never pretends they are editable here.
    """
    return {
        "editable": False,
        "note": "Settings are supplied by the deployment environment; change them there and redeploy.",
        "platform": {
            "app_name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "api_prefix": settings.API_PREFIX,
            "debug": settings.DEBUG,
            "environment": _runtime_environment(),
            "database_engine": "sqlite" if settings.is_sqlite else "postgresql",
        },
        "registration": {
            "mode": "invitation_code_only",
            "invitation_expiry_hours": settings.INVITATION_EXPIRY_HOURS,
            "public_signup": False,
            "invitable_roles": ["admin", "environmental_officer", "mine_manager", "safety_officer"],
        },
        "session_security": {
            "auth_provider": settings.AUTH_PROVIDER,
            "access_token_expire_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
            "jwt_algorithm": settings.JWT_ALGORITHM,
            "sms_otp_enabled": bool(settings.MSG91_AUTHKEY and settings.MSG91_WIDGET_ID),
            "otp_expiry_minutes": settings.MSG91_OTP_EXPIRY_MINUTES,
            "otp_max_attempts": settings.MSG91_OTP_MAX_ATTEMPTS,
            "otp_resend_cooldown_seconds": settings.MSG91_OTP_RESEND_COOLDOWN_SECONDS,
            "otp_sms_disabled": settings.OTP_SMS_DISABLED,
            "cors_origin_count": len(settings.CORS_ORIGINS),
        },
        "platform_preferences": {
            "ai_detector": settings.AI_DETECTOR,
            "ai_worker_configured": bool(settings.AI_SERVICE_URL),
            "live_event_cooldown_seconds": settings.LIVE_EVENT_COOLDOWN_SECONDS,
            "storage_provider": settings.STORAGE_PROVIDER,
            "max_image_upload_mb": settings.MAX_IMAGE_UPLOAD_MB,
            "max_video_upload_mb": settings.MAX_VIDEO_UPLOAD_MB,
        },
    }
