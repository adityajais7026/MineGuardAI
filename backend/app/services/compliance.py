"""
Compliance engine (Phase 5).

Evaluates environmental readings against active compliance rules and
generates alerts for violations, with duplicate suppression.

Honesty notes:
- Rule thresholds are demo/simulated values seeded in Phase 2. They do NOT
  represent certified statutory limits; real regulations must be loaded via
  the compliance_rules table before any real-world use.
- `source` stays "simulated" on readings/ingest; alerts record
  source="compliance_engine" (the software that raised them) while the
  message text labels the underlying data as simulated.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import Alert, ComplianceRule, EnvironmentalReading, Mine

ComplianceStatus = Literal["COMPLIANT", "WARNING", "VIOLATION"]

# How long an open (unresolved) alert suppresses duplicates for the same
# mine+rule. Prevents alert storms from continuous monitoring.
DUPLICATE_WINDOW_HOURS = 6
# Fraction of threshold above which a value is WARNING rather than COMPLIANT
# (only when the rule explicitly supports a warning level).
WARNING_FRACTION = 0.8


class EvaluationResult(BaseModel):
    parameter: str
    value: float
    unit: str
    threshold: float | None
    operator: str | None
    rule_id: str | None
    status: ComplianceStatus
    severity: str | None
    message: str


class IngestResult(BaseModel):
    reading_id: str
    mine_id: str
    parameter: str
    value: float
    status: ComplianceStatus
    threshold: float | None
    rule_id: str | None
    alert_generated: bool
    alert_id: str | None = None
    message: str


_OPERATORS = {
    ">": lambda v, t: v > t,
    ">=": lambda v, t: v >= t,
    "<": lambda v, t: v < t,
    "<=": lambda v, t: v <= t,
}


def evaluate_value_against_rule(value: float, rule: ComplianceRule) -> tuple[ComplianceStatus, str | None]:
    """Pure, deterministic evaluation: (status, severity-if-violation)."""
    check = _OPERATORS[rule.operator]
    if check(value, rule.threshold):
        return "VIOLATION", rule.severity
    if getattr(rule, "warn_threshold", None) and not check(value, rule.warn_threshold):
        return "WARNING", None
    # General WARNING band: >= 80% of the threshold for '>' rules (documented
    # project heuristic, not a statutory definition).
    if rule.operator in {">", ">="} and value >= WARNING_FRACTION * rule.threshold:
        return "WARNING", None
    return "COMPLIANT", None


def _find_open_duplicate(db: Session, mine_id: str, rule_id: str) -> Alert | None:
    """An unresolved alert for the same mine+rule within the window blocks duplicates."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DUPLICATE_WINDOW_HOURS)
    return db.scalar(
        select(Alert).where(
            Alert.mine_id == mine_id,
            Alert.source == "compliance_engine",
            Alert.source_reading_id.isnot(None),
            Alert.status != "resolved",
            Alert.created_at >= cutoff,
            Alert.source_reading_id.in_(
                select(EnvironmentalReading.id).where(
                    EnvironmentalReading.mine_id == mine_id,
                    EnvironmentalReading.rule_id == rule_id,
                )
            ),
        )
    )


def _generate_violation_alert(
    db: Session,
    *,
    mine: Mine,
    rule: ComplianceRule,
    reading: EnvironmentalReading,
    severity: str,
) -> Alert:
    alert = Alert(
        mine_id=mine.id,
        alert_type="environmental",
        title=f"{rule.name} breached at {mine.name}",
        description=(
            f"Simulated {reading.parameter} reading {reading.value} {reading.unit} "
            f"{rule.operator} {reading.threshold} {reading.unit} "
            f"(rule '{rule.name}'). Data source: simulated sensors."
        ),
        severity=severity,
        source="compliance_engine",
        status="new",
        source_reading_id=reading.id,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def evaluate_reading(db: Session, reading: EnvironmentalReading) -> EvaluationResult:
    """Evaluate one stored reading against its rule (explicit, deterministic)."""
    rule = db.get(ComplianceRule, reading.rule_id) if reading.rule_id else None
    if rule is None:
        return EvaluationResult(
            parameter=reading.parameter, value=reading.value, unit=reading.unit,
            threshold=None, operator=None, rule_id=None, status="COMPLIANT",
            severity=None, message="No active rule covers this parameter.",
        )
    status, severity = evaluate_value_against_rule(reading.value, rule)
    if status == "VIOLATION":
        message = f"{reading.value} {reading.unit} {rule.operator} {rule.threshold} {reading.unit}"
    elif status == "WARNING":
        message = f"{reading.value} {reading.unit} is within 20% of the {rule.threshold} {reading.unit} limit"
    else:
        message = f"{reading.value} {reading.unit} within limit {rule.threshold} {reading.unit}"
    return EvaluationResult(
        parameter=reading.parameter, value=reading.value, unit=reading.unit,
        threshold=rule.threshold, operator=rule.operator, rule_id=rule.id,
        status=status, severity=severity, message=message,
    )


def ingest_reading(db: Session, mine_id: str, parameter: str, value: float, unit: str,
                   source: str = "simulated", recorded_at: datetime | None = None) -> IngestResult:
    """Full pipeline: store reading -> evaluate -> create alert (with dedupe)."""
    mine = db.get(Mine, mine_id)
    if mine is None:
        raise ValueError(f"Unknown mine '{mine_id}'")

    rule = db.scalar(
        select(ComplianceRule).where(
            ComplianceRule.parameter == parameter,
            ComplianceRule.is_active.is_(True),
            (ComplianceRule.mine_id == mine_id) | (ComplianceRule.mine_id.is_(None)),
        )
    )
    if rule is None:
        rule = db.scalar(
            select(ComplianceRule).where(
                ComplianceRule.parameter == parameter,
                ComplianceRule.is_active.is_(True),
                ComplianceRule.mine_id.is_(None),
            )
        )

    status: ComplianceStatus = "COMPLIANT"
    severity: str | None = None
    if rule is not None:
        status, severity = evaluate_value_against_rule(value, rule)

    reading = EnvironmentalReading(
        mine_id=mine_id, rule_id=rule.id if rule else None, parameter=parameter,
        value=value, unit=unit, threshold=rule.threshold if rule else value,
        status="violation" if status == "VIOLATION" else "normal",
        source=source, recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    alert_id: str | None = None
    alert_generated = False
    if status == "VIOLATION" and rule is not None:
        if _find_open_duplicate(db, mine_id, rule.id) is None:
            alert = _generate_violation_alert(db, mine=mine, rule=rule, reading=reading, severity=severity or "medium")
            alert_id, alert_generated = alert.id, True

    return IngestResult(
        reading_id=reading.id, mine_id=mine_id, parameter=parameter, value=value,
        status=status, threshold=rule.threshold if rule else None,
        rule_id=rule.id if rule else None, alert_generated=alert_generated,
        alert_id=alert_id,
        message=f"{status}" + (" — alert generated" if alert_generated else ""),
    )


def reevaluate_mine(db: Session, mine_id: str) -> list[EvaluationResult]:
    """Re-run evaluation over a mine's recent readings (display refresh; no new alerts)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    readings = db.scalars(
        select(EnvironmentalReading)
        .where(EnvironmentalReading.mine_id == mine_id, EnvironmentalReading.recorded_at >= cutoff)
        .order_by(EnvironmentalReading.recorded_at.desc())
    ).all()
    return [evaluate_reading(db, r) for r in readings]
