"""SLA / overdue computation for corrective actions (lazy, no daemon).

Overdue status is computed on read and persisted opportunistically in the
same transaction when actions are listed/updated. Escalation notifications
are created through the notifications service with dedupe keys so repeated
sweeps never spam the same recipient.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import CorrectiveAction, Notification


def is_overdue(action: CorrectiveAction, now: datetime | None = None) -> bool:
    if action.status in ("completed", "overdue"):
        return False
    now = now or datetime.now(timezone.utc)
    due = action.due_date
    if due.tzinfo is None:
        from datetime import timezone as _tz
        due = due.replace(tzinfo=_tz.utc)
    return due < now


def refresh_overdue_flags(db: Session, actions: list[CorrectiveAction]) -> int:
    """Persist overdue status for the given actions. Returns count changed."""
    changed = 0
    for a in actions:
        if is_overdue(a) and a.status != "overdue":
            a.status = "overdue"
            changed += 1
    if changed:
        db.commit()
    return changed


def escalate_overdue(db: Session, now: datetime | None = None) -> list[Notification]:
    """Create escalation notifications for overdue high/critical actions.

    Deduped per (action, escalation level) via Notification.dedupe_key, so
    calling this repeatedly is safe. Returns newly created notifications.
    """
    now = now or datetime.now(timezone.utc)
    actions = db.execute(
        select(CorrectiveAction).where(
            CorrectiveAction.status.in_(("overdue", "pending", "in_progress")),
            CorrectiveAction.priority.in_(("high", "critical")),
        )
    ).scalars().all()
    created: list[Notification] = []
    for a in actions:
        if not is_overdue(a, now):
            continue
        if a.status != "overdue":
            a.status = "overdue"
        dedupe = f"action:{a.id}:overdue"
        exists = db.execute(
            select(Notification).where(Notification.dedupe_key == dedupe)
        ).scalar_one_or_none()
        if exists:
            continue
        n = Notification(
            user_id=a.assigned_to_id,
            category="overdue_action",
            title=f"Overdue {a.priority} corrective action",
            body=a.description[:500],
            severity="critical" if a.priority == "critical" else "high",
            entity_type="corrective_action",
            entity_id=a.id,
            dedupe_key=dedupe,
        )
        db.add(n)
        created.append(n)
    if created:
        db.commit()
    return created
