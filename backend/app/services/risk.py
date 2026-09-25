"""
Risk classification (Phase 6).

Transparent, rule-based scoring — NOT machine learning, NOT a scientifically
validated safety model. The formula below is a documented project heuristic
that combines weighted system signals into a 0-100 score.

Formula (all weights sum to 100):
    environmental violations (last 7 days) ........... 20
        2 points per violation, capped at 20
    active alerts (status != resolved) ............... 25
        critical=8, high=5, medium=2, low=1, capped at 25
    open incidents (not resolved/closed) ............. 20
        critical=8, high=5, medium=2, low=1, capped at 20
    inspections (last 30 days) ....................... 15
        non_compliant=10, partial=5, compliant=0, capped at 15
    overdue corrective actions ....................... 15
        5 points each, capped at 15
    in-progress actions (mild signal) ................ 5
        1 point each, capped at 5

Level bands: 0-24 LOW, 25-49 MEDIUM, 50-74 HIGH, 75-100 CRITICAL.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Alert,
    CorrectiveAction,
    EnvironmentalReading,
    Incident,
    Inspection,
    Mine,
)

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

SEVERITY_POINTS = {"critical": 8, "high": 5, "medium": 2, "low": 1}
INSPECTION_POINTS = {"non_compliant": 10, "partial": 5, "compliant": 0, "pending": 0}

WEIGHTS = {
    "environmental_violations": 20,
    "active_alerts": 25,
    "open_incidents": 20,
    "inspection_results": 15,
    "overdue_actions": 15,
    "in_progress_actions": 5,
}

LEVEL_BANDS = [(75, "CRITICAL"), (50, "HIGH"), (25, "MEDIUM"), (0, "LOW")]


def score_to_level(score: int) -> RiskLevel:
    for floor, level in LEVEL_BANDS:
        if score >= floor:
            return level
    return "LOW"  # unreachable; keeps type-checkers happy


class RiskFactor(BaseModel):
    factor: str
    points: int
    max_points: int
    detail: str


class RiskAssessment(BaseModel):
    mine_id: str
    mine_name: str
    score: int
    level: RiskLevel
    factors: list[RiskFactor]
    counts: dict[str, int]
    disclaimer: str


def _cap(value: int, maximum: int) -> int:
    return min(value, maximum)


def compute_risk(db: Session, mine: Mine) -> RiskAssessment:
    """Deterministic, explainable risk assessment for one mine."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    violations = db.scalar(
        select(func.count()).select_from(EnvironmentalReading).where(
            EnvironmentalReading.mine_id == mine.id,
            EnvironmentalReading.status == "violation",
            EnvironmentalReading.recorded_at >= week_ago,
        )
    ) or 0

    open_alerts = db.scalars(
        select(Alert).where(Alert.mine_id == mine.id, Alert.status != "resolved")
    ).all()
    alerts_points = _cap(sum(SEVERITY_POINTS.get(a.severity, 1) for a in open_alerts), WEIGHTS["active_alerts"])

    open_incidents = db.scalars(
        select(Incident).where(
            Incident.mine_id == mine.id, Incident.status.in_(["open", "investigating", "action_required"])
        )
    ).all()
    incidents_points = _cap(sum(SEVERITY_POINTS.get(i.severity, 1) for i in open_incidents), WEIGHTS["open_incidents"])

    inspections = db.scalars(
        select(Inspection).where(
            Inspection.mine_id == mine.id,
            Inspection.completed_at >= month_ago,
            Inspection.status == "completed",
        )
    ).all()
    inspections_points = _cap(
        sum(INSPECTION_POINTS.get(ins.compliance_result, 0) for ins in inspections),
        WEIGHTS["inspection_results"],
    )

    overdue = db.scalar(
        select(func.count()).select_from(CorrectiveAction).where(
            (CorrectiveAction.incident_id.in_(select(Incident.id).where(Incident.mine_id == mine.id)))
            | (CorrectiveAction.inspection_id.in_(select(Inspection.id).where(Inspection.mine_id == mine.id))),
            CorrectiveAction.status == "overdue",
        )
    ) or 0
    in_progress = db.scalar(
        select(func.count()).select_from(CorrectiveAction).where(
            (CorrectiveAction.incident_id.in_(select(Incident.id).where(Incident.mine_id == mine.id)))
            | (CorrectiveAction.inspection_id.in_(select(Inspection.id).where(Inspection.mine_id == mine.id))),
            CorrectiveAction.status == "in_progress",
        )
    ) or 0

    factors = [
        RiskFactor(factor="environmental_violations", points=_cap(violations * 2, 20), max_points=20,
                   detail=f"{violations} violation reading(s) in the last 7 days (2 pts each)"),
        RiskFactor(factor="active_alerts", points=alerts_points, max_points=25,
                   detail=f"{len(open_alerts)} unresolved alert(s), weighted by severity"),
        RiskFactor(factor="open_incidents", points=incidents_points, max_points=20,
                   detail=f"{len(open_incidents)} open incident(s), weighted by severity"),
        RiskFactor(factor="inspection_results", points=inspections_points, max_points=15,
                   detail=f"{len(inspections)} completed inspection(s) in the last 30 days"),
        RiskFactor(factor="overdue_actions", points=_cap(overdue * 5, 15), max_points=15,
                   detail=f"{overdue} overdue corrective action(s) (5 pts each)"),
        RiskFactor(factor="in_progress_actions", points=_cap(in_progress * 1, 5), max_points=5,
                   detail=f"{in_progress} in-progress corrective action(s) (1 pt each)"),
    ]

    score = sum(f.points for f in factors)
    counts = {
        "environmental_violations_7d": violations,
        "active_alerts": len(open_alerts),
        "open_incidents": len(open_incidents),
        "inspections_30d": len(inspections),
        "overdue_actions": overdue,
        "in_progress_actions": in_progress,
    }
    return RiskAssessment(
        mine_id=mine.id, mine_name=mine.name, score=score, level=score_to_level(score),
        factors=factors, counts=counts,
        disclaimer=(
            "Project risk-scoring heuristic based on recorded system data. "
            "Not machine learning and not a scientifically validated safety model."
        ),
    )


def compute_all_risks(db: Session) -> list[RiskAssessment]:
    mines = db.scalars(select(Mine)).all()
    return [compute_risk(db, m) for m in mines]
