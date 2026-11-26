"""Corrective actions router (linked to incidents and/or inspections)."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.mine_scope import ensure_mine_in_scope, scope_column, visible_mine_ids
from app.core.roles import write_access
from app.core.security import CurrentUser, get_current_user
from app.database.models import CorrectiveAction, Incident, Inspection, User
from app.database.session import get_db
from app.schemas import CorrectiveActionCreate, CorrectiveActionResponse, CorrectiveActionUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/corrective-actions", tags=["Corrective Actions"],
                   dependencies=[Depends(get_current_user)])
service = CrudService(CorrectiveAction, default_order="due_date")

DbSession = Annotated[Session, Depends(get_db)]


def _validate_links(
    db: Session,
    *,
    incident_id: str | None,
    inspection_id: str | None,
    assigned_to_id: str | None,
) -> None:
    if assigned_to_id is not None and db.get(User, assigned_to_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown assigned_to_id '{assigned_to_id}'.")
    if incident_id is not None and db.get(Incident, incident_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown incident_id '{incident_id}'.")
    if inspection_id is not None and db.get(Inspection, inspection_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown inspection_id '{inspection_id}'.")


def _action_mine_id(action: CorrectiveAction) -> str | None:
    """A corrective action's mine comes from its incident or inspection source."""
    if action.incident_id and action.incident:
        return action.incident.mine_id
    if action.inspection_id and action.inspection:
        return action.inspection.mine_id
    return None


def _action_scope_filter(db: Session, user) :
    """Row-level scope expression: action's incident or inspection mine in scope."""
    ids = visible_mine_ids(db, user)
    if ids is None:
        return None
    return (
        CorrectiveAction.incident_id.in_(
            select(Incident.id).where(scope_column(Incident.mine_id, ids))
        )
        | CorrectiveAction.inspection_id.in_(
            select(Inspection.id).where(scope_column(Inspection.mine_id, ids))
        )
    )


@router.get("", response_model=PaginatedResponse[CorrectiveActionResponse])
def list_actions(
    db: DbSession,
    user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    incident_id: str | None = None,
    inspection_id: str | None = None,
    assigned_to_id: str | None = None,
    action_status: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    sort: str = Query(default="due_date"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={
            "incident_id": incident_id,
            "inspection_id": inspection_id,
            "assigned_to_id": assigned_to_id,
            "status": action_status,
            "priority": priority,
        },
        sort=sort,
        order=order,
        additional_filter=_action_scope_filter(db, user),
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=CorrectiveActionResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("corrective_actions"))])
def create_action(db: DbSession, payload: CorrectiveActionCreate, user: CurrentUser):
    """Create an action linked to an incident and/or inspection (at least one)."""
    if payload.incident_id is None and payload.inspection_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="corrective_actions require an incident_id or an inspection_id.",
        )
    _validate_links(
        db,
        incident_id=payload.incident_id,
        inspection_id=payload.inspection_id,
        assigned_to_id=payload.assigned_to_id,
    )
    # Mine isolation: the action's mine is derived from its source record.
    src_mine = None
    if payload.incident_id:
        src_mine = db.get(Incident, payload.incident_id).mine_id
    elif payload.inspection_id:
        src_mine = db.get(Inspection, payload.inspection_id).mine_id
    ensure_mine_in_scope(db, user, src_mine)
    action = CorrectiveAction(**payload.model_dump())
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@router.get("/{action_id}", response_model=CorrectiveActionResponse)
def get_action(db: DbSession, action_id: str, user: CurrentUser):
    action = service.get(db, action_id)
    ensure_mine_in_scope(db, user, _action_mine_id(action))
    return action


@router.patch("/{action_id}", response_model=CorrectiveActionResponse,
               dependencies=[Depends(write_access("corrective_actions"))])
def update_action(db: DbSession, action_id: str, payload: CorrectiveActionUpdate, user: CurrentUser):
    action = service.get(db, action_id)
    ensure_mine_in_scope(db, user, _action_mine_id(action))
    data = payload.model_dump(exclude_unset=True)

    if {"incident_id", "inspection_id"} & data.keys():
        _validate_links(
            db,
            incident_id=data.get("incident_id", action.incident_id),
            inspection_id=data.get("inspection_id", action.inspection_id),
            assigned_to_id=data.get("assigned_to_id", action.assigned_to_id),
        )
    elif "assigned_to_id" in data:
        _validate_links(db, incident_id=None, inspection_id=None, assigned_to_id=data["assigned_to_id"])

    new_status = data.get("status")
    if new_status == "completed":
        if data.get("completion_date") is None and action.completion_date is None:
            data["completion_date"] = datetime.now(timezone.utc)
    elif new_status in {"pending", "in_progress", "overdue"}:
        data["completion_date"] = None  # reopening clears completion

    for field, value in data.items():
        setattr(action, field, value)
    db.commit()
    db.refresh(action)
    return action


@router.delete("/{action_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("corrective_actions"))])
def delete_action(db: DbSession, action_id: str, user: CurrentUser):
    action = service.get(db, action_id)
    ensure_mine_in_scope(db, user, _action_mine_id(action))
    service.delete(db, action_id)
