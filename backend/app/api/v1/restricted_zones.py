"""Restricted zones CRUD router."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.mine_scope import ensure_mine_in_scope, scope_column, visible_mine_ids
from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import RestrictedZone, User
from app.database.session import get_db
from app.schemas import RestrictedZoneCreate, RestrictedZoneResponse, RestrictedZoneUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService

router = APIRouter(prefix="/restricted-zones", tags=["Restricted Zones"],
                   dependencies=[Depends(get_current_user)])
service = CrudService(RestrictedZone, default_order="created_at")

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=PaginatedResponse[RestrictedZoneResponse])
def list_zones(
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    mine_id: str | None = None,
    is_active: bool | None = None,
    sort: str = Query(default="created_at"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db, skip=skip, limit=limit, filters={"mine_id": mine_id, "is_active": is_active},
        sort=sort, order=order,
        additional_filter=scope_column(RestrictedZone.mine_id, visible_mine_ids(db, user)),
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=RestrictedZoneResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("restricted_zones"))])
def create_zone(db: DbSession, payload: RestrictedZoneCreate, user: Annotated[User, Depends(get_current_user)]):
    ensure_mine_in_scope(db, user, payload.mine_id)
    try:
        return service.create(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown mine_id.")


@router.get("/{zone_id}", response_model=RestrictedZoneResponse)
def get_zone(db: DbSession, zone_id: str, user: Annotated[User, Depends(get_current_user)]):
    zone = service.get(db, zone_id)
    ensure_mine_in_scope(db, user, zone.mine_id)
    return zone


@router.patch("/{zone_id}", response_model=RestrictedZoneResponse,
               dependencies=[Depends(write_access("restricted_zones"))])
def update_zone(db: DbSession, zone_id: str, payload: RestrictedZoneUpdate, user: Annotated[User, Depends(get_current_user)]):
    zone = service.get(db, zone_id)
    ensure_mine_in_scope(db, user, zone.mine_id)
    return service.update(db, zone_id, payload)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("restricted_zones"))])
def delete_zone(db: DbSession, zone_id: str, user: Annotated[User, Depends(get_current_user)]):
    zone = service.get(db, zone_id)
    ensure_mine_in_scope(db, user, zone.mine_id)
    service.delete(db, zone_id)
