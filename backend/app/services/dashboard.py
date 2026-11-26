"""Dashboard aggregation service (Phase 8). Every number comes from the database."""
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Numeric, cast, func, select
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


def _mine_cond(mine_col, mine_id: str | None, allowed: list[str] | None):
    """Mine filter expression for a model column; exact mine wins over scope."""
    if mine_id:
        return mine_col == mine_id
    if allowed is not None:
        return mine_col.in_(allowed or ["__none__"])
    return None


def _count_mine_scoped(db: Session, model, base_cond, mine_col, mine_id: str | None, allowed: list[str] | None) -> int:
    """_count with combined mine filter: exact mine_id, else user scope, else all."""
    if base_cond is None:
        base = []
    elif isinstance(base_cond, (list, tuple)):
        base = list(base_cond)
    else:
        base = [base_cond]
    cond = base
    mc = _mine_cond(mine_col, mine_id, allowed)
    if mc is not None:
        cond.append(mc)
    return _count(db, model, *cond)


def _count_actions_scoped(db: Session, status_value: str, mine_id: str | None, allowed: list[str] | None) -> int:
    """Count corrective actions with a status, scoped via their incident/inspection mine."""
    cond = [CorrectiveAction.status == status_value]
    mc_inc = _mine_cond(Incident.mine_id, mine_id, allowed)
    mc_insp = _mine_cond(Inspection.mine_id, mine_id, allowed)
    if mc_inc is not None or mc_insp is not None:
        scope = CorrectiveAction.incident_id.in_(
            select(Incident.id).where(mc_inc if mc_inc is not None else Incident.mine_id.is_not(None))
        ) | CorrectiveAction.inspection_id.in_(
            select(Inspection.id).where(mc_insp if mc_insp is not None else Inspection.mine_id.is_not(None))
        )
        cond.append(scope)
    return _count(db, CorrectiveAction, *cond)


def get_dashboard_summary(
        db: Session, mine_id: str | None = None, days: int = 7, allowed_mine_ids: list[str] | None = None) -> DashboardSummary:
    """Aggregated overview. `mine_id` scopes counters to one mine; `days`
    sets the trend/compliance window (1, 7 or 30). `allowed_mine_ids`
    (None = admin/all) further restricts org-wide numbers to the user's scope."""
    scope_allowed = allowed_mine_ids if mine_id is None else None
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    window_start = now - timedelta(days=days)

    # ---- headline counters ----
    mines_total = _count_mine_scoped(db, Mine, [], Mine.id, mine_id, scope_allowed)
    mines_operational = _count_mine_scoped(db, Mine, [Mine.status == "operational"], Mine.id, mine_id, scope_allowed)
    alerts_active = _count_mine_scoped(db, Alert, [Alert.status != "resolved"], Alert.mine_id, mine_id, scope_allowed)
    alerts_critical = _count_mine_scoped(db, Alert, [Alert.status != "resolved", Alert.severity == "critical"], Alert.mine_id, mine_id, scope_allowed)
    incidents_open = _count_mine_scoped(db, Incident, Incident.status.in_(["open", "investigating", "action_required"]), Incident.mine_id, mine_id, scope_allowed)
    inspections_pending = _count_mine_scoped(db, Inspection, Inspection.status.in_(["scheduled", "in_progress"]), Inspection.mine_id, mine_id, scope_allowed)
    actions_overdue = _count_actions_scoped(db, "overdue", mine_id, scope_allowed)
    actions_pending = _count_actions_scoped(db, "pending", mine_id, scope_allowed)

    # ---- compliance rate over the window ----
    reading_window = [EnvironmentalReading.recorded_at >= window_start]
    if mine_id:
        reading_window.append(EnvironmentalReading.mine_id == mine_id)
    elif scope_allowed is not None:
        reading_window.append(EnvironmentalReading.mine_id.in_(scope_allowed or ["__none__"]))
    total_week = _count(db, EnvironmentalReading, *reading_window)
    violations_week = _count(
        db, EnvironmentalReading, *reading_window, EnvironmentalReading.status == "violation",
    )
    compliance_rate = round(100.0 * (total_week - violations_week) / total_week, 1) if total_week else 100.0

    # ---- distributions (scoped to the mine filter / user scope) ----
    alert_cond = [Alert.status != "resolved"]
    incident_cond = [Incident.status.in_(["open", "investigating", "action_required"])]
    event_cond = [CameraEvent.occurred_at >= window_start]
    for col, cond in ((Alert.mine_id, alert_cond), (Incident.mine_id, incident_cond), (CameraEvent.mine_id, event_cond)):
        mc = _mine_cond(col, mine_id, scope_allowed)
        if mc is not None:
            cond.append(mc)

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
    mc_rt = _mine_cond(EnvironmentalReading.mine_id, mine_id, scope_allowed)
    if mc_rt is not None:
        trend_cond.append(mc_rt)
    readings_rows = db.execute(
        select(
            func.date(EnvironmentalReading.recorded_at).label("day"),
            EnvironmentalReading.parameter,
            # PostgreSQL requires numeric for round(x, n); cast keeps SQLite
            # behaviour identical (avg rounded to 1 decimal).
            func.round(cast(func.avg(EnvironmentalReading.value), Numeric), 1).label("avg_value"),
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

    # ---- risk distribution (scoped when mine filter / user scope active) ----
    risk_rows = db.execute(select(Mine)).scalars().all()
    if mine_id:
        risk_rows = [m for m in risk_rows if m.id == mine_id]
    elif scope_allowed is not None:
        risk_set = set(scope_allowed)
        risk_rows = [m for m in risk_rows if m.id in risk_set]
    risks = [compute_all_risks_one(db, m) for m in risk_rows]
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
    mc_a = _mine_cond(Alert.mine_id, mine_id, scope_allowed)
    mc_e = _mine_cond(CameraEvent.mine_id, mine_id, scope_allowed)
    if mc_a is not None:
        recent_alert_cond.append(mc_a)
    if mc_e is not None:
        recent_event_cond.append(mc_e)
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

    recent_readings_cond = [EnvironmentalReading.recorded_at >= day_ago]
    mc_rr = _mine_cond(EnvironmentalReading.mine_id, mine_id, scope_allowed)
    if mc_rr is not None:
        recent_readings_cond.append(mc_rr)
    recent_readings_rows = db.scalars(
        select(EnvironmentalReading)
        .where(*recent_readings_cond)
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
        readings_24h=_count(db, EnvironmentalReading, *recent_readings_cond),
        camera_events_24h=(
            _count(db, CameraEvent, CameraEvent.occurred_at >= day_ago,
                   _mine_cond(CameraEvent.mine_id, mine_id, scope_allowed))
            if _mine_cond(CameraEvent.mine_id, mine_id, scope_allowed) is not None
            else _count(db, CameraEvent, CameraEvent.occurred_at >= day_ago)
        ),
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
