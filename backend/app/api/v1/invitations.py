"""Public invitation acceptance endpoints (no authentication).

The invited person opens /accept-invitation/<token> in the frontend, which
drives three steps with the token from the URL:

    1. POST /invitations/accept/{token}/mobile/start   -> MSG91 SMS OTP
    2. POST /invitations/accept/{token}/mobile/verify  -> pending-reg token
    3. POST /invitations/accept/{token}                -> account + JWT

Mobile verification reuses the EXISTING MSG91 OTP machinery unchanged
(`app.services.otp`, purpose=register — the same functions the public
registration flow calls); there is no second OTP system. The invitation link
itself is not an OTP: it only determines WHO may start verification and the
role the account receives. The invited person sets their own password in the
last step; the account is always created with the OTP-verified mobile.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_db
from app.schemas.auth import (
    InvitationAcceptRequest,
    InvitationPublicResponse,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    RegisterVerifyResponse,
)
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


@router.post("/accept/{token}/mobile/start", response_model=OtpSendResponse)
def start_mobile_otp(db: DbSession, token: str, payload: OtpSendRequest):
    """Step 1: send the MSG91 OTP to the invited person's mobile number.

    The link token is validated first so bad links never trigger SMS. The OTP
    send/verify logic is the existing register-purpose flow unchanged —
    cooldown, hourly cap and the not-already-registered mobile check included.
    """
    return OtpSendResponse(
        **invitation_service.start_mobile_verification(db, token=token, mobile=payload.mobile)
    )


@router.post("/accept/{token}/mobile/verify", response_model=RegisterVerifyResponse)
def verify_mobile_otp(db: DbSession, token: str, payload: OtpVerifyRequest):
    """Step 2: verify the SMS code -> single-use pending-registration token.

    Same 15-minute `typ=prp` token the public registration flow mints after
    OTP verification; it proves the mobile is verified and carries no other
    authority. The account is only created in step 3.
    """
    return RegisterVerifyResponse(
        **invitation_service.verify_mobile_otp(db, token=token, mobile=payload.mobile, code=payload.otp)
    )


@router.post("/accept/{token}")
def accept_invitation(db: DbSession, token: str, payload: InvitationAcceptRequest):
    """Step 3: consume the invitation and create the account atomically.

    Requires the pending-registration token from step 2 (the mobile was
    MSG91-verified and cannot be swapped afterwards). The invitation's stored
    role is authoritative; the client cannot change it. On success the invited
    user is logged in immediately (same JWT shape as every other login path).
    """
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Passwords do not match.")

    invitation, user = invitation_service.accept_invitation(
        db, token=token, mobile=payload.mobile, reg_token=payload.token, password=payload.password
    )

    token_out = create_access_token(subject=user.id, role=user.role)
    return {
        "access_token": token_out,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
        "role": invitation.role,
    }
