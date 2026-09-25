"""
Development demo-data seeder.

Mirrors the clearly-labelled SIMULATED dataset from database/seed.sql so the
APIs can be exercised locally without Supabase credentials. All rows are
marked source='simulated' / detection_source='simulated' and never represent
real sensors, mines or government data.

Run from backend/:
    python -m app.utils.seed_demo            # seeds only if mines table empty
    python -m app.utils.seed_demo --force    # wipes demo rows and reseeds
"""
import sys
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import hash_password
from app.database.session import Base, SessionLocal, engine
from app.database.models import (
    Alert,
    CameraEvent,
    ComplianceRule,
    CorrectiveAction,
    EnvironmentalReading,
    Incident,
    Inspection,
    Mine,
    RestrictedZone,
    User,
)

NOW = datetime.now(timezone.utc)


def _seed(db) -> None:
    users = [
        User(id="u-admin-0001", email=settings.SEED_ADMIN_EMAIL, full_name="Asha Verma",
             role="admin", hashed_password=hash_password(settings.SEED_ADMIN_PASSWORD)),
        User(id="u-mgr-0001", email="manager@mineguard.ai", full_name="Rohit Malhotra",
             role="mine_manager", hashed_password=hash_password("Manager@123")),
        User(id="u-safe-0001", email="safety@mineguard.ai", full_name="Priya Nair",
             role="safety_officer", hashed_password=hash_password("Safety@123")),
        User(id="u-env-0001", email="env@mineguard.ai", full_name="Karan Desai",
             role="environmental_officer", hashed_password=hash_password("Env@123")),
    ]
    db.add_all(users)

    mines = [
        Mine(id="m-iron-0001", name="Keonjhar Iron Ore Mine", code="MINE-KIR", mine_type="open_cast",
             status="operational", location="Keonjhar, Odisha", latitude=21.6289, longitude=85.5846,
             manager_id="u-mgr-0001", description="Simulated open-cast iron ore operation (demo data)."),
        Mine(id="m-coal-0002", name="Talcher Coal Mine", code="MINE-TCH", mine_type="underground",
             status="maintenance", location="Talcher, Odisha", manager_id="u-mgr-0001",
             description="Simulated underground coal operation (demo data)."),
        Mine(id="m-baux-0003", name="Damanjodi Bauxite Mine", code="MINE-DBX", mine_type="mixed",
             status="suspended", location="Damanjodi, Odisha", manager_id="u-mgr-0001",
             description="Simulated mixed bauxite site (demo data)."),
    ]
    db.add_all(mines)

    rules = [
        ComplianceRule(id="r-pm25-0001", name="PM2.5 limit", parameter="pm2_5", operator=">",
                       threshold=60.0, unit="µg/m³", severity="high", mine_id=None,
                       description="Simulated threshold for demo purposes."),
        ComplianceRule(id="r-pm10-0002", name="PM10 limit", parameter="pm10", operator=">",
                       threshold=100.0, unit="µg/m³", severity="high", mine_id=None),
        ComplianceRule(id="r-noise-0003", name="Daytime noise limit", parameter="noise", operator=">",
                       threshold=85.0, unit="dB", severity="medium", mine_id=None),
        ComplianceRule(id="r-temp-0004", name="Temperature extreme", parameter="temperature", operator=">",
                       threshold=45.0, unit="°C", severity="medium", mine_id=None),
        ComplianceRule(id="r-co-0005", name="CO gas limit", parameter="co", operator=">",
                       threshold=30.0, unit="ppm", severity="critical", mine_id=None),
        ComplianceRule(id="r-aqi-0006", name="Air quality index", parameter="aqi", operator=">",
                       threshold=200.0, unit="index", severity="critical", mine_id=None),
    ]
    db.add_all(rules)

    zones = [
        RestrictedZone(id="z-blast-0001", mine_id="m-iron-0001", name="Blast Zone A",
                       camera_id="CAM-KIR-01", description="Active blasting area (demo)."),
        RestrictedZone(id="z-haul-0002", mine_id="m-iron-0001", name="Haul Road Crossing",
                       camera_id="CAM-KIR-02"),
        RestrictedZone(id="z-gas-0003", mine_id="m-coal-0002", name="Gassy Panel 3",
                       camera_id="CAM-TCH-01"),
        RestrictedZone(id="z-crush-0004", mine_id="m-baux-0003", name="Crusher Bay",
                       camera_id="CAM-DBX-01"),
    ]
    db.add_all(zones)
    db.commit()

    # --- Environmental readings: 7 days, every 4h, 3 parameters per mine ---
    params = [("pm2_5", 70.0, "µg/m³", 60.0), ("noise", 80.0, "dB", 85.0), ("co", 20.0, "ppm", 30.0)]
    rule_by_param = {r.parameter: r for r in rules}
    readings: list[EnvironmentalReading] = []
    counter = 0
    for mine in mines:
        for param, base, unit, threshold in params:
            for hours_ago in range(0, 7 * 24, 4):
                counter += 1
                # deterministic wave: some violations, mostly normal
                value = round(base + (8 if counter % 7 == 0 else -6) + (counter % 5), 1)
                rule = rule_by_param[param]
                is_violation = value > rule.threshold
                readings.append(EnvironmentalReading(
                    mine_id=mine.id, parameter=param, value=value, unit=unit,
                    threshold=rule.threshold, rule_id=rule.id,
                    status="violation" if is_violation else "normal",
                    source="simulated", recorded_at=NOW - timedelta(hours=hours_ago),
                ))
    db.add_all(readings)

    # --- Camera events (all simulated) ---
    event_specs = [
        ("restricted_zone_entry", "person", "critical", "z-blast-0001", "CAM-KIR-01"),
        ("person_without_helmet", "person", "high", "z-haul-0002", "CAM-KIR-02"),
        ("vehicle_in_restricted_area", "truck", "high", "z-gas-0003", "CAM-TCH-01"),
        ("fire_smoke", "smoke", "critical", "z-crush-0004", "CAM-DBX-01"),
    ]
    events: list[CameraEvent] = []
    for i, (etype, obj, sev, zone_id, cam) in enumerate(event_specs * 3):
        zone = next(z for z in zones if z.id == zone_id)
        events.append(CameraEvent(
            mine_id=zone.mine_id, zone_id=zone_id, camera_id=cam, event_type=etype,
            detected_object=obj, zone_label=zone.name, confidence=round(0.65 + (i % 5) * 0.06, 2),
            severity=sev, status="resolved" if i < 4 else "new",
            detection_source="simulated", occurred_at=NOW - timedelta(hours=6 * i + 2),
        ))
    db.add_all(events)
    db.commit()

    # --- Alerts: environmental (from violations) + safety (from events) ---
    alerts: list[Alert] = []
    for r in [x for x in readings if x.status == "violation"][:6]:
        alerts.append(Alert(
            mine_id=r.mine_id, alert_type="environmental",
            title=f"{r.parameter.upper()} limit breached (simulated reading)",
            description=f"Simulated {r.parameter} reading {r.value} {r.unit} exceeded {r.threshold} {r.unit}.",
            severity="high" if r.parameter != "co" else "critical",
            source="compliance_engine", status="new", source_reading_id=r.id,
            created_at=r.recorded_at,
        ))
    for e in events[:4]:
        alerts.append(Alert(
            mine_id=e.mine_id, alert_type="safety",
            title=f"{e.event_type.replace('_', ' ').title()} — {e.zone_label}",
            description=f"Simulated camera {e.camera_id} flagged {e.event_type} (confidence {e.confidence}).",
            severity=e.severity, source="camera_pipeline",
            status="acknowledged" if e.status == "resolved" else "new",
            source_event_id=e.id, acknowledged_at=NOW - timedelta(hours=1) if e.status == "resolved" else None,
            created_at=e.occurred_at,
        ))
    db.add_all(alerts)

    # --- Incidents / inspections / corrective actions ---
    incidents = [
        Incident(id="i-0001", mine_id="m-coal-0002", reported_by_id="u-safe-0001",
                 title="CO spike in Gassy Panel 3 (simulated)",
                 description="Simulated gas spike triggered evacuation drill.",
                 category="gas", severity="critical", status="action_required",
                 occurred_at=NOW - timedelta(days=3)),
        Incident(id="i-0002", mine_id="m-iron-0001", reported_by_id="u-mgr-0001",
                 title="Haul truck near-miss (simulated)",
                 category="vehicle", severity="high", status="investigating",
                 occurred_at=NOW - timedelta(days=1)),
    ]
    inspections = [
        Inspection(id="ins-0001", mine_id="m-iron-0001", inspector_id="u-safe-0001",
                   inspection_type="safety", status="completed",
                   scheduled_at=NOW - timedelta(days=5), completed_at=NOW - timedelta(days=5),
                   compliance_result="compliant", findings="Simulated findings: PPE compliance strong."),
        Inspection(id="ins-0002", mine_id="m-coal-0002", inspector_id="u-env-0001",
                   inspection_type="environmental", status="completed",
                   scheduled_at=NOW - timedelta(days=2), completed_at=NOW - timedelta(days=2),
                   compliance_result="non_compliant", findings="Simulated findings: ventilation lag."),
        Inspection(id="ins-0003", mine_id="m-baux-0003", inspector_id="u-safe-0001",
                   inspection_type="compliance", status="scheduled",
                   scheduled_at=NOW + timedelta(days=2)),
    ]
    actions = [
        CorrectiveAction(id="ca-0001", incident_id="i-0001", description="Install additional CO sensors (simulated)",
                         assigned_to_id="u-mgr-0001", priority="critical", status="in_progress",
                         due_date=NOW + timedelta(days=4)),
        CorrectiveAction(id="ca-0002", incident_id="i-0002", description="Deploy speed cameras on haul road (simulated)",
                         assigned_to_id="u-safe-0001", priority="high", status="pending",
                         due_date=NOW + timedelta(days=9)),
        CorrectiveAction(id="ca-0003", inspection_id="ins-0002", description="Recalibrate ventilation (simulated)",
                         assigned_to_id="u-env-0001", priority="high", status="overdue",
                         due_date=NOW - timedelta(days=1)),
        CorrectiveAction(id="ca-0004", inspection_id="ins-0001", description="Annual signage refresh (simulated)",
                         assigned_to_id="u-mgr-0001", priority="low", status="completed",
                         due_date=NOW - timedelta(days=10), completion_date=NOW - timedelta(days=9)),
    ]
    db.add_all(incidents + inspections + actions)
    db.commit()

    print(f"Demo data seeded: {len(users)} users, {len(mines)} mines, {len(rules)} rules, "
          f"{len(readings)} readings, {len(events)} camera events, {len(alerts)} alerts, "
          f"{len(incidents)} incidents, {len(inspections)} inspections, {len(actions)} corrective actions.")
    print("NOTE: all data is SIMULATED for development/demo purposes.")


def main() -> None:
    force = "--force" in sys.argv
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        existing = db.query(Mine).count()
        if existing and not force:
            print(f"Demo data already present ({existing} mines). Use --force to reseed.")
            return
        if force:
            # Wipe in FK-safe order (SQLite-friendly; Postgres cascades too).
            for model in [Alert, CameraEvent, EnvironmentalReading, CorrectiveAction,
                          Incident, Inspection, RestrictedZone, ComplianceRule, Mine, User]:
                db.query(model).delete()
            db.commit()
        _seed(db)


if __name__ == "__main__":
    main()
