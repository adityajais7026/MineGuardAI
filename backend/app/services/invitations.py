"""Link-invitation lifecycle for the "Invite User" flow.

An Administrator mints an invitation for one of the four roles. The raw
credential — an unpredictable, cryptographically secure URL token — is returned
exactly once to the inviting admin (who shares the link manually via WhatsApp,
email, etc.); only its bcrypt hash is stored. This module never sends SMS or
email itself.

Acceptance is OTP-gated and reuses the production MSG91 flow unchanged
(`app.services.otp`, purpose=register — the SAME machinery as public
registration, no second OTP system): the invited person verifies their mobile
number with an SMS OTP BEFORE setting a password. A successful verification
mints a single-use, 15-minute pending-registration JWT (`typ=prp`) via the
OTP service; the final accept step validates it against the mobile in the
payload, so no account can ever be created without a verified mobile.

Security properties:
  * token: `secrets.token_urlsafe(24)` (128 bits of entropy from the OS CSPRNG)
  * storage: bcrypt hash only (`token_hash`, mirrored in `code_hash`)
  * single-use: consumed in the SAME transaction that creates the account,
    so a concurrent second accept rolls back instead of double-spending
  * expiry: INVITATION_EXPIRY_HOURS (default 24h) — expired invitations are
    rejected for both validation and acceptance
  * role authority: the account always receives the invitation's stored role;
    the client cannot influence it via URL, payload or otherwise
  * email bind: when minted with an email, only that email can accept
  * mobile verification: REQUIRED — delegated to the existing MSG91 OTP
    service (send cooldown, hourly cap, attempt policy all inherited); the
    invitation link itself is never an OTP and carries no OTP authority
  * no plaintext password is ever stored on the invitation
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.database.models import RoleInvitation
from app.services import msg91
from app.services import otp as otp_service

# Roles an Administrator may invite (the full privileged set).
INVITABLE_ROLES = ("admin", "environmental_officer", "mine_manager", "safety_officer")

INVALID_INVITATION_DETAIL = "This invitation is expired or has already been used."


def _as_utc(value: datetime) -> datetime:
    """Coerce DB datetimes to aware-UTC (SQLite returns naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_invitation(
    db: Session,
    *,
    role: str,
    full_name: str,
    email: str | None,
    invited_by_id: str,
) -> tuple[RoleInvitation, str]:
    """Mint a link invitation; returns (row, raw_token).

    The raw token is returned exactly once (shown to the inviting admin) and
    only its bcrypt hash is persisted.
    """
    token = secrets.token_urlsafe(24)
    token_hash = hash_password(token)
    invitation = RoleInvitation(
        role=role,
        full_name=full_name,
        bound_email=email.lower() if email else None,
        token_hash=token_hash,
        code_hash=token_hash,  # keep the single credential-hash invariant
        invited_by_id=invited_by_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.INVITATION_EXPIRY_HOURS),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, token


def validate_invitation(db: Session, token: str) -> RoleInvitation:
    """Resolve a raw token to a valid (unused, unexpired) invitation.

    Raises 404 with a generic message for unknown/expired/used tokens so the
    endpoint reveals nothing about which invitations exist.
    """
    invitation = _find_by_token(db, token)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INVALID_INVITATION_DETAIL)
    return invitation


def _find_by_token(db: Session, token: str) -> RoleInvitation | None:
    if not token or len(token) > 200:
        return None
    candidates = db.scalars(
        select(RoleInvitation).where(RoleInvitation.is_used.is_(False))
    ).all()
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        if _as_utc(candidate.expires_at) < now:
            continue  # expired
        stored_hash = candidate.token_hash or candidate.code_hash
        if stored_hash and verify_password(token, stored_hash):
            return candidate
    return None


def _normalized_or_400(mobile: str) -> str:
    """Normalize a payload mobile (same rules as the public OTP endpoints)."""
    try:
        return msg91.normalize_mobile(mobile)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def start_mobile_verification(db: Session, *, token: str, mobile: str) -> dict:
    """Send the accept-flow OTP to `mobile` via the EXISTING MSG91 OTP service.

    The invitation link token is validated FIRST (404, generic message) so an
    invalid/expired/used link never triggers SMS spend. Delegation to
    `otp_service.request_otp` with purpose=register inherits everything the
    public registration flow enforces: the not-already-registered mobile
    check (409), resend cooldown and rolling hourly cap (429). The invitation
    link itself is not an OTP — it only gates WHO may start this verification.
    """
    validate_invitation(db, token)
    mobile = _normalized_or_400(mobile)
    return otp_service.request_otp(
        db, purpose=otp_service.PURPOSE_REGISTER, subject=mobile, mobile=mobile
    )


def verify_mobile_otp(db: Session, *, token: str, mobile: str, code: str) -> dict:
    """Verify the SMS code; return the RegisterVerifyResponse payload.

    On success the OTP service consumes the challenge and we mint the
    single-use pending-registration JWT (`typ=prp`) carrying the verified
    mobile — the exact same token shape the public registration flow uses.
    """
    validate_invitation(db, token)
    mobile = _normalized_or_400(mobile)
    otp_service.verify_otp(db, purpose=otp_service.PURPOSE_REGISTER, subject=mobile, code=code)
    return {
        "token": otp_service.mint_pending_registration_token(mobile),
        "mobile_masked": msg91.mask_mobile(mobile),
        "expires_in_minutes": otp_service.REGISTER_TOKEN_MINUTES,
    }


def accept_invitation(
    db: Session,
    *,
    token: str,
    mobile: str,
    reg_token: str,
    password: str,
) -> tuple[RoleInvitation, "User"]:  # noqa: F821  (User imported lazily for atomicity)
    """Atomically consume the invitation and create the active account.

    `reg_token` must be the pending-registration JWT minted after a successful
    MSG91 OTP verification and must carry exactly `mobile` — a user cannot
    accept without verifying a mobile first, or swap in a different number
    after verifying. Everything (invitation consumption + user insert) commits
    in ONE transaction: a replayed token fails because `is_used` is already
    set inside the same transaction, and a failed user insert rolls the
    consumption back. The role comes exclusively from the stored invitation.
    """
    from app.database.models import User  # local import: no cycle at module load

    invitation = validate_invitation(db, token)

    # The email is fixed at mint time (when supplied): the accept step may not
    # introduce a different identity than the admin invited.
    email = invitation.bound_email
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation is not bound to an email address. Request a new invitation.",
        )

    mobile = _normalized_or_400(mobile)
    reg = otp_service.read_pending_registration_token(reg_token)  # 401 on bad/expired
    if str(reg.get("sub")) != mobile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration session expired. Start again.",
        )

    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already registered. Log in instead or request a new invitation.",
        )
    if db.scalar(select(User.id).where(User.mobile == mobile)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mobile number is already registered. Try logging in instead.",
        )

    user = User(
        email=email,
        full_name=invitation.full_name or email.split("@")[0],
        role=invitation.role,  # server-side authority; never client-chosen
        mobile=mobile,  # MSG91-verified via the existing register-purpose flow
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.flush()  # assign user.id before stamping the invitation

    invitation.is_used = True
    invitation.used_by_id = user.id
    invitation.used_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(user)

    # Single-use registration: drop the mobile's register challenges exactly
    # like the public flow does (after the account commit; a leftover challenge
    # is harmless because request_otp re-checks registered mobiles).
    otp_service.mark_registration_completed(db, mobile)
    return invitation, user
