"""Mine-level data isolation, shared by every v1 router (legacy + governance).

Scope rules (matching app.services.mine_access and governance._ensure_mine_scope):
    admin                  -> all mines
    mine_manager           -> mines where mines.manager_id == user.id
    safety_officer /       -> user.permitted_mine_ids only
    environmental_officer

The backend is authoritative: client-supplied mine_id values (query param,
request body, or resource id) are never trusted; everything funnels through
these helpers.
"""
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.database.models import Mine, User


def visible_mine_ids(db: Session, user: User) -> list[str] | None:
    """Mine IDs the user may see, or None for admins (all mines)."""
    if user.role == "admin":
        return None
    if user.role == "mine_manager":
        return list(db.scalars(select(Mine.id).where(Mine.manager_id == user.id)).all())
    return list(user.permitted_mine_ids or [])


# Sentinel that yields an empty IN clause when a user has no permitted mines,
# so an empty scope excludes everything instead of matching nothing IN () error.
_NO_MINES = "__no_mine_access__"


def scope_column(column, ids: Sequence[str] | None):
    """Apply a mine IN-scope filter to an SQLAlchemy query column.

    ids None (admin) -> always-true predicate. Returning the bare column
    instead would emit ``WHERE ... AND alerts.mine_id`` — a non-boolean
    string column — which PostgreSQL rejects at runtime (SQLite tolerated
    it, which hid the bug from the test suite).
    """
    if ids is None:
        return true()
    ids = [i for i in ids if i] or [_NO_MINES]
    return column.in_(ids)


def ensure_mine_in_scope(db: Session, user: User, mine_id: str | None) -> None:
    """403 unless the user's scope covers `mine_id` (no-op for admins/None)."""
    if mine_id is None or user.role == "admin":
        return
    ids = visible_mine_ids(db, user) or []
    if mine_id not in ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Restricted to mines assigned to you.",
        )
