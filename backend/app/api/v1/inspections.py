"""Inspections router."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import Inspection, User
from app.database.session import get_db
from app.schemas import InspectionCreate, InspectionResponse, InspectionUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/inspections", tags=["Inspections"],
                   dependencies=[Depends(get_current_user)])
service = CrudService(Inspection, default_order="scheduled_at")

DbSession = Annotated[Session, Depends(get_db)]


def _validate_inspector(db: Session, inspector_id: str | None) -> None:
    if inspector_id is not None and db.get(User, inspector_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown inspector_id '{inspector_id}'.")


@router.get("", response_model=PaginatedResponse[InspectionResponse])
def list_inspections(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    mine_id: str | None = None,
    inspection_type: str | None = None,
    inspection_status: str | None = Query(default=None, alias="status"),
    compliance_result: str | None = None,
    sort: str = Query(default="scheduled_at"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={
            "mine_id": mine_id,
            "inspection_type": inspection_type,
            "status": inspection_status,
            "compliance_result": compliance_result,
        },
        sort=sort,
        order=order,
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=InspectionResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("inspections"))])
def create_inspection(db: DbSession, payload: InspectionCreate):
    _validate_inspector(db, payload.inspector_id)
    if payload.completed_at and payload.status == "scheduled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="completed_at cannot be set while status is 'scheduled'.",
        )
    inspection = Inspection(**payload.model_dump())
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.get("/{inspection_id}", response_model=InspectionResponse)
def get_inspection(db: DbSession, inspection_id: str):
    return service.get(db, inspection_id)


@router.patch("/{inspection_id}", response_model=InspectionResponse,
               dependencies=[Depends(write_access("inspections"))])
def update_inspection(db: DbSession, inspection_id: str, payload: InspectionUpdate):
    """Record findings / mark compliance; completion requires consistency."""
    inspection = service.get(db, inspection_id)
    data = payload.model_dump(exclude_unset=True)
    if "inspector_id" in data:
        _validate_inspector(db, data["inspector_id"])

    new_status = data.get("status", inspection.status)
    if new_status == "completed":
        result = data.get("compliance_result", inspection.compliance_result)
        if result == "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An inspection cannot be completed with compliance_result 'pending'.",
            )
        if data.get("completed_at") is None and inspection.completed_at is None:
            data["completed_at"] = datetime.now(timezone.utc)
    if new_status in {"scheduled", "cancelled"}:
        data["completed_at"] = None

    for field, value in data.items():
        setattr(inspection, field, value)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.delete("/{inspection_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("inspections"))])
def delete_inspection(db: DbSession, inspection_id: str):
    service.delete(db, inspection_id)
