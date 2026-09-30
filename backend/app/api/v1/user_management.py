"""Administrator-only user management endpoints.

Sits behind the existing users router (same admin-only `write_access("users")`
gate) and provides:

  POST   /users/invite           — mint an invitation link (replaces "Add User")
  GET    /users/invitations      — recent invitations with Pending/Accepted/Expired status
  GET    /users/{id}/impact      — what a permanent delete would affect (read-only)
  DELETE /users/{id}/permanent   — permanently delete an eligible account

All four endpoints are Administrator-only. Route order matters: the static
paths (/invite, /invitations) are registered BEFORE the parameterised
/user_id routes.
"""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import RoleInvitation, User
from app.database.session import get_db
from app.schemas.auth import InvitationLinkResponse, InvitationUserCreate
from app.schemas.common import PaginatedResponse
from app.services import invitations as invitation_service
from app.services import user_deletion

router = APIRouter(prefix="/users", tags=["User Management"], dependencies=[Depends(get_current_user)])

DbSession = Annotated[Session, Depends(get_db)]
AdminOnly = Depends(write_access("users"))


@router.post("/invite", response_model=InvitationLinkResponse, status_code=status.HTTP_201_CREATED)
def invite_user(
    db: DbSession,
    payload: InvitationUserCreate,
    current: Annotated[User, AdminOnly],
):
    """Administrator-only: mint a single-use invitation link.

    The admin provides Full Name, Email and Role only — never a password and
    never a mobile number. The raw link token is returned exactly once (shown
    to the admin to copy/share manually); only its bcrypt hash is stored.
    """
    try:
        email = str(EmailStr._validate(payload.email)).lower()
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A valid email is required.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    invitation, token = invitation_service.create_invitation(
        db,
        role=payload.role,
        full_name=payload.full_name.strip(),
        email=email,
        invited_by_id=current.id,
    )
    return InvitationLinkResponse(
        id=invitation.id,
        role=invitation.role,
        invited_name=invitation.full_name or "",
        invited_email=email,
        invitation_url=f"/accept-invitation/{token}",
        token=token,
        expires_at=invitation.expires_at,
    )


@router.get("/invitations", response_model=PaginatedResponse[dict])
def list_invitations(
    db: DbSession,
    current: Annotated[User, AdminOnly],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Administrator-only: recent invitations with derived status."""
    link_only = RoleInvitation.token_hash.is_not(None)  # link invitations only
    rows = db.scalars(
        select(RoleInvitation)
        .where(link_only)
        .order_by(RoleInvitation.created_at.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    total = int(db.scalar(select(func.count()).select_from(RoleInvitation).where(link_only)) or 0)
    now = datetime.now(timezone.utc)

    def _status(inv: RoleInvitation) -> Literal["Pending", "Accepted", "Expired"]:
        if inv.is_used:
            return "Accepted"
        exp = inv.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return "Expired" if exp < now else "Pending"

    items = [
        {
            "id": inv.id,
            "role": inv.role,
            "full_name": inv.full_name or "",
            "email": inv.bound_email or "",
            "status": _status(inv),
            "expires_at": inv.expires_at,
            "created_at": inv.created_at,
        }
        for inv in rows
    ]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/{user_id}/impact")
def get_user_impact(
    user_id: str,
    db: DbSession,
    current: Annotated[User, AdminOnly],
):
    """Administrator-only: what a permanent delete of this user would affect."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user_deletion.scan_user_impact(db, user)


@router.delete("/{user_id}/permanent")
def delete_user_permanently(
    user_id: str,
    db: DbSession,
    current: Annotated[User, AdminOnly],
):
    """Administrator-only: permanently delete an eligible user account.

    Guards (self-delete, last-admin) are enforced inside the service; the
    response reports what was deleted and what was detached (SET NULL).
    The account's email/mobile become available again for registration.
    """
    report = user_deletion.delete_user_permanently(db, target_id=user_id, acting_admin=current)
    return {"detail": "User permanently deleted.", **report}
