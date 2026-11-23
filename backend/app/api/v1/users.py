"""Users admin router (auth/RBAC enforcement arrives in Phase 11).

Administrator-managed credentials
--------------------------------
There is no email-delivery channel in this deployment, so a self-service
"forgot password" link is not offered. Instead an Administrator can:

  * POST /users/{id}/password-reset — issues a cryptographically random
    TEMPORARY password, returned exactly once in the response (never logged,
    never stored in plaintext, never written to the audit payload). The
    account is flagged `must_change_password`, so every authenticated call
    except /auth/me and /auth/change-password answers HTTP 403 until the
    holder sets their own password. All previously issued sessions are
    revoked immediately (the JWT session generation is incremented).
  * PATCH /users/{id} with `password` — the same temporary-password path,
    used by the Edit dialog.

Every reset, password change, deactivation and deletion is appended to the
tamper-evident audit chain.
"""
import logging
import secrets
import string
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import (
    CurrentUser,
    get_current_user,
    hash_password,
    password_policy_error,
    require_roles,
)
from app.database.models import User
from app.database.session import get_db
from app.schemas import UserCreate, UserResponse, UserUpdate
from app.schemas.common import PaginatedResponse
from app.schemas.user import PasswordResetResponse
from app.services import CrudService
from app.services import user_deletion
from app.services.governance import audit_chain
from app.services.msg91 import normalize_mobile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[Depends(get_current_user)])
service = CrudService(User, default_order="created_at")

DbSession = Annotated[Session, Depends(get_db)]

# Unambiguous alphabet: no O/0, I/1/l, so a temporary password read aloud or
# copied by hand cannot be mistyped into a lockout.
_TEMP_ALPHABET = (
    string.ascii_uppercase.replace("O", "").replace("I", "")
    + string.ascii_lowercase.replace("l", "").replace("o", "")
    + "23456789"
    + "!@#$%^&*-_=+"
)

TEMP_PASSWORD_LENGTH = 16


def _to_response(user: User) -> UserResponse:
    """Hashed passwords must never leave the backend."""
    data = UserResponse.model_validate(user)
    return data


def _generate_temporary_password() -> str:
    """Random temporary password satisfying every character class."""
    while True:
        candidate = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(TEMP_PASSWORD_LENGTH))
        has_upper = any(c.isupper() for c in candidate)
        has_lower = any(c.islower() for c in candidate)
        has_digit = any(c.isdigit() for c in candidate)
        has_symbol = any(c in "!@#$%^&*-_=+" for c in candidate)
        if has_upper and has_lower and has_digit and has_symbol:
            return candidate


def _assert_not_self(actor: User, target: User, action: str) -> None:
    if target.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You cannot {action} your own account.",
        )


def _assert_not_last_admin(db: Session, target: User, action: str) -> None:
    """Refuse an action that would remove the last usable Administrator."""
    if target.role != "admin" or not target.is_active:
        return
    others = user_deletion.other_active_admin_count(db, exclude_id=target.id)
    if others == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot {action} the last active Administrator. "
                "Grant another account the Administrator role first."
            ),
        )


def _audit(db: Session, actor: User, action: str, target: User, payload: dict) -> None:
    """Append the credential/account event to the tamper-evident audit chain."""
    audit_chain.append_event(
        db,
        actor_id=actor.id,
        actor_role=actor.role,
        action=action,
        entity_type="user",
        entity_id=target.id,
        payload={"email": target.email, "role": target.role, **payload},
    )


@router.get("", response_model=PaginatedResponse[UserResponse],
           dependencies=[Depends(require_roles("admin"))])
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
def create_user(db: DbSession, payload: UserCreate, current: CurrentUser):
    try:
        data = payload.model_dump()
        password = data.pop("password")
        mobile = data.pop("mobile", None)
        if mobile:
            data["mobile"] = normalize_mobile(mobile)  # raises ValueError -> 422 below
        # An administrator sets this password, so it is temporary by definition.
        user = User(**data, hashed_password=hash_password(password), must_change_password=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        _audit(db, current, "user.create", user, {
            "method": "administrator_set_password",
            "must_change_password": True,
        })
        return _to_response(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or mobile already exists.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{user_id}", response_model=UserResponse,
           dependencies=[Depends(require_roles("admin"))])
def get_user(db: DbSession, user_id: str):
    return _to_response(service.get(db, user_id))


@router.patch("/{user_id}", response_model=UserResponse,
               dependencies=[Depends(write_access("users"))])
def update_user(db: DbSession, user_id: str, payload: UserUpdate, current: CurrentUser):
    user = service.get(db, user_id)
    data = payload.model_dump(exclude_unset=True)

    # Role/status changes on an Administrator must not strand the platform.
    if data.get("role") not in (None, "admin") and user.role == "admin":
        _assert_not_last_admin(db, user, "change the role of")
    if data.get("is_active") is False:
        _assert_not_self(current, user, "deactivate")
        _assert_not_last_admin(db, user, "deactivate")

    password_changed = "password" in data
    if password_changed:
        new_password = data.pop("password")
        policy_error = password_policy_error(new_password)
        if policy_error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=policy_error)
        user.hashed_password = hash_password(new_password)
        # Administrator-set password = temporary: force the holder to replace
        # it and invalidate every session issued with the old secret.
        user.must_change_password = True
        user.token_version = int(user.token_version or 0) + 1

    if "mobile" in data:
        mobile = data.pop("mobile")
        user.mobile = normalize_mobile(mobile) if mobile else None
    # Explicit null means "no change" (the column is NOT NULL); [] clears the
    # permitted-mine scope. Omitted means no change (exclude_unset above).
    if data.get("permitted_mine_ids") is None:
        data.pop("permitted_mine_ids", None)
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

    if password_changed:
        _audit(db, current, "user.password_reset", user, {
            "method": "administrator_set_password",
            "must_change_password": True,
            "sessions_revoked": True,
            "role_changed": "role" in data,
        })
    elif data.get("is_active") is False:
        _audit(db, current, "user.deactivated", user, {"sessions_revoked": True})
    return _to_response(user)


@router.post("/{user_id}/password-reset", response_model=PasswordResetResponse)
def reset_user_password(user_id: str, db: DbSession, current: CurrentUser):
    """Administrator-only: issue a one-time temporary password.

    The account must set its own password on next sign-in; the temporary
    value is disclosed only in this response and never stored or logged. All
    of the account's existing sessions stop working immediately.
    """
    if current.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an Administrator can reset another account's password.",
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    temporary_password = _generate_temporary_password()
    user.hashed_password = hash_password(temporary_password)
    user.must_change_password = True
    user.token_version = int(user.token_version or 0) + 1
    db.commit()
    db.refresh(user)

    _audit(db, current, "user.password_reset", user, {
        "method": "temporary_password",
        "must_change_password": True,
        "sessions_revoked": True,
    })
    logger.info("Password reset issued for user %s by admin %s", user.id, current.id)
    return PasswordResetResponse(
        user_id=user.id,
        email=user.email,
        temporary_password=temporary_password,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
                dependencies=[Depends(write_access("users"))])
def delete_user(db: DbSession, user_id: str, current: CurrentUser):
    """Soft-delete (deactivate). History is preserved; sessions are revoked."""
    user = service.get(db, user_id)
    _assert_not_self(current, user, "deactivate")
    _assert_not_last_admin(db, user, "deactivate")
    user.is_active = False
    user.token_version = int(user.token_version or 0) + 1
    db.commit()
    _audit(db, current, "user.deactivated", user, {"sessions_revoked": True, "method": "soft_delete"})
