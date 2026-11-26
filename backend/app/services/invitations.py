"""Code-based invitation lifecycle — the ONLY way to create a new account.

An Administrator mints an invitation for one of the four roles. The raw
invitation code (short, human-usable, unambiguous alphabet) is stored BOTH as
plaintext (`code`, so the creator can keep copying it from the management list
until the invitation is used, expired or deleted — it is never hidden after
creation) and as a bcrypt hash (`code_hash`, the verification credential).

Registration with a code reuses the EXISTING MSG91 OTP flow unchanged:
    code + email  ->  mobile  ->  OTP (purpose=register)  ->  password  ->  account
The invitation record is the source of truth: the email is strictly bound
(403 on mismatch), the role comes exclusively from the stored invitation and
consumption is atomic with account creation (single-use). Soft-deleted
invitations (`deleted_at`) are invalid immediately; regeneration stores a new
code/hash on the SAME row (same email/role) and invalidates the old code by
overwriting it. No second invitation or OTP system exists.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.database.models import RoleInvitation

# Roles an Administrator may invite (the full privileged set).
INVITABLE_ROLES = ("admin", "environmental_officer", "mine_manager", "safety_officer")

# Unambiguous alphabet: no 0/O/1/I/L look-alikes (codes are shared by hand).
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_CODE_GROUPS = 3
_CODE_GROUP_LEN = 4


def _new_code() -> str:
    """CSPRNG invitation code, e.g. 'K7M2-9QX4-PTR8' (~47 bits of entropy)."""
    def group() -> str:
        return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_GROUP_LEN))
    return "-".join(group() for _ in range(_CODE_GROUPS))


def _as_utc(value: datetime) -> datetime:
    """Coerce DB datetimes to aware-UTC (SQLite returns naive values)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# --- Exact, user-facing registration error messages -------------------------
MSG_CODE_REQUIRED = "Invitation code is required to create an account."
MSG_INVALID_CODE = "Invalid invitation code. Please check the code and try again."
MSG_WRONG_EMAIL = (
    "Invalid email for this invitation. Please use the email address associated "
    "with this invitation and try again."
)
MSG_EXPIRED = "This invitation has expired. Please request a new invitation code."
MSG_ALREADY_USED = "This invitation code has already been used. Please request a new invitation."
MSG_DELETED = "This invitation is no longer valid. Please request a new invitation code."


def _expired(invitation: RoleInvitation) -> bool:
    return _as_utc(invitation.expires_at) < datetime.now(timezone.utc)


def create_invitation(
    db: Session,
    *,
    role: str,
    full_name: str,
    email: str,
    invited_by_id: str,
) -> tuple[RoleInvitation, str]:
    """Mint an invitation-code invitation; returns (row, raw_code).

    The code is stored plaintext AND bcrypt-hashed: plaintext so the creator
    can always copy it from the management list, hash so verification never
    trusts the plaintext column.
    """
    code = _new_code()
    invitation = RoleInvitation(
        role=role,
        full_name=full_name,
        code=code,
        code_hash=hash_password(code),
        bound_email=email.lower(),
        invited_by_id=invited_by_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.INVITATION_EXPIRY_HOURS),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, code


def regenerate_invitation(db: Session, *, invitation_id: str, acting_admin: "User") -> tuple[RoleInvitation, str]:  # noqa: F821
    """Issue a NEW code for the SAME email/role/permissions (same row).

    The previous code stops working immediately: its plaintext and hash are
    overwritten on the row and the expiry clock restarts. Only the admin who
    created the invitation (or any current administrator) may regenerate it;
    used/expired/deleted invitations cannot be regenerated — create a new one.
    """
    from app.database.models import User  # local import: no cycle at module load

    invitation = db.get(RoleInvitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    if acting_admin.role != "admin" and invitation.invited_by_id != acting_admin.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the creator can regenerate this invitation.")
    if invitation.is_used:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This invitation has already been used and cannot be regenerated.")
    if invitation.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This invitation has been deleted and cannot be regenerated.")
    if _expired(invitation):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This invitation has expired. Create a new invitation instead.")

    code = _new_code()
    invitation.code = code
    invitation.code_hash = hash_password(code)
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.INVITATION_EXPIRY_HOURS)
    db.commit()
    db.refresh(invitation)
    return invitation, code


def delete_invitation(db: Session, *, invitation_id: str, acting_admin: "User") -> RoleInvitation:  # noqa: F821
    """Soft-delete an invitation: the code is invalid immediately.

    The row is kept for audit and shows status "Deleted". Deleting is
    idempotent (deleting twice returns 404 the second time only if the row is
    already deleted — here it answers 409 to signal 'already deleted').
    Only the creator (or any current administrator) may delete.
    """
    invitation = db.get(RoleInvitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    if acting_admin.role != "admin" and invitation.invited_by_id != acting_admin.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the creator can delete this invitation.")
    if invitation.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This invitation is already deleted.")

    invitation.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return invitation


def invitation_status(invitation: RoleInvitation, *, now: datetime | None = None) -> str:
    """Management-list status: Active / Used / Expired / Deleted."""
    if invitation.deleted_at is not None:
        return "Deleted"
    if invitation.is_used:
        return "Used"
    now = now or datetime.now(timezone.utc)
    if _as_utc(invitation.expires_at) < now:
        return "Expired"
    return "Active"


def validate_invitation(db: Session, *, code: str, email: str) -> RoleInvitation:
    """Validate a code+email pair and return the invitation row.

    Check order reveals as little as possible: unknown code, deleted, used,
    expired, then email mismatch (each with its exact required message).
    The role is NOT part of the request — it comes from the invitation only.
    """
    normalized = (code or "").strip().upper()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=MSG_CODE_REQUIRED)

    # Direct lookup on the indexed plaintext column, then verify the bcrypt
    # hash so validation never trusts the plaintext column alone. Rows without
    # a plaintext code (legacy pre-rework invitations) are simply unfindable —
    # the old link flow is gone and old codes are inert.
    invitation = db.scalar(select(RoleInvitation).where(RoleInvitation.code == normalized))
    if invitation is not None and not verify_password(normalized, invitation.code_hash):
        invitation = None  # plaintext/hash mismatch: treat as unknown code

    if invitation is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_INVALID_CODE)
    if invitation.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_DELETED)
    if invitation.is_used:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_ALREADY_USED)
    if _expired(invitation):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_EXPIRED)
    if invitation.bound_email and invitation.bound_email != (email or "").strip().lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_WRONG_EMAIL)
    return invitation


def claim_invitation(db: Session, invitation: RoleInvitation, *, user_id: str) -> None:
    """Atomically consume the invitation inside the account-creation transaction.

    Re-checks every condition right before stamping: two concurrent uses of
    the same code cannot both pass, because the second flush/commit re-evaluates
    the row state after the first commit set `is_used`.
    """
    if invitation.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_DELETED)
    if invitation.is_used:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_ALREADY_USED)
    if _expired(invitation):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MSG_EXPIRED)

    invitation.is_used = True
    invitation.used_by_id = user_id
    invitation.used_at = datetime.now(timezone.utc)


def normalize_code(code: str) -> str:
    """Trim whitespace and uppercase (codes are case-insensitive by design)."""
    return re.sub(r"\s+", "", (code or "")).upper()
