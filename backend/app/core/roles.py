"""
Role-based access control (Phase 11).

Permission model: read access for all authenticated users; write access by
role. `admin` always has access. The map below is the single source of truth.

Roles (existing users.role values, no schema change):
    admin                 — full management incl. users
    mine_manager          — mines, inspections, incidents, corrective actions
    safety_officer        — alerts, incidents, inspections, actions, camera events
    environmental_officer — environment, compliance rules, alerts, actions
"""
from typing import Annotated

from fastapi import Depends

from app.core.security import CurrentUser, RoleChecker, require_roles
from app.database.models import User

# Central permission map: endpoint-area -> roles allowed to write.
WRITE_ROLES: dict[str, set[str]] = {
    "users": {"admin"},
    "mines": {"mine_manager"},
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
}


def write_access(area: str) -> RoleChecker:
    """Dependency factory enforcing the WRITE_ROLES map for an area."""
    return require_roles(*WRITE_ROLES[area])


def require_write(area: str):
    """Annotated dependency: returns the current user if they may write in `area`."""
    checker = write_access(area)

    def _dep(user: CurrentUser) -> User:
        return checker(user)

    return Annotated[User, Depends(_dep)]
