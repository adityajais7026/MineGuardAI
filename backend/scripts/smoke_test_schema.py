"""
Constraint smoke test for the Phase 2 database design.

Creates the ORM tables in a scratch SQLite database, inserts seed-shaped
data (mirroring database/seed.sql), and proves that:
  * all ten tables + users accept the seeded row shapes
  * foreign keys are enforced
  * CHECK constraints reject invalid enum values
  * corrective_actions requires an incident or inspection source
  * camera_events.confidence must be within [0, 1]

Run from backend/:  python scripts/smoke_test_schema.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import models  # noqa: F401
from app.database.session import Base

DB_PATH = Path(__file__).resolve().parents[1] / "_smoke_test.db"
# Start from a clean slate (a previous failed run may leave the file behind).
DB_PATH.unlink(missing_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _enable_sqlite_fks(dbapi_conn, _record):
    # SQLite enforces FKs only when this pragma is set per connection;
    # PostgreSQL (the production target) always enforces them.
    dbapi_conn.execute("pragma foreign_keys=ON")

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

now = datetime.now(timezone.utc)
failures: list[str] = []


def expect_reject(label: str, fn) -> None:
    try:
        fn()
        db.rollback()
        failures.append(f"{label}: expected IntegrityError, got none")
    except IntegrityError:
        db.rollback()
        print(f"  rejected as expected: {label}")


try:
    # --- Seed-shaped data (same rows/shapes as database/seed.sql) ---
    users = [
        models.User(id="u-admin-0001", email="admin@mineguard.ai", full_name="Asha Verma",
                    role="admin", hashed_password="x"),
        models.User(id="u-mgr-0001", email="manager@mineguard.ai", full_name="Rohit Malhotra",
                    role="mine_manager", hashed_password="x"),
        models.User(id="u-safe-0001", email="safety@mineguard.ai", full_name="Priya Nair",
                    role="safety_officer", hashed_password="x"),
        models.User(id="u-env-0001", email="env@mineguard.ai", full_name="Karan Desai",
                    role="environmental_officer", hashed_password="x"),
    ]
    mines = [
        models.Mine(id="m-iron-0001", name="Keonjhar Iron Ore Mine", code="MINE-KIR",
                    mine_type="open_cast", status="operational", location="Keonjhar, Odisha",
                    latitude=21.6289, longitude=85.5846, manager_id="u-mgr-0001"),
        models.Mine(id="m-coal-0002", name="Talcher Coal Mine", code="MINE-TCH",
                    mine_type="underground", status="maintenance", location="Talcher, Odisha",
                    manager_id="u-mgr-0001"),
        models.Mine(id="m-baux-0003", name="Damanjodi Bauxite Mine", code="MINE-DBX",
                    mine_type="mixed", status="suspended", location="Damanjodi, Odisha",
                    manager_id="u-mgr-0001"),
    ]
    rules = [
        models.ComplianceRule(id=f"r-{i}", name=n, parameter=p, operator=">",
                              threshold=t, unit=u, severity=s, mine_id=None)
        for i, (n, p, t, u, s) in enumerate([
            ("PM2.5 limit", "pm2_5", 60.0, "µg/m³", "high"),
            ("PM10 limit", "pm10", 100.0, "µg/m³", "high"),
            ("Daytime noise limit", "noise", 85.0, "dB", "medium"),
            ("Temperature extreme", "temperature", 45.0, "°C", "medium"),
            ("CO gas limit", "co", 30.0, "ppm", "critical"),
            ("Air quality index", "aqi", 200.0, "index", "critical"),
        ], start=1)
    ]
    zones = [
        models.RestrictedZone(id="z-blast-0001", mine_id="m-iron-0001", name="Blast Zone A",
                              camera_id="CAM-KIR-01"),
        models.RestrictedZone(id="z-gas-0003", mine_id="m-coal-0002", name="Gassy Panel 3",
                              camera_id="CAM-TCH-01"),
    ]
    reading = models.EnvironmentalReading(
        id="r-iron-pm2_5-2026092504", mine_id="m-iron-0001", rule_id="r-1",
        parameter="pm2_5", value=82.4, unit="µg/m³", threshold=60.0,
        status="violation", source="simulated", recorded_at=now - timedelta(hours=2),
    )
    event = models.CameraEvent(
        id="e-z-blast-0001-restricted_zone_entry-2026092506", mine_id="m-iron-0001",
        zone_id="z-blast-0001", camera_id="CAM-KIR-01", event_type="restricted_zone_entry",
        detected_object="person", zone_label="Blast Zone A", confidence=0.87,
        severity="critical", status="new", detection_source="simulated",
        occurred_at=now - timedelta(hours=1),
    )
    alert_env = models.Alert(
        id="a-env-r-iron-pm2_5-2026092504", mine_id="m-iron-0001", alert_type="environmental",
        title="PM2.5 limit breached at Keonjhar Iron Ore Mine", severity="high",
        source="compliance_engine", status="new", source_reading_id=reading.id,
    )
    alert_safety = models.Alert(
        id="a-safety-e-z-blast", mine_id="m-iron-0001", alert_type="safety",
        title="Restricted zone entry — Blast Zone A", severity="critical",
        source="camera_pipeline", status="new", source_event_id=event.id,
    )
    incident = models.Incident(
        id="i-0002", mine_id="m-coal-0002", reported_by_id="u-safe-0001",
        title="CO spike in Gassy Panel 3", category="gas", severity="critical",
        status="action_required", occurred_at=now - timedelta(days=5),
    )
    inspection = models.Inspection(
        id="ins-0002", mine_id="m-coal-0002", inspector_id="u-safe-0001",
        inspection_type="environmental", status="completed", scheduled_at=now - timedelta(days=4),
        completed_at=now - timedelta(days=4), compliance_result="non_compliant",
        findings="Simulated finding: ventilation lag.",
    )
    actions = [
        models.CorrectiveAction(id="ca-0001", incident_id="i-0002",
                                description="Install additional CO sensors",
                                assigned_to_id="u-mgr-0001", priority="critical",
                                status="in_progress", due_date=now + timedelta(days=5)),
        models.CorrectiveAction(id="ca-0003", inspection_id="ins-0002",
                                description="Recalibrate ventilation and re-audit airflow",
                                assigned_to_id="u-env-0001", priority="high",
                                status="overdue", due_date=now - timedelta(days=2)),
    ]

    # Flush parents before alerts: Alert references readings/events by raw FK
    # (no ORM relationship), so insertion order must be explicit.
    db.add_all(users + mines + rules + zones + [reading, event])
    db.flush()
    db.add_all([alert_env, alert_safety, incident, inspection])
    db.flush()
    db.add_all(actions)
    db.commit()

    counts = {
        "users": 4, "mines": 3, "compliance_rules": 6, "restricted_zones": 2,
        "environmental_readings": 1, "camera_events": 1, "alerts": 2,
        "incidents": 1, "inspections": 1, "corrective_actions": 2,
    }
    for table, expected in counts.items():
        actual = db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        status_word = "OK" if actual == expected else "MISMATCH"
        print(f"  {table}: {actual}/{expected} {status_word}")
        if actual != expected:
            failures.append(f"{table}: expected {expected}, got {actual}")

    # --- Constraint checks ---
    expect_reject("invalid user role", lambda: (
        db.add(models.User(id="u-bad", email="bad@x.io", full_name="Bad", role="superuser",
                           hashed_password="x")), db.commit()))
    expect_reject("reading with unknown mine_id (FK)", lambda: (
        db.add(models.EnvironmentalReading(id="r-bad", mine_id="m-nope", parameter="pm2_5",
                                           value=1.0, unit="µg/m³", threshold=60.0,
                                           recorded_at=now)), db.commit()))
    expect_reject("camera event with confidence > 1", lambda: (
        db.add(models.CameraEvent(id="e-bad", mine_id="m-iron-0001", camera_id="CAM-X",
                                  event_type="other", confidence=1.5, severity="low",
                                  occurred_at=now)), db.commit()))
    expect_reject("corrective action without incident/inspection source", lambda: (
        db.add(models.CorrectiveAction(id="ca-bad", description="orphan",
                                       priority="low", status="pending",
                                       due_date=now + timedelta(days=1))), db.commit()))
    expect_reject("invalid inspection compliance_result", lambda: (
        db.add(models.Inspection(id="ins-bad", mine_id="m-iron-0001",
                                 inspection_type="safety", scheduled_at=now,
                                 compliance_result="excellent")), db.commit()))
    expect_reject("duplicate mine code", lambda: (
        db.add(models.Mine(id="m-dup", name="Dup", code="MINE-KIR",
                           mine_type="open_cast", status="operational",
                           location="X")), db.commit()))

    # --- Cascade check: deleting a mine removes its readings ---
    db.execute(text("DELETE FROM mines WHERE id='m-iron-0001'"))
    remaining = db.execute(text("SELECT count(*) FROM environmental_readings")).scalar_one()
    if remaining != 0:
        failures.append(f"cascade delete failed: {remaining} readings remain")
    else:
        print("  cascade delete mine->readings: OK")

    if failures:
        print("\nSMOKE TEST FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nSMOKE TEST PASSED: row shapes, FKs, CHECKs, uniqueness and cascades all behave.")
finally:
    db.close()
    engine.dispose()  # release the sqlite file handle before cleanup (Windows)
    DB_PATH.unlink(missing_ok=True)
