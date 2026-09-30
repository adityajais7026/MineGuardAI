"""Administrator-only permanent user deletion.

The existing soft-delete (PATCH is_active=False) stays untouched; this service
adds hard deletion for eligible accounts, used by the "Delete Permanently"
action in User Management.

Deletion policy (matches the schema's own FK design — every FK referencing
users is ON DELETE SET NULL, so operational history is preserved and
de-attributed rather than destroyed):

  * Guards: an Administrator can never delete themselves; the last/only active
    Administrator can never be deleted.
  * Deleted outright (user-owned, single-use credentials):
      - the user row itself
      - the user's PENDING (unused) role_invitations — a deleted admin must
        not leave active invitation links behind. Used invitations survive
        (audit) and their invited_by/used_by references are nulled by FK.
      - the user's OTP challenges (login challenges keyed by user id;
        register challenges keyed by their mobile — the mobile is being freed)
  * Detached, never deleted (shared/system data preserved via ON DELETE
    SET NULL): mines they manage, incidents they reported, inspections they
    led, alerts and corrective actions assigned to them.
  * Unique email/mobile are freed automatically by removing the row, so the
    identity can be re-registered or re-invited.
  * Everything runs in ONE transaction; any failure rolls the whole
    deletion back (no partial deletes).
"""
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.database.models import (
    Alert,
    CorrectiveAction,
    Inspection,
    Incident,
    Mine,
    OtpChallenge,
    RoleInvitation,
    User,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _count(db: Session, stmt) -> int:
    return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def scan_user_impact(db: Session, user: User) -> dict:
    """Read-only report of what would be affected by deleting `user`.

    Returned to the Administrator BEFORE deletion so the exact account (id,
    email, role, status) and the affected references are confirmed. Nothing is
    deleted here. Rows counted below are DETACHED (SET NULL), not destroyed.
    """
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "has_mobile": user.mobile is not None,
        "has_password": user.hashed_password is not None,
        "affected": {
            "mines_managed": _count(db, select(Mine).where(Mine.manager_id == user.id)),
            "incidents_reported": _count(db, select(Incident).where(Incident.reported_by_id == user.id)),
            "inspections_led": _count(db, select(Inspection).where(Inspection.inspector_id == user.id)),
            "alerts_assigned": _count(db, select(Alert).where(Alert.assigned_to_id == user.id)),
            "corrective_actions_assigned": _count(
                db, select(CorrectiveAction).where(CorrectiveAction.assigned_to_id == user.id)
            ),
            "pending_invitations_to_revoke": _count(
                db,
                select(RoleInvitation).where(
                    RoleInvitation.invited_by_id == user.id, RoleInvitation.is_used.is_(False)
                ),
            ),
        },
    }


def _assert_deletable(db: Session, target: User, acting_admin: User) -> None:
    # Guard order: self-deletion is rejected first — it is the most personal,
    # always-true rule (an Administrator can never delete themselves).
    if target.id == acting_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )
    if target.role == "admin":
        other_active_admins = (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "admin", User.id != target.id, User.is_active.is_(True))
            )
            or 0
        )
        if other_active_admins == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last active Administrator. Invite another Administrator first.",
            )


def delete_user_permanently(db: Session, *, target_id: str, acting_admin: User) -> dict:
    """Permanently delete `target_id` with all guards applied.

    Returns a report of what was deleted and what was detached. Raises 404 for
    unknown users and 400 when a guard (self-delete / last-admin) fails.
    """
    target = db.get(User, target_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _assert_deletable(db, target, acting_admin)

    report: dict = {
        "user_id": target.id,
        "email": target.email,
        "role": target.role,
        "detached": scan_user_impact(db, target)["affected"],
        "deleted": {},
    }

    # 1) Revoke the user's outstanding (unused) invitations. A deleted admin
    #    must not leave live invitation links; used ones stay for audit.
    pending_revoked = db.execute(
        delete(RoleInvitation).where(
            RoleInvitation.invited_by_id == target.id, RoleInvitation.is_used.is_(False)
        )
    )
    report["deleted"]["pending_invitations_revoked"] = pending_revoked.rowcount or 0

    # 2) Drop the user's OTP challenges (their mobile is being freed; stale
    #    login/register challenges must not outlive the account).
    otp_conditions = [OtpChallenge.subject == target.id]
    if target.mobile:
        otp_conditions.append(OtpChallenge.mobile == target.mobile)
    otp_deleted = db.execute(delete(OtpChallenge).where(or_(*otp_conditions)))
    report["deleted"]["otp_challenges"] = otp_deleted.rowcount or 0

    # 3) Delete the account. All other references (mines.manager_id,
    #    incidents.reported_by_id, inspections.inspector_id,
    #    alerts.assigned_to_id, corrective_actions.assigned_to_id,
    #    role_invitations.invited_by_id/used_by_id) are ON DELETE SET NULL:
    #    shared/system records survive, de-attributed.
    user_deleted = db.execute(delete(User).where(User.id == target.id))
    report["deleted"]["user"] = user_deleted.rowcount or 0

    db.commit()
    return report
