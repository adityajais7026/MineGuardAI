"""Deterministic, explainable mine risk scoring.

NO opaque AI: the score is a weighted sum of measurable factors, and every
contribution is returned so the UI can show WHY the score is what it is.
Weights live in FACTOR_WEIGHTS and may be tuned; the algorithm itself stays
deterministic so the same mine state always yields the same score.

Bands: low <25, medium 25-49, high 50-74, critical >=75 (of 100).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Alert,
    CorrectiveAction,
    EmergencyEvent,
    Incident,
    Inspection,
    Mine,
)

FACTOR_WEIGHTS = {
    "overdue_actions": 20.0,
    "failed_inspections": 15.0,
    "environmental_alerts": 15.0,
    "open_emergencies": 15.0,
}


def _band(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def compute_mine_risk(db: Session, mine_id: str) -> dict:
    """Compute the risk score for one mine. Returns score, band and factors."""
    factors: list[dict] = []
    total = 0.0
    now = datetime.now(timezone.utc)

    # --- Overdue corrective actions (heaviest weight) ---
    action_rows = db.execute(
        select(CorrectiveAction, Incident.mine_id, Inspection.mine_id)
        .join(Incident, CorrectiveAction.incident_id == Incident.id, isouter=True)
        .join(Inspection, CorrectiveAction.inspection_id == Inspection.id, isouter=True)
        .where(CorrectiveAction.status.notin_(("completed", "overdue")))
    ).all()
    n_overdue = 0
    for action, inc_mine_id, insp_mine_id in action_rows:
        mine = inc_mine_id or insp_mine_id
        if mine != mine_id:
            continue
        due = action.due_date
        if due.tzinfo is None:
            from datetime import timezone as _tz
            due = due.replace(tzinfo=_tz.utc)
        if due < now:
            n_overdue += 1
    pts = min(FACTOR_WEIGHTS["overdue_actions"], n_overdue * 5.0)
    if pts:
        factors.append({"factor": "overdue_actions", "points": pts, "detail": f"{n_overdue} overdue corrective action(s)"})
        total += pts

    # --- Failed inspections (last 30 days) ---
    failed = db.execute(
        select(func.count(Inspection.id)).where(
            Inspection.mine_id == mine_id,
            Inspection.compliance_result == "non_compliant",
            Inspection.completed_at >= now - timedelta(days=30),
        )
    ).scalar() or 0
    pts = min(FACTOR_WEIGHTS["failed_inspections"], failed * 5.0)
    if pts:
        factors.append({"factor": "failed_inspections", "points": pts, "detail": f"{failed} non-compliant inspection(s) in 30d"})
        total += pts

    # --- Active alerts (last 7 days) ---
    env_alerts = db.execute(
        select(func.count(Alert.id)).where(
            Alert.mine_id == mine_id,
            Alert.created_at >= now - timedelta(days=7),
            Alert.status == "active",
        )
    ).scalar() or 0
    pts = min(FACTOR_WEIGHTS["environmental_alerts"], env_alerts * 5.0)
    if pts:
        factors.append({"factor": "environmental_alerts", "points": pts, "detail": f"{env_alerts} active alert(s) in 7d"})
        total += pts

    # --- Open emergencies ---
    emergencies = db.execute(
        select(func.count(EmergencyEvent.id)).where(
            EmergencyEvent.mine_id == mine_id,
            EmergencyEvent.status.in_(("open", "responding")),
        )
    ).scalar() or 0
    pts = min(FACTOR_WEIGHTS["open_emergencies"], emergencies * 7.5)
    if pts:
        factors.append({"factor": "open_emergencies", "points": pts, "detail": f"{emergencies} open emergency event(s)"})
        total += pts

    score = round(min(100.0, total), 1)
    return {"mine_id": mine_id, "score": score, "band": _band(score), "factors": factors}


def compute_all_mine_risk(db: Session) -> list[dict]:
    """Risk score for every mine (used by dashboards)."""
    mine_ids = db.execute(select(Mine.id)).scalars().all()
    return [compute_mine_risk(db, mid) for mid in mine_ids]
