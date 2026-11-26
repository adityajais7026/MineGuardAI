"""Dashboard endpoints (Phase 8)."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.mine_scope import ensure_mine_in_scope, visible_mine_ids
from app.core.security import get_current_user
from app.database.models import User
from app.database.session import get_db
from app.services.dashboard import DashboardSummary, get_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["Dashboard"],
                   dependencies=[Depends(get_current_user)])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    mine_id: str | None = Query(default=None, description="Scope all counters to one mine"),
    days: int = Query(default=7, ge=1, le=90, description="Trend/compliance window in days"),
):
    """Aggregated dashboard data — computed by the backend from the database.

    Mine isolation: non-admins are always scoped to their visible mines;
    a mine_id outside the scope raises 403.
    """
    ensure_mine_in_scope(db, user, mine_id)
    scope = visible_mine_ids(db, user)
    return get_dashboard_summary(db, mine_id=mine_id, days=days, allowed_mine_ids=scope)
