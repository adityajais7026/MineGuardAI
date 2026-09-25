"""Camera events router.

Phase 4 scope: CRUD for camera events. Detection `detection_source` records
where the event came from (`simulated` until a real YOLO/OpenCV pipeline runs
in Phase 10). Alert generation from events is Phase 5+ scope.
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import CameraEvent, Mine, RestrictedZone
from app.database.session import get_db
from app.schemas import CameraEventCreate, CameraEventResponse, CameraEventUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/camera-events", tags=["Camera Events"],
                   dependencies=[Depends(get_current_user)])
service = CrudService(CameraEvent, default_order="occurred_at")

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[CameraEventResponse])
def list_events(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    mine_id: str | None = None,
    zone_id: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    event_status: str | None = Query(default=None, alias="status"),
    detection_source: str | None = None,
    sort: str = Query(default="occurred_at"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={
            "mine_id": mine_id,
            "zone_id": zone_id,
            "event_type": event_type,
            "severity": severity,
            "status": event_status,
            "detection_source": detection_source,
        },
        sort=sort,
        order=order,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=CameraEventResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("camera_events"))])
def create_event(db: DbSession, payload: CameraEventCreate):
    """Create a camera event. Zone (if given) must belong to the same mine."""
    if db.get(Mine, payload.mine_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown mine_id '{payload.mine_id}'.")
    if payload.zone_id:
        zone = db.get(RestrictedZone, payload.zone_id)
        if zone is None or zone.mine_id != payload.mine_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="zone_id does not belong to the given mine.",
            )

    event = CameraEvent(**payload.model_dump(exclude={"occurred_at"}))
    if payload.occurred_at:
        event.occurred_at = payload.occurred_at
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/{event_id}", response_model=CameraEventResponse)
def get_event(db: DbSession, event_id: str):
    return service.get(db, event_id)


@router.patch("/{event_id}", response_model=CameraEventResponse,
               dependencies=[Depends(write_access("camera_events"))])
def update_event(db: DbSession, event_id: str, payload: CameraEventUpdate):
    event = service.get(db, event_id)
    data = payload.model_dump(exclude_unset=True)
    if "zone_id" in data and data["zone_id"] is not None:
        zone = db.get(RestrictedZone, data["zone_id"])
        if zone is None or zone.mine_id != event.mine_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="zone_id does not belong to the event's mine.",
            )
    for field, value in data.items():
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("camera_events"))])
def delete_event(db: DbSession, event_id: str):
    service.delete(db, event_id)
