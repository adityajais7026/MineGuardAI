"""
Role-based access control (Phase 11).

Permission model: read access for all authenticated users; write access by
role. The map below is the single source of truth and there is NO implicit
administrator bypass — `admin` is listed explicitly in the platform areas it
owns and is absent from the mine-safety areas it must not touch.

Roles (existing users.role values, no schema change):
    admin                 — platform administration only: users, mine registry,
                            sensor-device registry (no operational writes)
    mine_manager          — mines, inspections, incidents, corrective actions
    safety_officer        — alerts, incidents, inspections, actions, camera events
    environmental_officer — environment, compliance rules, alerts, actions
"""
from typing import Annotated

from fastapi import Depends

from app.core.security import CurrentUser, RoleChecker, require_roles
from app.database.models import User

# Central permission map: endpoint-area -> roles allowed to write.
# Platform administration areas name `admin` explicitly; operational areas do
# not, which is what keeps administrators out of daily mine-safety work.
WRITE_ROLES: dict[str, set[str]] = {
    "users": {"admin"},
    # Mine registry (create/edit/deactivate) is platform administration.
    "mines": {"admin", "mine_manager"},
    "compliance_rules": {"environmental_officer"},
    "environment": {"environmental_officer", "mine_manager", "safety_officer"},
    "compliance_engine": {"environmental_officer", "safety_officer"},
    "alerts": {"safety_officer", "environmental_officer", "mine_manager"},
    "incidents": {"safety_officer", "mine_manager"},
    "inspections": {"safety_officer", "mine_manager"},
    "corrective_actions": {"safety_officer", "environmental_officer", "mine_manager"},
    "camera_events": {"safety_officer"},
    "restricted_zones": {"safety_officer", "mine_manager"},
    "ai_simulation": {"safety_officer"},
    # --- Governance platform areas (additive; existing areas untouched) ---
    "inspection_templates": {"safety_officer", "mine_manager", "environmental_officer"},
    "compliance_requirements": {"environmental_officer", "mine_manager"},
    "geofences": {"safety_officer", "mine_manager"},
    "workers": {"safety_officer", "mine_manager"},
    "contractors": {"safety_officer", "mine_manager"},
    "emergencies": {"safety_officer", "mine_manager", "environmental_officer"},
    # Sensor-device registry (register/edit/activate) is platform
    # infrastructure the administrator owns. Telemetry *readings* are
    # operational measurements and stay with the safety/environment roles.
    "device_registry": {"admin", "safety_officer", "environmental_officer"},
    "telemetry": {"safety_officer", "environmental_officer"},
}

# Areas administrators may write to. Kept as an explicit list so the API and
# the UI can state the admin scope instead of claiming a blanket bypass.
PLATFORM_ADMIN_AREAS: frozenset[str] = frozenset(area for area, roles in WRITE_ROLES.items() if "admin" in roles)


def admin_can_write(area: str) -> bool:
    return "admin" in WRITE_ROLES.get(area, set())


def write_access(area: str) -> RoleChecker:
    """Dependency factory enforcing the WRITE_ROLES map for an area."""
    return require_roles(*WRITE_ROLES[area])


def require_write(area: str):
    """Annotated dependency: returns the current user if they may write in `area`."""
    checker = write_access(area)

    def _dep(user: CurrentUser) -> User:
        return checker(user)

    return Annotated[User, Depends(_dep)]
