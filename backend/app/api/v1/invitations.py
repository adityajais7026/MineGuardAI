"""Public invitation acceptance endpoints (no authentication).

The invited person opens /accept-invitation/<token> in the frontend, which
calls these endpoints with the token from the URL. No MSG91/SMS is involved;
the invited person sets their own password. The account's role comes
exclusively from the server-side invitation record.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_db
from app.schemas.auth import InvitationAcceptRequest, InvitationPublicResponse
from app.schemas.user import UserResponse
from app.services import invitations as invitation_service

router = APIRouter(prefix="/invitations", tags=["Invitations"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/accept/{token}", response_model=InvitationPublicResponse)
def get_invitation(db: DbSession, token: str):
    """Validate an invitation token for the accept page.

    404 with a generic message for unknown/expired/used tokens; on success the
    invited name/email/role are shown (no database IDs, no secrets).
    """
    invitation = invitation_service.validate_invitation(db, token)
    return InvitationPublicResponse(
        full_name=invitation.full_name or "",
        email=invitation.bound_email or "",
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


@router.post("/accept/{token}")
def accept_invitation(db: DbSession, token: str, payload: InvitationAcceptRequest):
    """Consume the invitation and create the account atomically.

    The invitation's stored role is authoritative; the client cannot change
    it. On success the invited user is logged in immediately (same JWT shape
    as every other login path).
    """
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Passwords do not match.")

    invitation, user = invitation_service.accept_invitation(db, token=token, password=payload.password)

    token_out = create_access_token(subject=user.id, role=user.role)
    return {
        "access_token": token_out,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
        "role": invitation.role,
    }
