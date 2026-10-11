"""Inspection workflow service: templates -> snapshot -> checklist -> submit.

Template items are SNAPSHOTTED into inspection_checklist_items at creation
time, so later template edits never rewrite what was actually asked.
Checklist results are pass|fail|na|unknown; 'unknown' is no-evidence, never
a violation. Compliance roll-up is a mechanical aggregation of item results
and never overrides an inspector's judgement.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Inspection, InspectionChecklistItem, InspectionTemplate, InspectionTemplateItem

VALID_RESULTS = {"pass", "fail", "na", "unknown"}

# Maps checklist item results to inspection compliance_result.
# fail -> non_compliant; unknown -> pending (insufficient evidence, NOT a fail);
# otherwise all pass/na -> compliant.
RESULT_TO_COMPLIANCE = {
    "fail": "non_compliant",
    "pass": "compliant",
    "na": "compliant",
    "unknown": "pending",
}


def get_template(db: Session, template_id: str) -> InspectionTemplate | None:
    return db.get(InspectionTemplate, template_id)


def snapshot_template(db: Session, inspection: Inspection, template: InspectionTemplate) -> list[InspectionChecklistItem]:
    """Copy template items onto the inspection (append; idempotent per template)."""
    existing = db.execute(
        select(InspectionChecklistItem).where(InspectionChecklistItem.inspection_id == inspection.id)
    ).scalars().all()
    if existing:
        return list(existing)

    items = db.execute(
        select(InspectionTemplateItem)
        .where(InspectionTemplateItem.template_id == template.id)
        .order_by(InspectionTemplateItem.position)
    ).scalars().all()
    created = []
    for it in items:
        row = InspectionChecklistItem(
            inspection_id=inspection.id,
            template_item_id=it.id,
            position=it.position,
            label=it.label,
            category=it.category,
            result_options=it.result_options,
            severity_weight=it.severity_weight,
        )
        db.add(row)
        created.append(row)
    db.commit()
    return created


def apply_checklist_results(db: Session, inspection_id: str, results: dict[str, dict]) -> list[InspectionChecklistItem]:
    """Apply {checklist_item_id: {result, comment?, ai_suggestion?...}} to items.

    Only items belonging to this inspection are updated; invalid results are
    rejected with ValueError so bad data never lands in the audit chain.
    """
    items = db.execute(
        select(InspectionChecklistItem).where(InspectionChecklistItem.inspection_id == inspection_id)
    ).scalars().all()
    by_id = {i.id: i for i in items}
    for item_id, payload in (results or {}).items():
        item = by_id.get(item_id)
        if item is None:
            raise ValueError(f"checklist item {item_id} does not belong to inspection {inspection_id}")
        result = payload.get("result")
        if result is not None:
            if result not in VALID_RESULTS:
                raise ValueError(f"invalid result '{result}' for item {item_id}")
            allowed = set((item.result_options or "").split(","))
            if result not in allowed:
                raise ValueError(f"result '{result}' not allowed for item {item_id} (options: {item.result_options})")
            item.result = result
        if "comment" in payload:
            item.comment = payload.get("comment")
        if "ai_suggestion" in payload:
            sug = payload.get("ai_suggestion")
            if sug is not None and sug not in VALID_RESULTS:
                raise ValueError(f"invalid ai_suggestion '{sug}'")
            item.ai_suggestion = sug
    db.commit()
    return items


def rollup_compliance(items: list[InspectionChecklistItem]) -> str:
    """Mechanical roll-up: any fail -> non_compliant; any unknown (with no fail) -> pending; else compliant."""
    results = [i.result for i in items if i.result is not None]
    if not results:
        return "pending"
    if "fail" in results:
        return "non_compliant"
    if "unknown" in results:
        return "pending"
    return "compliant"


# ---------------------------------------------------------------------------
# Review / approval lifecycle (additive column `inspections.review_status`)
#
# Transition rules follow the EXISTING RBAC hierarchy — no new roles:
#   draft / in_progress / submit            any user with inspections write
#                                           (safety_officer, mine_manager)
#   under_review / approved / rejected /
#   closed                                  mine_manager (of the scoped mine)
#                                           or admin
#
# An inspector may never approve their own inspection (segregation of duties):
# the author is always allowed to submit, never to approve/reject.
# ---------------------------------------------------------------------------

REVIEW_STATUSES = ["draft", "in_progress", "submitted", "under_review", "approved", "rejected", "closed"]

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    None: {"draft", "in_progress", "submitted"},
    "draft": {"in_progress", "submitted"},
    "in_progress": {"submitted"},
    "submitted": {"under_review", "rejected"},
    "under_review": {"approved", "rejected", "submitted"},
    "rejected": {"in_progress", "submitted"},
    "approved": {"closed"},
    "closed": set(),
}

REVIEWER_ACTIONS = {"under_review", "approved", "rejected", "closed"}


def validate_review_transition(
    *,
    current: str | None,
    target: str,
    user_role: str,
    is_scoped_manager: bool,
    is_author: bool,
) -> None:
    """Raise ValueError with a safe message if the transition is not allowed."""
    if target not in REVIEW_STATUSES:
        raise ValueError(f"Unknown review_status '{target}'.")
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"Cannot move review_status from '{current or 'new'}' to '{target}'.")
    if target in REVIEWER_ACTIONS and not (is_scoped_manager or user_role == "admin"):
        raise ValueError(
            "Only the mine manager (or an administrator) can perform review decisions "
            f"('{target}')."
        )
    if is_author and target in {"approved", "rejected"}:
        raise ValueError("An inspector cannot approve or reject their own inspection.")
