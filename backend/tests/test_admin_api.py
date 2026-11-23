"""Platform administration API — role enforcement and honest reporting.

Verifies the redesigned administrator area is protected on the BACKEND (not just
by hiding sidebar links), that its numbers come from the database, and that
services which are not deployed report NOT CONFIGURED instead of a fake status.
"""
ADMIN = "u-admin-0001"
MANAGER = "u-mgr-0001"
SAFETY = "u-safe-0001"
ENV = "u-env-0001"

ADMIN_PATHS = ["/api/admin/overview", "/api/admin/system-health", "/api/admin/roles", "/api/admin/config"]


def test_admin_endpoints_require_authentication(anon_client):
    for path in ADMIN_PATHS:
        assert anon_client.get(path).status_code == 401, path


def test_admin_endpoints_reject_non_admin_roles(client, as_role):
    for role in (MANAGER, SAFETY, ENV):
        as_role(role)
        for path in ADMIN_PATHS:
            assert client.get(path).status_code == 403, (role, path)


def test_overview_reports_live_database_counters(client, db_session):
    """Every counter must equal the row count actually stored in the database.

    The suite shares one database, and other modules (mines, users,
    invitations, devices) legitimately add and remove rows, so the expected
    values are MEASURED here instead of hard-coded — that is what proves the
    endpoint reads the tables rather than replaying seed constants.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from app.database import models

    def count(model, *conditions):
        stmt = select(func.count()).select_from(model)
        for cond in conditions:
            stmt = stmt.where(cond)
        return int(db_session.scalar(stmt) or 0)

    db_session.expire_all()
    payload = client.get("/api/admin/overview").json()

    users_total = count(models.User)
    users_active = count(models.User, models.User.is_active.is_(True))
    assert payload["users"]["total"] == users_total
    assert payload["users"]["active"] == users_active
    assert payload["users"]["inactive"] == users_total - users_active

    mines_total = count(models.Mine)
    assert payload["mines"]["total"] == mines_total
    assert payload["mines"]["active"] == count(models.Mine, models.Mine.status == "operational")
    assert payload["mines"]["active"] + payload["mines"]["inactive"] == payload["mines"]["total"]

    assert payload["devices"]["total"] == count(models.SensorDevice)
    assert payload["invitations"]["pending"] == count(
        models.RoleInvitation,
        models.RoleInvitation.is_used.is_(False),
        models.RoleInvitation.deleted_at.is_(None),
        models.RoleInvitation.expires_at > datetime.now(timezone.utc),
    )
    assert isinstance(payload["recent_activity"], list)


def test_system_health_reports_unconfigured_services_honestly(client):
    payload = client.get("/api/admin/system-health").json()
    assert payload["api"]["status"] == "OPERATIONAL"
    assert payload["database"]["status"] == "CONNECTED"
    # The test environment configures no AI worker and no error-log store.
    assert payload["ai_worker"]["status"] == "NOT CONFIGURED"
    assert payload["error_log"]["status"] == "NOT CONFIGURED"
    assert payload["integrations"]["ocr"]["status"] == "NOT CONFIGURED"


def test_config_never_exposes_secrets(client):
    payload = client.get("/api/admin/config").json()
    assert payload["editable"] is False
    body = str(payload).lower()
    for forbidden in ("database_url", "jwt_secret", "password", "postgres://", "postgresql://"):
        assert forbidden not in body


def test_roles_endpoint_reflects_backend_permission_map(client):
    payload = client.get("/api/admin/roles").json()
    by_role = {entry["role"]: entry for entry in payload["roles"]}
    assert by_role["admin"]["users"] == 1
    assert "mine_manager" in by_role
    # Mines write access is granted to mine managers, not to safety officers.
    assert "mine_manager" in payload["write_matrix"]["mines"]
    assert "safety_officer" not in payload["write_matrix"]["mines"]


# --------------------------------------------------------------------------- #
# Sensor device administration (new PATCH endpoint)
# --------------------------------------------------------------------------- #
def _create_device(client, code: str) -> str:
    response = client.post("/api/governance/telemetry/devices", json={
        "mine_id": "m-test-0001",
        "device_code": code,
        "parameter": "pm2_5",
        "unit": "µg/m³",
        "source": "real",
        "warning_threshold": 50,
        "critical_threshold": 80,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_device_can_be_edited_and_deactivated(client):
    before = client.get("/api/admin/overview").json()["devices"]
    device_id = _create_device(client, "SEN-ADMIN-EDIT")
    response = client.patch(f"/api/governance/telemetry/devices/{device_id}",
                            json={"is_active": False, "location_text": "Pit 2"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_active"] is False
    assert body["location_text"] == "Pit 2"
    # The device is now counted as inactive by the platform overview.
    after = client.get("/api/admin/overview").json()["devices"]
    assert after["total"] == before["total"] + 1
    # The device was inserted active and then deactivated, so the active count is unchanged.
    assert after["active"] == before["active"]


def test_device_update_rejects_roles_without_telemetry_write(client, as_role):
    device_id = _create_device(client, "SEN-ADMIN-RBAC")
    as_role(MANAGER)
    assert client.patch(f"/api/governance/telemetry/devices/{device_id}",
                        json={"is_active": False}).status_code == 403


# --------------------------------------------------------------------------- #
# Administrator scope: platform management, never mine operations
# --------------------------------------------------------------------------- #
def _operational_write_attempts(due: str) -> list[tuple[str, str, dict]]:
    return [
        ("post", "/api/inspections", {"mine_id": "m-test-0001", "scheduled_at": due}),
        ("post", "/api/alerts", {"mine_id": "m-test-0001", "alert_type": "safety", "title": "Admin alert"}),
        ("post", "/api/corrective-actions", {"description": "Admin action", "due_date": due}),
        ("post", "/api/governance/emergencies",
         {"mine_id": "m-test-0001", "emergency_type": "fire", "title": "Admin emergency"}),
        # PPE violation events (camera pipeline) are safety-officer work.
        ("post", "/api/camera-events",
         {"mine_id": "m-test-0001", "camera_id": "CAM-X", "event_type": "other", "confidence": 0.9}),
    ]


def test_admin_cannot_record_telemetry_readings(client, db_session):
    """The device registry is admin-owned; the readings themselves are not."""
    from app.database.models import SensorDevice, TelemetryReading

    device_id = _create_device(client, "SEN-ADMIN-READ")
    before = db_session.query(TelemetryReading).count()
    response = client.post("/api/governance/telemetry/readings",
                           json={"device_id": device_id, "value": 0.4})
    assert response.status_code == 403, response.text
    db_session.expire_all()
    assert db_session.query(TelemetryReading).count() == before
    assert db_session.get(SensorDevice, device_id) is not None


def test_admin_cannot_perform_mine_operational_writes(client, db_session):
    """No implicit superuser: operational writes return 403 AND change nothing."""
    from datetime import datetime, timedelta, timezone

    from app.database.models import Alert, CameraEvent, CorrectiveAction, EmergencyEvent, Inspection

    def counts() -> tuple[int, int, int, int, int]:
        return (
            db_session.query(Inspection).count(),
            db_session.query(Alert).count(),
            db_session.query(CorrectiveAction).count(),
            db_session.query(EmergencyEvent).count(),
            db_session.query(CameraEvent).count(),
        )

    before = counts()
    due = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    for method, path, body in _operational_write_attempts(due):
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 403, (path, response.status_code, response.text)

    db_session.expire_all()
    assert counts() == before, "A denied administrator request modified database rows"


def test_admin_cannot_resolve_alerts_or_close_corrective_actions(client, as_role, db_session):
    """Workflow writes by an administrator are rejected and leave rows untouched."""
    from datetime import datetime, timedelta, timezone

    from app.database.models import Alert, CorrectiveAction

    due = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    as_role(SAFETY)
    alert_id = client.post("/api/alerts", json={
        "mine_id": "m-test-0001", "alert_type": "safety", "title": "PPE violation"
    }).json()["id"]
    incident_id = client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "Guard missing",
    }).json()["id"]
    action_id = client.post("/api/corrective-actions", json={
        "incident_id": incident_id, "description": "Fit guard rails", "due_date": due
    }).json()["id"]

    as_role(ADMIN)
    assert client.patch(f"/api/alerts/{alert_id}", json={"status": "resolved"}).status_code == 403
    assert client.patch(f"/api/corrective-actions/{action_id}", json={"status": "completed"}).status_code == 403

    db_session.expire_all()
    assert db_session.get(Alert, alert_id).status == "new"
    assert db_session.get(CorrectiveAction, action_id).status == "pending"


def test_admin_retains_platform_management_writes(client):
    """Mine registry, user accounts and the device registry stay admin-editable."""
    response = client.post("/api/mines", json={
        "name": "Admin Platform Mine", "code": "MINE-ADMPLAT", "mine_type": "open_cast",
        "status": "operational", "location": "HQ",
    })
    assert response.status_code == 201, response.text

    response = client.patch(f"/api/users/{SAFETY}", json={"full_name": "Safety Officer"})
    assert response.status_code == 200, response.text

    response = client.post("/api/governance/telemetry/devices", json={
        "mine_id": "m-test-0001", "device_code": "SEN-ADM-PLAT", "parameter": "co",
        "unit": "ppm", "source": "real",
    })
    assert response.status_code == 201, response.text


def test_device_registry_and_overview_counts_agree(client):
    """The dashboard counter and the device page read the same database set."""
    _create_device(client, "SEN-COUNT-AGREE")
    listed = client.get("/api/governance/telemetry/devices").json()
    overview = client.get("/api/admin/overview").json()["devices"]
    assert overview["total"] == len(listed)


def test_config_reports_the_runtime_environment(client):
    """A local SQLite run must never be labelled production."""
    platform = client.get("/api/admin/config").json()["platform"]
    assert platform["database_engine"] == "sqlite"
    assert platform["environment"].startswith("development")


def test_roles_endpoint_states_admin_scope_without_a_bypass(client):
    payload = client.get("/api/admin/roles").json()
    admin = next(entry for entry in payload["roles"] if entry["role"] == "admin")
    assert "users" in admin["write_areas"] and "mines" in admin["write_areas"]
    for operational in ("inspections", "alerts", "corrective_actions", "emergencies", "incidents"):
        assert operational not in admin["write_areas"], operational
        assert "admin" not in payload["write_matrix"][operational], operational
    assert not any("always pass" in note for note in payload["notes"])
