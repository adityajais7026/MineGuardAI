"""Alerts router with status workflow (acknowledge/resolve timestamps server-side)."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import Alert, User
from app.database.session import get_db
from app.schemas import AlertCreate, AlertResponse, AlertUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(get_current_user)])
service = CrudService(Alert, default_order="created_at")

DbSession = Annotated[Session, Depends(get_db)]


def _validate_assignee(db: Session, assigned_to_id: str | None) -> None:
    if assigned_to_id is not None and db.get(User, assigned_to_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown assigned_to_id '{assigned_to_id}'.")


@router.get("", response_model=PaginatedResponse[AlertResponse])
def list_alerts(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    mine_id: str | None = None,
    alert_type: str | None = None,
    severity: str | None = None,
    alert_status: str | None = Query(default=None, alias="status"),
    assigned_to_id: str | None = None,
    sort: str = Query(default="created_at"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={
            "mine_id": mine_id,
            "alert_type": alert_type,
            "severity": severity,
            "status": alert_status,
            "assigned_to_id": assigned_to_id,
        },
        sort=sort,
        order=order,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("alerts"))])
def create_alert(db: DbSession, payload: AlertCreate):
    _validate_assignee(db, payload.assigned_to_id)
    alert = Alert(**payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(db: DbSession, alert_id: str):
    return service.get(db, alert_id)


@router.patch("/{alert_id}", response_model=AlertResponse,
               dependencies=[Depends(write_access("alerts"))])
def update_alert(db: DbSession, alert_id: str, payload: AlertUpdate):
    """Acknowledge/assign/resolve an alert.

    Transition rules: timestamps set server-side; resolved alerts are final;
    resolution requires the alert to have been acknowledged first.
    """
    alert = service.get(db, alert_id)
    data = payload.model_dump(exclude_unset=True)

    if "assigned_to_id" in data:
        _validate_assignee(db, data["assigned_to_id"])

    new_status = data.get("status")
    if alert.status == "resolved":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resolved alerts cannot be modified.")
    if new_status == "resolved" and alert.status == "new":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alert must be acknowledged before it can be resolved.",
        )

    now = datetime.now(timezone.utc)
    if new_status == "acknowledged" and alert.acknowledged_at is None:
        alert.acknowledged_at = now
    if new_status == "resolved":
        alert.resolved_at = now
        if alert.acknowledged_at is None:
            alert.acknowledged_at = now

    for field, value in data.items():
        setattr(alert, field, value)
    db.commit()
    db.refresh(alert)
    return alert


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("alerts"))])
def delete_alert(db: DbSession, alert_id: str):
    service.delete(db, alert_id)
