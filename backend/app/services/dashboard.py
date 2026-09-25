"""Dashboard aggregation service (Phase 8). Every number comes from the database."""
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Alert,
    CameraEvent,
    CorrectiveAction,
    EnvironmentalReading,
    Incident,
    Inspection,
    Mine,
)
from app.services.risk import RiskAssessment, compute_all_risks, compute_risk as compute_all_risks_one

SEVERITY_ORDER = ["critical", "high", "medium", "low"]


class DashboardSummary(BaseModel):
    mines_total: int
    mines_operational: int
    alerts_active: int
    alerts_critical: int
    incidents_open: int
    inspections_pending: int
    actions_overdue: int
    actions_pending: int
    compliance_rate: float
    readings_24h: int
    camera_events_24h: int
    alerts_by_severity: dict[str, int]
    incidents_by_category: dict[str, int]
    camera_events_by_type: dict[str, int]
    readings_trend: list[dict[str, Any]]
    risk_distribution: dict[str, int]
    highest_risk_mines: list[dict[str, Any]]
    recent_alerts: list[dict[str, Any]]
    recent_camera_events: list[dict[str, Any]]
    recent_readings: list[dict[str, Any]]
    generated_at: datetime
    data_note: str


def _count(db: Session, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    return db.scalar(query) or 0


def _tally(rows: list[tuple[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {s: 0 for s in SEVERITY_ORDER}
    for key, n in rows:
        out[key] = n
    return out


def get_dashboard_summary(db: Session, mine_id: str | None = None, days: int = 7) -> DashboardSummary:
    """Aggregated overview. `mine_id` scopes counters to one mine; `days`
    sets the trend/compliance window (1, 7 or 30)."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    window_start = now - timedelta(days=days)

    # ---- headline counters ----
    mines_total = _count(db, Mine)
    mines_operational = _count(db, Mine, Mine.status == "operational")
    alerts_active = _count(db, Alert, Alert.status != "resolved")
    alerts_critical = _count(db, Alert, Alert.status != "resolved", Alert.severity == "critical")
    incidents_open = _count(db, Incident, Incident.status.in_(["open", "investigating", "action_required"]))
    inspections_pending = _count(db, Inspection, Inspection.status.in_(["scheduled", "in_progress"]))
    actions_overdue = _count(db, CorrectiveAction, CorrectiveAction.status == "overdue")
    actions_pending = _count(db, CorrectiveAction, CorrectiveAction.status == "pending")

    if mine_id:
        alerts_active = _count(db, Alert, Alert.status != "resolved", Alert.mine_id == mine_id)
        alerts_critical = _count(db, Alert, Alert.status != "resolved", Alert.severity == "critical", Alert.mine_id == mine_id)
        incidents_open = _count(db, Incident, Incident.status.in_(["open", "investigating", "action_required"]), Incident.mine_id == mine_id)
        inspections_pending = _count(db, Inspection, Inspection.status.in_(["scheduled", "in_progress"]), Inspection.mine_id == mine_id)

    # ---- compliance rate over the window ----
    reading_window = [EnvironmentalReading.recorded_at >= window_start]
    if mine_id:
        reading_window.append(EnvironmentalReading.mine_id == mine_id)
    total_week = _count(db, EnvironmentalReading, *reading_window)
    violations_week = _count(
        db, EnvironmentalReading, *reading_window, EnvironmentalReading.status == "violation",
    )
    compliance_rate = round(100.0 * (total_week - violations_week) / total_week, 1) if total_week else 100.0

    # ---- distributions (scoped to the mine filter when provided) ----
    alert_cond = [Alert.status != "resolved"]
    incident_cond = [Incident.status.in_(["open", "investigating", "action_required"])]
    event_cond = [CameraEvent.occurred_at >= window_start]
    if mine_id:
        alert_cond.append(Alert.mine_id == mine_id)
        incident_cond.append(Incident.mine_id == mine_id)
        event_cond.append(CameraEvent.mine_id == mine_id)

    alerts_by_severity = _tally(
        db.execute(
            select(Alert.severity, func.count()).where(*alert_cond).group_by(Alert.severity)
        ).all()
    )
    incidents_by_category = dict(
        db.execute(
            select(Incident.category, func.count()).where(*incident_cond).group_by(Incident.category)
        ).all()
    )
    camera_events_by_type = dict(
        db.execute(
            select(CameraEvent.event_type, func.count()).where(*event_cond).group_by(CameraEvent.event_type)
        ).all()
    )

    # ---- environmental trend: daily avg per parameter over the window ----
    trend_cond = [EnvironmentalReading.recorded_at >= window_start]
    if mine_id:
        trend_cond.append(EnvironmentalReading.mine_id == mine_id)
    readings_rows = db.execute(
        select(
            func.date(EnvironmentalReading.recorded_at).label("day"),
            EnvironmentalReading.parameter,
            func.round(func.avg(EnvironmentalReading.value), 1).label("avg_value"),
            func.count().label("n"),
        )
        .where(*trend_cond)
        .group_by("day", EnvironmentalReading.parameter)
        .order_by("day")
    ).all()
    readings_trend = [
        {"date": str(r.day), "parameter": r.parameter, "avg_value": float(r.avg_value), "count": r.n}
        for r in readings_rows
    ]

    # ---- risk distribution (scoped when mine filter is active) ----
    if mine_id:
        mine = db.get(Mine, mine_id)
        risks = [compute_all_risks_one(db, mine)] if mine else []
    else:
        risks = compute_all_risks(db)
    risk_distribution = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for r in risks:
        risk_distribution[r.level] += 1
    highest_risk_mines = [
        {"mine_id": r.mine_id, "mine_name": r.mine_name, "score": r.score, "level": r.level}
        for r in sorted(risks, key=lambda x: x.score, reverse=True)[:5]
    ]

    # ---- recent activity ----
    recent_alert_cond = []
    recent_event_cond = []
    if mine_id:
        recent_alert_cond.append(Alert.mine_id == mine_id)
        recent_event_cond.append(CameraEvent.mine_id == mine_id)
    recent_alerts_rows = db.scalars(
        select(Alert).where(*recent_alert_cond).order_by(Alert.created_at.desc()).limit(8)
    ).all()
    recent_alerts = [
        {
            "id": a.id, "mine_id": a.mine_id, "title": a.title, "severity": a.severity,
            "status": a.status, "alert_type": a.alert_type, "source": a.source,
            "created_at": a.created_at.isoformat(),
        }
        for a in recent_alerts_rows
    ]

    recent_events_rows = db.scalars(
        select(CameraEvent).where(*recent_event_cond).order_by(CameraEvent.occurred_at.desc()).limit(8)
    ).all()
    recent_camera_events = [
        {
            "id": e.id, "mine_id": e.mine_id, "event_type": e.event_type,
            "zone_label": e.zone_label, "camera_id": e.camera_id,
            "confidence": e.confidence, "severity": e.severity, "status": e.status,
            "detection_source": e.detection_source, "occurred_at": e.occurred_at.isoformat(),
        }
        for e in recent_events_rows
    ]

    recent_readings_rows = db.scalars(
        select(EnvironmentalReading)
        .where(EnvironmentalReading.recorded_at >= day_ago)
        .order_by(EnvironmentalReading.recorded_at.desc())
        .limit(10)
    ).all()
    recent_readings = [
        {
            "id": rd.id, "mine_id": rd.mine_id, "parameter": rd.parameter,
            "value": rd.value, "unit": rd.unit, "threshold": rd.threshold,
            "status": rd.status, "recorded_at": rd.recorded_at.isoformat(),
        }
        for rd in recent_readings_rows
    ]

    return DashboardSummary(
        mines_total=mines_total,
        mines_operational=mines_operational,
        alerts_active=alerts_active,
        alerts_critical=alerts_critical,
        incidents_open=incidents_open,
        inspections_pending=inspections_pending,
        actions_overdue=actions_overdue,
        actions_pending=actions_pending,
        compliance_rate=compliance_rate,
        readings_24h=_count(db, EnvironmentalReading, EnvironmentalReading.recorded_at >= day_ago),
        camera_events_24h=_count(db, CameraEvent, CameraEvent.occurred_at >= day_ago),
        alerts_by_severity=alerts_by_severity,
        incidents_by_category=incidents_by_category,
        camera_events_by_type=camera_events_by_type,
        readings_trend=readings_trend,
        risk_distribution=risk_distribution,
        highest_risk_mines=highest_risk_mines,
        recent_alerts=recent_alerts,
        recent_camera_events=recent_camera_events,
        recent_readings=recent_readings,
        generated_at=now,
        data_note="All figures derive from SIMULATED demo data stored in the database.",
    )
