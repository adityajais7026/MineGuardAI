"""Incidents router."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import Incident, User
from app.database.session import get_db
from app.schemas import IncidentCreate, IncidentResponse, IncidentUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/incidents", tags=["Incidents"], dependencies=[Depends(get_current_user)])
service = CrudService(Incident, default_order="occurred_at")

DbSession = Annotated[Session, Depends(get_db)]


def _validate_reporter(db: Session, reported_by_id: str | None) -> None:
    if reported_by_id is not None and db.get(User, reported_by_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown reported_by_id '{reported_by_id}'.")


@router.get("", response_model=PaginatedResponse[IncidentResponse])
def list_incidents(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    mine_id: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    incident_status: str | None = Query(default=None, alias="status"),
    sort: str = Query(default="occurred_at"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={
            "mine_id": mine_id,
            "category": category,
            "severity": severity,
            "status": incident_status,
        },
        sort=sort,
        order=order,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("incidents"))])
def create_incident(db: DbSession, payload: IncidentCreate):
    _validate_reporter(db, payload.reported_by_id)
    data = payload.model_dump()
    if data.get("occurred_at") is None:
        data["occurred_at"] = datetime.now(timezone.utc)
    incident = Incident(**data)
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(db: DbSession, incident_id: str):
    return service.get(db, incident_id)


@router.patch("/{incident_id}", response_model=IncidentResponse,
               dependencies=[Depends(write_access("incidents"))])
def update_incident(db: DbSession, incident_id: str, payload: IncidentUpdate):
    incident = service.get(db, incident_id)
    data = payload.model_dump(exclude_unset=True)
    if "reported_by_id" in data:
        _validate_reporter(db, data["reported_by_id"])

    new_status = data.get("status")
    if new_status in {"resolved", "closed"} and incident.status not in {"resolved", "closed"}:
        data.setdefault("resolved_at", datetime.now(timezone.utc))
    if new_status in {"open", "investigating", "action_required"}:
        data["resolved_at"] = None  # reopening clears the resolution timestamp

    for field, value in data.items():
        setattr(incident, field, value)
    db.commit()
    db.refresh(incident)
    return incident


@router.delete("/{incident_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("incidents"))])
def delete_incident(db: DbSession, incident_id: str):
    service.delete(db, incident_id)
