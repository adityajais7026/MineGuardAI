"""Administrator-only user management endpoints.

Registered BEFORE the users router (same admin-only `write_access("users")`
gate) and provides the invitation-code system — the ONLY registration path:

  POST   /users/invite                — mint an invitation code (Full Name/Email/Role)
  GET    /users/invitations           — management list: code visible, status
                                        Active/Used/Expired/Deleted, created_by
  POST   /users/invitations/{id}/regenerate — new code, same email/role;
                                        previous code invalidated immediately
  DELETE /users/invitations/{id}      — soft-delete; code invalid immediately
  GET    /users/{id}/impact           — what a permanent delete would affect
  DELETE /users/{id}/permanent        — permanently delete an eligible account

Route order matters: the static paths (/invite, /invitations) are registered
BEFORE the parameterised /user_id routes.
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
from app.schemas.auth import (
    InvitationCodeResponse,
    InvitationSummaryResponse,
    InvitationUserCreate,
)
from app.schemas.common import PaginatedResponse
from app.services import invitations as invitation_service
from app.services import user_deletion

router = APIRouter(prefix="/users", tags=["User Management"], dependencies=[Depends(get_current_user)])

DbSession = Annotated[Session, Depends(get_db)]
AdminOnly = Depends(write_access("users"))


@router.post("/invite", response_model=InvitationCodeResponse, status_code=status.HTTP_201_CREATED)
def invite_user(
    db: DbSession,
    payload: InvitationUserCreate,
    current: Annotated[User, AdminOnly],
):
    """Administrator-only: mint an invitation code.

    The admin provides Full Name, Email and Role only — never a password and
    never a mobile number. The code is stored plaintext AND bcrypt-hashed:
    plaintext so the creator can keep copying it from the management list
    until the invitation is used, expired or deleted; hash so validation never
    trusts the plaintext column. The email is strictly bound: only that email
    can register with this code, and the account always receives the
    invitation's role.
    """
    try:
        email = str(EmailStr._validate(payload.email)).lower()
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A valid email is required.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    invitation, code = invitation_service.create_invitation(
        db,
        role=payload.role,
        full_name=payload.full_name.strip(),
        email=email,
        invited_by_id=current.id,
    )
    return InvitationCodeResponse(
        id=invitation.id,
        role=invitation.role,
        full_name=invitation.full_name or "",
        email=email,
        code=code,
        expires_at=invitation.expires_at,
    )


@router.get("/invitations", response_model=PaginatedResponse[InvitationSummaryResponse])
def list_invitations(
    db: DbSession,
    current: Annotated[User, AdminOnly],
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Administrator-only: invitation management list.

    Shows the plaintext code for every invitation that still has one (so the
    creator can copy it at any time before use/expiry/deletion — never the
    hash), plus Full Name, Email, Role, Status (Active/Used/Expired/Deleted),
    Created By, Created At and Expiry.
    """
    rows = db.scalars(
        select(RoleInvitation).order_by(RoleInvitation.created_at.desc()).offset(skip).limit(limit)
    ).all()
    total = int(db.scalar(select(func.count()).select_from(RoleInvitation)) or 0)

    creator_ids = {row.invited_by_id for row in rows if row.invited_by_id}
    creators = {}
    if creator_ids:
        creators = {
            user.id: user.email
            for user in db.scalars(select(User).where(User.id.in_(creator_ids))).all()
        }

    items = [
        InvitationSummaryResponse(
            id=inv.id,
            role=inv.role,
            full_name=inv.full_name or "",
            email=inv.bound_email or "",
            code=inv.code,
            status=invitation_service.invitation_status(inv),
            created_by=creators.get(inv.invited_by_id) if inv.invited_by_id else None,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
        )
        for inv in rows
    ]
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.post("/invitations/{invitation_id}/regenerate", response_model=InvitationCodeResponse)
def regenerate_invitation(
    invitation_id: str,
    db: DbSession,
    current: Annotated[User, AdminOnly],
):
    """Administrator-only: issue a NEW code for the SAME email/role/purpose.

    The previous code is invalidated immediately (its plaintext and hash are
    overwritten and the expiry clock restarts). Used/deleted/expired
    invitations cannot be regenerated — create a new invitation instead.
    """
    invitation, code = invitation_service.regenerate_invitation(
        db, invitation_id=invitation_id, acting_admin=current
    )
    return InvitationCodeResponse(
        id=invitation.id,
        role=invitation.role,
        full_name=invitation.full_name or "",
        email=invitation.bound_email or "",
        code=code,
        expires_at=invitation.expires_at,
    )


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_200_OK)
def delete_invitation(
    invitation_id: str,
    db: DbSession,
    current: Annotated[User, AdminOnly],
):
    """Administrator-only: soft-delete an invitation (code invalid immediately).

    The row is kept for audit and shows status "Deleted". Requires an explicit
    confirmation in the UI; the API itself is permanent for the code.
    """
    invitation_service.delete_invitation(db, invitation_id=invitation_id, acting_admin=current)
    return {"detail": "Invitation deleted. Its code is no longer valid."}


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
