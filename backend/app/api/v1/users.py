"""Users admin router (auth/RBAC enforcement arrives in Phase 11)."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user, hash_password
from app.database.models import User
from app.database.session import get_db
from app.schemas import UserCreate, UserResponse, UserUpdate
from app.schemas.common import PaginatedResponse
from app.services import CrudService
from app.services.msg91 import normalize_mobile

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[Depends(get_current_user)])
service = CrudService(User, default_order="created_at")

DbSession = Annotated[Session, Depends(get_db)]


def _to_response(user: User) -> UserResponse:
    """Hashed passwords must never leave the backend."""
    data = UserResponse.model_validate(user)
    return data


@router.get("", response_model=PaginatedResponse[UserResponse])
def list_users(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    role: str | None = None,
    is_active: bool | None = None,
    sort: str = Query(default="created_at"),
    order: Literal["asc", "desc"] = "desc",
):
    items, total = service.list(
        db,
        skip=skip,
        limit=limit,
        filters={"role": role, "is_active": is_active},
        sort=sort,
        order=order,
    )
    return {"items": [_to_response(u) for u in items], "total": total, "skip": skip, "limit": limit}


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(write_access("users"))])
def create_user(db: DbSession, payload: UserCreate):
    try:
        data = payload.model_dump()
        password = data.pop("password")
        mobile = data.pop("mobile", None)
        if mobile:
            data["mobile"] = normalize_mobile(mobile)  # raises ValueError -> 422 below
        user = User(**data, hashed_password=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return _to_response(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or mobile already exists.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{user_id}", response_model=UserResponse)
def get_user(db: DbSession, user_id: str):
    return _to_response(service.get(db, user_id))


@router.patch("/{user_id}", response_model=UserResponse,
               dependencies=[Depends(write_access("users"))])
def update_user(db: DbSession, user_id: str, payload: UserUpdate):
    user = service.get(db, user_id)
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    if "mobile" in data:
        mobile = data.pop("mobile")
        user.mobile = normalize_mobile(mobile) if mobile else None
    for field, value in data.items():
        setattr(user, field, value)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Update failed (duplicate email or mobile?).")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _to_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("users"))])
def delete_user(db: DbSession, user_id: str):
    # Soft-delete: deactivate instead of destroying audit-relevant history.
    user = service.get(db, user_id)
    user.is_active = False
    db.commit()
