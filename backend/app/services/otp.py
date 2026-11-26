"""OTP challenge lifecycle for MSG91 OTP Widget SMS verification.

State lives in the `otp_challenges` table (one active challenge per
(subject, purpose)). MSG91's widget generates and validates the code using the
widget's default SMS configuration; we store the provider's request id and
enforce our own policy on top:

- expiry            : MSG91_OTP_EXPIRY_MINUTES (default 10)
- attempts          : MSG91_OTP_MAX_ATTEMPTS wrong entries burn the challenge
- resend cooldown   : MSG91_OTP_RESEND_COOLDOWN_SECONDS between sends
- hourly send cap   : 6 sends per subject/purpose per rolling hour

Registration additionally mints a single-use, 15-minute JWT-scoped
"pending-registration" token carrying the verified mobile (distinct `prp`
claim), so a user cannot register without verifying.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.database.models import OtpChallenge, User
from app.services import msg91

logger = logging.getLogger(__name__)

PURPOSE_REGISTER = "register"
PURPOSE_LOGIN = "login"

# Rolling-window send cap per (subject, purpose).
_HOURLY_SEND_CAP = 6
# pending-registration token lifetime (minutes).
REGISTER_TOKEN_MINUTES = 15
_REG_TOKEN_TYPE = "prp"  # claim distinguishing pending-registration tokens

# The widget provider all challenges are stored under.
PROVIDER = "msg91_widget"


class OtpError(HTTPException):
    """OTP-flow failure mapped to a clean HTTP error (no secrets)."""

    def __init__(self, status_code: int, detail: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Coerce DB datetimes to aware-UTC (SQLite returns naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _new_expiry(now: datetime) -> datetime:
    return now + timedelta(minutes=settings.MSG91_OTP_EXPIRY_MINUTES)


def _active_challenge(db: Session, subject: str, purpose: str) -> OtpChallenge | None:
    return db.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.subject == subject,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
            OtpChallenge.completed_at.is_(None),
            OtpChallenge.expires_at > _utcnow(),
        )
        .order_by(OtpChallenge.created_at.desc())
    )


def _count_recent_sends(db: Session, subject: str, purpose: str) -> int:
    """Sends in the rolling hour across ALL challenges for (subject, purpose).

    Summing request_count over every recent row (not just the active one)
    prevents resetting the cap by consuming/expiring challenges.
    """
    since = _utcnow() - timedelta(hours=1)
    rows = db.execute(
        select(OtpChallenge.request_count).where(
            OtpChallenge.subject == subject,
            OtpChallenge.purpose == purpose,
            OtpChallenge.first_requested_at > since,
        )
    ).scalars().all()
    return sum(int(n) for n in rows)


def request_otp(db: Session, *, purpose: str, subject: str, mobile: str) -> dict:
    """Create/refresh the OTP challenge for (subject, purpose) and trigger SMS.

    Returns {"mobile_masked", "cooldown_seconds", "expires_in_minutes"} —
    never the code itself (MSG91's widget generates and delivers it).
    """
    try:
        mobile = msg91.normalize_mobile(mobile)
    except ValueError as exc:
        raise OtpError(status.HTTP_400_BAD_REQUEST, str(exc))

    # Registration: the mobile must not belong to any account yet.
    if purpose == PURPOSE_REGISTER:
        if db.scalar(select(User.id).where(User.mobile == mobile)):
            raise OtpError(
                status.HTTP_409_CONFLICT,
                "This mobile number is already registered. Try logging in instead.",
            )

    now = _utcnow()
    challenge = _active_challenge(db, subject, purpose)

    # --- resend cooldown + rolling hourly cap -------------------------------
    if challenge is not None:
        elapsed = (_utcnow() - _as_utc(challenge.last_sent_at)).total_seconds()
        if elapsed < settings.MSG91_OTP_RESEND_COOLDOWN_SECONDS:
            retry_after = int(settings.MSG91_OTP_RESEND_COOLDOWN_SECONDS - elapsed)
            raise OtpError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Please wait {retry_after}s before requesting another OTP.",
                headers={"Retry-After": str(retry_after)},
            )
    if _count_recent_sends(db, subject, purpose) >= _HOURLY_SEND_CAP:
        if challenge is not None:
            challenge.last_error = "rate_limited"
            db.commit()
        raise OtpError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many OTP requests. Try again later.",
            headers={"Retry-After": "3600"},
        )

    if challenge is None:
        challenge = OtpChallenge(
            subject=subject,
            purpose=purpose,
            mobile=mobile,
            attempts_left=settings.MSG91_OTP_MAX_ATTEMPTS,
            request_count=1,
            first_requested_at=now,
            last_sent_at=now,
            expires_at=_new_expiry(now),
        )
        db.add(challenge)
    else:
        challenge.attempts_left = settings.MSG91_OTP_MAX_ATTEMPTS
        challenge.attempts_used = 0
        challenge.request_count += 1
        challenge.last_sent_at = now
        challenge.expires_at = _new_expiry(now)
        challenge.last_error = None
        challenge.mobile = mobile

    try:
        # The widget's default SMS configuration delivers the OTP; MSG91
        # returns an opaque request id used later for verification.
        request_id = msg91.send_otp_widget(mobile)
    except msg91.Msg91Error as exc:
        db.rollback()
        challenge = _active_challenge(db, subject, purpose)
        if challenge is not None:
            challenge.last_error = "provider_rejected"
            db.commit()
        logger.warning("OTP send failed for purpose=%s (%s)", purpose, exc)
        raise OtpError(
            status.HTTP_502_BAD_GATEWAY,
            "Could not send the OTP right now. Please try again shortly.",
        )

    challenge.provider_ref = request_id
    db.commit()
    return {
        "mobile_masked": msg91.mask_mobile(mobile),
        "cooldown_seconds": settings.MSG91_OTP_RESEND_COOLDOWN_SECONDS,
        "expires_in_minutes": settings.MSG91_OTP_EXPIRY_MINUTES,
    }


def verify_otp(db: Session, *, purpose: str, subject: str, code: str) -> OtpChallenge:
    """Verify `code` with MSG91's widget against the active challenge.

    The challenge is consumed on success. Wrong/expired/attempts-exhausted
    raise OtpError (401/410/403); provider outages raise 502.
    """
    challenge = _active_challenge(db, subject, purpose)
    if challenge is None:
        raise OtpError(status.HTTP_410_GONE, "No active OTP. Request a new one.")

    if not code or not code.strip().isdigit():
        challenge = _burn_attempt(db, challenge)
        raise OtpError(status.HTTP_401_UNAUTHORIZED, "Incorrect OTP")

    try:
        verified = msg91.verify_otp_widget(challenge.provider_ref or "", code.strip())
    except msg91.Msg91Error as exc:
        logger.warning("OTP provider verify failed for purpose=%s (%s)", purpose, exc)
        raise OtpError(
            status.HTTP_502_BAD_GATEWAY,
            "Verification service temporarily unavailable. Try again shortly.",
        )

    if not verified:
        challenge = _burn_attempt(db, challenge)
        if challenge.attempts_left <= 0:
            raise OtpError(status.HTTP_403_FORBIDDEN, "Too many incorrect attempts. Request a new OTP.")
        raise OtpError(status.HTTP_401_UNAUTHORIZED, "Incorrect OTP")

    challenge.consumed_at = _utcnow()
    db.commit()
    return challenge


def _burn_attempt(db: Session, challenge: OtpChallenge) -> OtpChallenge:
    """Consume one verification attempt; lock the challenge when exhausted."""
    challenge.attempts_left = max(0, challenge.attempts_left - 1)
    challenge.attempts_used += 1
    if challenge.attempts_left <= 0:
        challenge.consumed_at = _utcnow()
        challenge.last_error = "attempts_exhausted"
    db.commit()
    return challenge


def mint_pending_registration_token(mobile: str, invitation_code: str | None = None) -> str:
    """Single-use short-lived JWT carrying the verified mobile (+ invitation)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=REGISTER_TOKEN_MINUTES)
    payload = {
        "sub": mobile,
        "typ": _REG_TOKEN_TYPE,
        "exp": expire,
        "iss": "mineguardai",
    }
    if invitation_code:
        payload["inv"] = invitation_code
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def read_pending_registration_token(token: str) -> dict:
    """Decode the pending-registration JWT; OtpError on any problem."""
    credentials_error = OtpError(status.HTTP_401_UNAUTHORIZED, "Registration session expired. Start again.")
    try:
        payload = decode_token(token)
    except JWTError:
        raise credentials_error
    if payload.get("typ") != _REG_TOKEN_TYPE or not payload.get("sub"):
        raise credentials_error
    return payload


def mark_registration_completed(db: Session, mobile: str) -> None:
    """Delete register challenges for the mobile (single-use registration)."""
    db.execute(
        delete(OtpChallenge).where(OtpChallenge.subject == mobile, OtpChallenge.purpose == PURPOSE_REGISTER)
    )
    db.commit()


def cleanup_expired(db: Session) -> None:
    """Opportunistic deletion of stale challenges (older than 1 day)."""
    cutoff = _utcnow() - timedelta(days=1)
    db.execute(
        delete(OtpChallenge).where(
            OtpChallenge.expires_at < cutoff,
            OtpChallenge.consumed_at.is_(None),
        )
    )
    db.commit()
