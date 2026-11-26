"""Alert workflow + incident API tests."""
from datetime import datetime, timedelta, timezone


def test_alert_lifecycle(ops_client):
    r = ops_client.post("/api/alerts", json={
        "mine_id": "m-test-0001", "alert_type": "safety", "title": "Lifecycle alert",
        "severity": "high", "source": "manual",
    })
    assert r.status_code == 201
    alert_id = r.json()["id"]
    assert r.json()["acknowledged_at"] is None

    # resolve-from-new is blocked
    r = ops_client.patch(f"/api/alerts/{alert_id}", json={"status": "resolved"})
    assert r.status_code == 400

    r = ops_client.patch(f"/api/alerts/{alert_id}", json={"status": "acknowledged"})
    assert r.status_code == 200 and r.json()["acknowledged_at"] is not None

    r = ops_client.patch(f"/api/alerts/{alert_id}", json={"status": "resolved"})
    assert r.status_code == 200 and r.json()["resolved_at"] is not None

    # resolved is final
    assert ops_client.patch(f"/api/alerts/{alert_id}", json={"status": "new"}).status_code == 400


def test_alert_assignee_validation(ops_client):
    r = ops_client.post("/api/alerts", json={
        "mine_id": "m-test-0001", "alert_type": "safety", "title": "X",
        "assigned_to_id": "ghost-user",
    })
    assert r.status_code == 400


def test_alert_filters(ops_client):
    ops_client.post("/api/alerts", json={
        "mine_id": "m-test-0001", "alert_type": "environmental", "title": "Env alert", "severity": "low",
    })
    r = ops_client.get("/api/alerts", params={"alert_type": "environmental", "severity": "low"})
    assert r.status_code == 200
    assert all(a["alert_type"] == "environmental" and a["severity"] == "low" for a in r.json()["items"])


def test_incident_lifecycle(ops_client):
    r = ops_client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "Lifecycle incident", "category": "gas",
        "severity": "critical", "reported_by_id": "u-safe-0001",
    })
    assert r.status_code == 201
    incident_id = r.json()["id"]
    assert r.json()["resolved_at"] is None

    r = ops_client.patch(f"/api/incidents/{incident_id}", json={"status": "resolved"})
    assert r.status_code == 200 and r.json()["resolved_at"] is not None

    # reopening clears resolved_at
    r = ops_client.patch(f"/api/incidents/{incident_id}", json={"status": "investigating"})
    assert r.status_code == 200 and r.json()["resolved_at"] is None


def test_incident_unknown_reporter_400(ops_client):
    r = ops_client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "X", "reported_by_id": "ghost",
    })
    assert r.status_code == 400


import pytest


@pytest.fixture()
def ops_client(client, as_role):
    """Operational work runs as the safety officer, who owns these work areas."""
    as_role("u-safe-0001")
    return client
