"""Authentication endpoints.

Existing flows (unchanged): OAuth2 password login -> MineGuardAI JWT, /me.
MSG91 SMS OTP flows share the same JWT + bcrypt machinery:

    Registration : code + email -> SMS OTP -> verify -> password
                   -> account (invitation is the source of truth) -> JWT
    Login        : email+password correct -> SMS OTP to registered mobile
                   -> verify -> same MineGuardAI JWT as password login

Role policy (INVITATION-CODE ONLY):
    EVERY new account requires a valid invitation code minted by an
    Administrator (POST /api/users/invite). The code is strictly bound to one
    email, and the invitation record — not the client — decides the account's
    full name, email and role. There is no public/open registration and no
    role selection anywhere in the payload.

    Registration flow: code + email -> mobile -> MSG91 OTP (purpose=register,
    existing machinery, unchanged) -> password -> account (active, JWT).

MSG91 authkey/OTPs never reach the client; OTPs and invitation codes are
bcrypt-hashed at rest and never logged. Rate limiting: resend cooldown,
rolling hourly send cap, per-challenge attempt limit.
"""
import logging
from datetime import datetime, timezone
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
from app.database.models import User
from app.schemas.auth import (
    InvitationValidateResponse,
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
from app.services import invitations as invitation_service
from app.services import otp as otp_service

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Coerce DB datetimes to aware-UTC (SQLite returns naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

router = APIRouter(prefix="/auth", tags=["Authentication"])

DbSession = Annotated[Session, Depends(get_db)]


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
    except msg91.Msg91Error as exc:
        # Include the provider's non-secret reason (config missing, widget
        # rejected, etc.) so a misconfigured deployment is diagnosable from
        # the register page. Authkey never appears in Msg91Error text.
        raise HTTPException(
            status_code=502,
            detail=f"Could not send the OTP right now. Please try again shortly. ({exc})",
        )
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
    """Step 3: create the account — INVITATION-CODE ONLY.

    The invitation (valid code + matching bound email, unused, unexpired, not
    deleted) is validated server-side and is the source of truth for the
    account's email, full name and role. The client cannot choose or change a
    role; without a valid invitation no account is created.
    """
    code = invitation_service.normalize_code(payload.invitation_code or "")
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=invitation_service.MSG_CODE_REQUIRED,
        )

    invitation = invitation_service.validate_invitation(db, code=code, email=payload.email)

    reg = otp_service.read_pending_registration_token(payload.token)
    mobile = str(reg["sub"])

    # The invitation's bound email is authoritative (strict email-code tie).
    email = invitation.bound_email or payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
    if db.scalar(select(User).where(User.mobile == mobile)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mobile already registered.")

    user = User(
        email=email,
        full_name=invitation.full_name or email.split("@")[0],
        role=invitation.role,  # invitation is authoritative; never client-chosen
        mobile=mobile,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()  # assign user.id before stamping the invitation
    try:
        # Atomic single-use consumption in the SAME transaction as the insert:
        # two concurrent registrations with one code cannot both succeed.
        invitation_service.claim_invitation(db, invitation, user_id=user.id)
        db.commit()
        db.refresh(user)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Registration commit failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration failed")

    otp_service.mark_registration_completed(db, mobile)

    return _login_response(user)


@router.get("/invitations/validate", response_model=InvitationValidateResponse)
def validate_invitation_code(db: DbSession, code: str, email: str):
    """Public pre-flight: is this code+email pair registrable right now?

    Runs the exact server-side checks registration enforces (valid code, not
    deleted, not used, not expired, email strictly bound) so the register form
    can show the invitation-fixed role before the OTP step. For a correct
    pair it reveals only the invited name/role/expiry — never internal IDs or
    hashes. The role is NOT a request input; it comes from the invitation.
    """
    invitation = invitation_service.validate_invitation(db, code=code, email=email)
    return InvitationValidateResponse(
        role=invitation.role,
        full_name=invitation.full_name or "",
        expires_at=invitation.expires_at,
    )


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]):
    """Current authenticated user profile."""
    return user
