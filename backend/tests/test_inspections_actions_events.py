"""Inspection, corrective action, camera event and user API tests."""
from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------- #
# Inspections
# --------------------------------------------------------------------- #
def test_inspection_lifecycle(ops_client):
    r = ops_client.post("/api/inspections", json={
        "mine_id": "m-test-0001", "inspector_id": "u-safe-0001", "inspection_type": "safety",
        "status": "scheduled", "scheduled_at": (NOW + timedelta(days=2)).isoformat(),
    })
    assert r.status_code == 201
    inspection_id = r.json()["id"]

    # cannot complete with 'pending' result
    r = ops_client.patch(f"/api/inspections/{inspection_id}", json={"status": "completed"})
    assert r.status_code == 400

    r = ops_client.patch(f"/api/inspections/{inspection_id}", json={
        "status": "completed", "compliance_result": "non_compliant",
        "findings": "Ventilation issues.",
    })
    assert r.status_code == 200 and r.json()["completed_at"] is not None


def test_inspection_completed_at_validation(ops_client):
    r = ops_client.post("/api/inspections", json={
        "mine_id": "m-test-0001", "inspection_type": "safety", "status": "scheduled",
        "scheduled_at": (NOW + timedelta(days=1)).isoformat(),
        "completed_at": NOW.isoformat(),
    })
    assert r.status_code == 400


def test_inspection_bad_date_422(ops_client):
    r = ops_client.post("/api/inspections", json={
        "mine_id": "m-test-0001", "inspection_type": "safety", "status": "scheduled",
        "scheduled_at": "not-a-date",
    })
    assert r.status_code == 422


# --------------------------------------------------------------------- #
# Corrective actions
# --------------------------------------------------------------------- #
def test_action_requires_source(ops_client):
    r = ops_client.post("/api/corrective-actions", json={
        "description": "Orphan", "priority": "low",
        "due_date": (NOW + timedelta(days=1)).isoformat(),
    })
    assert r.status_code == 400


def test_action_lifecycle_linked_to_incident(ops_client):
    incident = ops_client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "Incident for action", "category": "machinery",
    }).json()

    r = ops_client.post("/api/corrective-actions", json={
        "incident_id": incident["id"], "description": "Fix machine guard",
        "assigned_to_id": "u-safe-0001", "priority": "high",
        "due_date": (NOW + timedelta(days=5)).isoformat(),
    })
    assert r.status_code == 201
    action_id = r.json()["id"]

    r = ops_client.patch(f"/api/corrective-actions/{action_id}", json={"status": "completed"})
    assert r.status_code == 200 and r.json()["completion_date"] is not None

    # reopening clears completion date
    r = ops_client.patch(f"/api/corrective-actions/{action_id}", json={"status": "in_progress"})
    assert r.status_code == 200 and r.json()["completion_date"] is None


def test_action_unknown_incident_400(ops_client):
    r = ops_client.post("/api/corrective-actions", json={
        "incident_id": "ghost-incident", "description": "X",
        "due_date": (NOW + timedelta(days=1)).isoformat(),
    })
    assert r.status_code == 400


def test_action_overdue_filter(ops_client):
    incident = ops_client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "Overdue incident",
    }).json()
    ops_client.post("/api/corrective-actions", json={
        "incident_id": incident["id"], "description": "Overdue action",
        "status": "overdue", "due_date": (NOW - timedelta(days=3)).isoformat(),
    })
    r = ops_client.get("/api/corrective-actions", params={"status": "overdue"})
    assert r.status_code == 200 and r.json()["total"] >= 1


# --------------------------------------------------------------------- #
# Camera events + restricted zones
# --------------------------------------------------------------------- #
def test_camera_event_zone_validation(ops_client):
    # zone from another mine is rejected
    r = ops_client.post("/api/camera-events", json={
        "mine_id": "m-test-0001", "zone_id": "z-test-0002", "camera_id": "CAM-T1",
        "event_type": "person_without_helmet", "confidence": 0.9,
    })
    assert r.status_code == 400


def test_camera_event_simulated_source(ops_client):
    r = ops_client.post("/api/camera-events", json={
        "mine_id": "m-test-0001", "zone_id": "z-test-0001", "camera_id": "CAM-T1",
        "event_type": "restricted_zone_entry", "confidence": 0.87,
        "detection_source": "simulated",
    })
    assert r.status_code == 201
    assert r.json()["detection_source"] == "simulated"  # honesty labelling
    event_id = r.json()["id"]

    r = ops_client.patch(f"/api/camera-events/{event_id}", json={"status": "investigating"})
    assert r.status_code == 200 and r.json()["status"] == "investigating"


def test_camera_event_confidence_bounds(ops_client):
    r = ops_client.post("/api/camera-events", json={
        "mine_id": "m-test-0001", "camera_id": "CAM-T1",
        "event_type": "other", "confidence": 1.5,
    })
    assert r.status_code == 422


def test_zone_crud(ops_client):
    r = ops_client.post("/api/restricted-zones", json={
        "mine_id": "m-test-0001", "name": "New Zone", "camera_id": "CAM-NZ",
    })
    assert r.status_code == 201
    zone_id = r.json()["id"]

    r = ops_client.patch(f"/api/restricted-zones/{zone_id}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    assert ops_client.delete(f"/api/restricted-zones/{zone_id}").status_code == 204


# --------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------- #
def test_user_create_hides_hash(ops_client, as_role):
    as_role("u-admin-0001")  # account management is platform administration
    r = ops_client.post("/api/users", json={
        "email": "new-user@test.ai", "full_name": "New User",
        "role": "safety_officer", "password": "Password!123",
    })
    assert r.status_code == 201
    assert "hashed_password" not in r.json()
    user_id = r.json()["id"]

    r = ops_client.patch(f"/api/users/{user_id}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"

    # duplicate email
    r = ops_client.post("/api/users", json={
        "email": "new-user@test.ai", "full_name": "Dup", "password": "Password!123",
    })
    assert r.status_code == 400


def test_user_invalid_email_422(ops_client, as_role):
    as_role("u-admin-0001")
    r = ops_client.post("/api/users", json={
        "email": "not-an-email", "full_name": "X", "password": "Password!123",
    })
    assert r.status_code == 422


def test_user_delete_soft_deactivates(ops_client, as_role):
    as_role("u-admin-0001")
    r = ops_client.post("/api/users", json={
        "email": "softdel@test.ai", "full_name": "Soft", "password": "Password!123",
    })
    user_id = r.json()["id"]
    r = ops_client.delete(f"/api/users/{user_id}")
    assert r.status_code == 204
    # still exists but deactivated (soft delete preserves audit history)
    r = ops_client.get(f"/api/users/{user_id}")
    assert r.status_code == 200 and r.json()["is_active"] is False


import pytest


@pytest.fixture()
def ops_client(client, as_role):
    """Operational work runs as the safety officer, who owns these work areas."""
    as_role("u-safe-0001")
    return client
