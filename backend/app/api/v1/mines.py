"""Mines CRUD router."""
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    Alert,
    CameraEvent,
    EnvironmentalReading,
    Incident,
    Inspection,
    Mine,
    RestrictedZone,
)
from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.session import get_db
from app.schemas import MineCreate, MineResponse, MineUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/mines", tags=["Mines"], dependencies=[Depends(get_current_user)])
service = CrudService(Mine, default_order="created_at")

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[MineResponse])
def list_mines(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    mine_status: str | None = Query(default=None, alias="status"),
    mine_type: str | None = Query(default=None, alias="type"),
    sort: str = Query(default="created_at"),
    order: Literal["asc", "desc"] = "desc",
):
    """List mines with optional status/type filters, sorting and pagination."""
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={"status": mine_status, "mine_type": mine_type},
        sort=sort,
        order=order,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=MineResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("mines"))])
def create_mine(db: DbSession, payload: MineCreate):
    """Create a mine. Duplicate codes or unknown manager_id return HTTP 400."""
    try:
        return service.create(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create mine: duplicate code or unknown manager_id.",
        )


@router.get("/{mine_id}", response_model=MineResponse)
def get_mine(db: DbSession, mine_id: str):
    return service.get(db, mine_id)


@router.get("/{mine_id}/details", response_model=dict)
def get_mine_details(db: DbSession, mine_id: str) -> dict[str, Any]:
    """Mine plus counts of its readings/events/alerts/incidents/inspections/zones."""
    mine = service.get(db, mine_id)

    def _count(model) -> int:
        return (
            db.scalar(
                select(func.count()).select_from(model).where(model.mine_id == mine_id)
            )
            or 0
        )

    return {
        "mine": MineResponse.model_validate(mine),
        "counts": {
            "environmental_readings": _count(EnvironmentalReading),
            "camera_events": _count(CameraEvent),
            "alerts": _count(Alert),
            "incidents": _count(Incident),
            "inspections": _count(Inspection),
            "restricted_zones": _count(RestrictedZone),
        },
    }


@router.patch("/{mine_id}", response_model=MineResponse,
               dependencies=[Depends(write_access("mines"))])
def update_mine(db: DbSession, mine_id: str, payload: MineUpdate):
    try:
        return service.update(db, mine_id, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not update mine: duplicate code or unknown manager_id.",
        )


@router.put("/{mine_id}", response_model=MineResponse,
             dependencies=[Depends(write_access("mines"))])
def replace_mine(db: DbSession, mine_id: str, payload: MineCreate):
    """Full replace (PUT semantics): every field must be provided."""
    service.get(db, mine_id)  # 404 if missing
    try:
        entity = service.update(db, mine_id, payload)
        return entity
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not replace mine: duplicate code or unknown manager_id.",
        )


@router.delete("/{mine_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("mines"))])
def delete_mine(db: DbSession, mine_id: str):
    service.delete(db, mine_id)
