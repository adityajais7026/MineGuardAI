"""Authentication endpoints.

Existing flows (unchanged): OAuth2 password login -> MineGuardAI JWT, /me.
New MSG91 SMS OTP flows share the same JWT + bcrypt machinery:

    Registration : mobile -> SMS OTP -> verify -> email/name/password/role
                   -> account (privileged roles gated, see below) -> JWT
    Login        : email+password correct -> SMS OTP to registered mobile
                   -> verify -> same MineGuardAI JWT as password login

Role policy:
    public registration ... mine_manager, safety_officer (Inspector) -> active
    Government Officer .. environmental_officer -> INVITATION-ONLY: a valid,
        single-use, unexpired invitation code minted by an Administrator
        (POST /api/auth/invitations) is required; the account is created
        active. There is no public self-registration or pending-approval path.
    Administrator ...... invitation-only; requires a single-use invitation
        code minted by an existing admin (POST /api/auth/invitations).

    A supplied invitation code grants exactly the role it was minted for —
    the client payload can never elevate itself to a privileged role.

MSG91 authkey/OTPs never reach the client; OTPs and invitation codes are
bcrypt-hashed at rest and never logged. Rate limiting: resend cooldown,
rolling hourly send cap, per-challenge attempt limit.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_current_user,
    get_db,
    hash_password,
    verify_password,
)
from app.database.models import RoleInvitation, User
from app.schemas.auth import (
    InvitationCreateRequest,
    InvitationResponse,
    LoginStartRequest,
    LoginStartResponse,
    LoginVerifyRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    RegisterCompleteRequest,
    RegisterStartRequest,
    RegisterVerifyResponse,
)
from app.schemas.user import UserResponse
from app.services import msg91
from app.services import otp as otp_service

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Coerce DB datetimes to aware-UTC (SQLite returns naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

router = APIRouter(prefix="/auth", tags=["Authentication"])

DbSession = Annotated[Session, Depends(get_db)]

PUBLIC_SELF_SERVICE_ROLES = {"mine_manager", "safety_officer"}
INVITATION_ONLY_ROLES = {"admin", "environmental_officer"}
_ROLE_LABELS = {"admin": "Administrator", "environmental_officer": "Government Officer"}


def _login_response(user: User) -> dict:
    """Same response shape as the classic password login (existing JWT)."""
    token = create_access_token(subject=user.id, role=user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }


def _issue_otp(db: Session, *, purpose: str, subject: str, mobile: str) -> OtpSendResponse:
    try:
        result = otp_service.request_otp(db, purpose=purpose, subject=subject, mobile=mobile)
    except otp_service.OtpError:
        raise
    except msg91.Msg91Error:
        raise HTTPException(status_code=502, detail="Could not send the OTP right now. Please try again shortly.")
    except Exception:
        logger.exception("OTP request failed (purpose=%s)", purpose)
        raise HTTPException(status_code=500, detail="Could not start OTP verification")
    return OtpSendResponse(**result)


@router.post("/login")
def login(db: DbSession, form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """OAuth2 password flow; returns a bearer token usable in Swagger too."""
    user = db.scalar(select(User).where(User.email == form.username))
    if user is None or user.hashed_password is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    token = create_access_token(subject=user.id, role=user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }


@router.post("/login/otp/start", response_model=LoginStartResponse)
def login_otp_start(db: DbSession, payload: LoginStartRequest):
    """Step 1 of OTP login: validate credentials, then send the SMS OTP.

    The password is required here so knowing a mobile number alone is not
    enough to trigger SMS. Accounts without a registered mobile (legacy/seed
    users) report otp_required=False and simply use the classic login.
    """
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or user.hashed_password is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    if not user.mobile:
        return LoginStartResponse(
            otp_required=False, mobile_masked=None, cooldown_seconds=None, expires_in_minutes=None
        )

    result = _issue_otp(db, purpose=otp_service.PURPOSE_LOGIN, subject=user.id, mobile=user.mobile)
    return LoginStartResponse(
        otp_required=True,
        mobile_masked=result.mobile_masked,
        cooldown_seconds=result.cooldown_seconds,
        expires_in_minutes=result.expires_in_minutes,
    )


@router.post("/login/otp/verify")
def login_otp_verify(db: DbSession, payload: LoginVerifyRequest):
    """Step 2 of OTP login: verify the SMS code, issue the MineGuardAI JWT.

    Response is identical to /auth/login (access_token + user).
    """
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login session. Start again.")

    try:
        otp_service.verify_otp(db, purpose=otp_service.PURPOSE_LOGIN, subject=user.id, code=payload.otp)
    except otp_service.OtpError:
        raise
    except Exception:
        logger.exception("Login OTP verification failed")
        raise HTTPException(status_code=500, detail="Verification failed")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    return _login_response(user)


@router.post("/register/otp/start", response_model=OtpSendResponse)
def register_otp_start(db: DbSession, payload: RegisterStartRequest):
    """Step 1 of registration: send an OTP to the (unused) mobile number."""
    try:
        mobile = msg91.normalize_mobile(payload.mobile)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _issue_otp(db, purpose=otp_service.PURPOSE_REGISTER, subject=mobile, mobile=mobile)


@router.post("/register/otp/verify", response_model=RegisterVerifyResponse)
def register_otp_verify(db: DbSession, payload: OtpVerifyRequest):
    """Step 2: verify the SMS code -> single-use pending-registration token.

    The token (15 min, distinct `typ` claim) proves the mobile is verified and
    carries no other authority; the account is only created in step 3.
    """
    try:
        mobile = msg91.normalize_mobile(payload.mobile)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        otp_service.verify_otp(db, purpose=otp_service.PURPOSE_REGISTER, subject=mobile, code=payload.otp)
    except otp_service.OtpError:
        raise
    except Exception:
        logger.exception("Registration OTP verification failed")
        raise HTTPException(status_code=500, detail="Verification failed")

    token = otp_service.mint_pending_registration_token(mobile)
    return RegisterVerifyResponse(
        token=token,
        mobile_masked=msg91.mask_mobile(mobile),
        expires_in_minutes=otp_service.REGISTER_TOKEN_MINUTES,
    )


@router.post("/register/complete")
def register_complete(db: DbSession, payload: RegisterCompleteRequest):
    """Step 3: create the account from the pending-registration token.

    Role gating:
      * mine_manager / safety_officer -> created active (public self-service).
      * admin / environmental_officer -> invitation-only: a valid single-use,
        unexpired invitation code minted by an Administrator is required and
        grants exactly its minted role; the account is created active.
    """
    reg = otp_service.read_pending_registration_token(payload.token)
    mobile = str(reg["sub"])
    invitation_code = payload.invitation_code or reg.get("inv")

    role = payload.role
    if role not in PUBLIC_SELF_SERVICE_ROLES | INVITATION_ONLY_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role for registration.")

    # Privileged roles are invitation-only: any supplied code must be valid
    # (single-use, unexpired, binds honored) and grants exactly the role it
    # was minted for — never a public self-service role.
    invitation: RoleInvitation | None = None
    if invitation_code:
        invitation = _consume_invitation(db, code=invitation_code, email=payload.email, mobile=mobile)
        role = invitation.role
    elif role in INVITATION_ONLY_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{_ROLE_LABELS[role]} accounts require an invitation code from an existing administrator.",
        )

    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    if db.scalar(select(User).where(User.mobile == mobile)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mobile already registered.")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        role=role,
        mobile=mobile,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        logger.exception("Registration commit failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration failed")

    if invitation is not None:
        invitation.is_used = True
        invitation.used_by_id = user.id
        invitation.used_at = datetime.now(timezone.utc)
        db.commit()

    otp_service.mark_registration_completed(db, mobile)

    return _login_response(user)


def _consume_invitation(db: Session, *, code: str, email: str, mobile: str) -> RoleInvitation:
    """Validate an unused, unexpired invitation honoring its email/mobile binds.

    Codes are bcrypt-hashed, so candidates are checked individually. The
    invitation's role is authoritative: callers must use invitation.role (a
    code never grants a public self-service role).
    """
    candidates = db.scalars(select(RoleInvitation).where(RoleInvitation.is_used.is_(False))).all()
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        if _as_utc(candidate.expires_at) < now:
            continue
        if candidate.bound_email and candidate.bound_email.lower() != email.lower():
            continue
        if candidate.bound_mobile and candidate.bound_mobile != mobile:
            continue
        if verify_password(code, candidate.code_hash):
            return candidate
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid, expired or already-used invitation code.",
    )


@router.post("/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
def create_invitation(
    db: DbSession,
    payload: InvitationCreateRequest,
    current: Annotated[User, Depends(get_current_user)],
):
    """Administrator-only: mint a single-use invitation for a privileged role.

    The raw code is returned exactly once (to the inviting admin) and stored
    bcrypt-hashed.
    """
    if current.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator privileges required")
    code = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=payload.expires_in_minutes)
    inv = RoleInvitation(
        role=payload.role,
        code_hash=hash_password(code),
        invited_by_id=current.id,
        note=payload.note,
        bound_email=payload.bound_email,
        bound_mobile=msg91.normalize_mobile(payload.bound_mobile) if payload.bound_mobile else None,
        expires_at=expires_at,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return InvitationResponse(id=inv.id, role=inv.role, code=code, note=inv.note, expires_at=inv.expires_at)


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]):
    """Current authenticated user profile."""
    return user
