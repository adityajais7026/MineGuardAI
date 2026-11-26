"""Phase 5 compliance engine tests (deterministic evaluation + alerting).

Ingestion is an operational write, so these tests run as the safety officer.
Mines are created directly in the database (the officer cannot use the mine
registry, which is platform administration) and granted to that officer.
"""
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def ops_client(client, as_role):
    """Operational work runs as the safety officer, who owns these work areas."""
    as_role("u-safe-0001")
    return client


def _fresh_mine(make_mine, code: str) -> str:
    """Alert dedupe is stateful (6h window), so alert-count tests need a
    fresh mine each run to stay independent of test execution order."""
    return make_mine(code, user_id="u-safe-0001", name=f"Compliance {code}")


def _ingest(ops_client, value, parameter="pm2_5", mine_id="m-test-0001"):
    return ops_client.post("/api/compliance/ingest", params={
        "mine_id": mine_id, "parameter": parameter, "value": value, "unit": "µg/m³",
    })


def test_ingest_below_threshold_compliant_no_alert(ops_client):
    r = _ingest(ops_client, 40.0)  # rule: pm2_5 > 60 -> violation
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "COMPLIANT"
    assert body["alert_generated"] is False
    assert body["rule_id"] == "r-test-0001"


def test_ingest_in_warning_band(ops_client):
    r = _ingest(ops_client, 52.0)  # >= 80% of 60 -> WARNING, no alert
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "WARNING"
    assert body["alert_generated"] is False


def test_ingest_violation_generates_alert(ops_client, make_mine):
    mine_id = _fresh_mine(make_mine, "MINE-CMP1")
    r = _ingest(ops_client, 95.0, mine_id=mine_id)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "VIOLATION"
    assert body["alert_generated"] is True
    assert body["alert_id"] is not None

    alert = ops_client.get(f"/api/alerts/{body['alert_id']}").json()
    assert alert["source"] == "compliance_engine"
    assert alert["alert_type"] == "environmental"
    assert alert["severity"] == "high"
    assert "simulated" in alert["description"].lower()
    assert alert["source_reading_id"] == body["reading_id"]


def test_duplicate_suppression_within_window(ops_client, make_mine):
    mine_id = _fresh_mine(make_mine, "MINE-CMP2")
    r1 = _ingest(ops_client, 100.0, mine_id=mine_id)
    r2 = _ingest(ops_client, 110.0, mine_id=mine_id)  # same rule within 6h window
    assert r1.json()["alert_generated"] is True
    assert r2.json()["alert_generated"] is False
    assert r2.json()["alert_id"] is None


def test_severity_comes_from_rule(ops_client, as_role, make_mine):
    # Compliance rules belong to the government officer; ingestion stays safety.
    as_role("u-env-0001")
    created = ops_client.post("/api/compliance-rules", json={
        "name": "Critical test rule", "parameter": "toxic_x", "operator": ">",
        "threshold": 10.0, "unit": "ppm", "severity": "critical",
    })
    assert created.status_code == 201, created.text
    as_role("u-safe-0001")
    mine_id = _fresh_mine(make_mine, "MINE-CMP3")
    r = _ingest(ops_client, 50.0, parameter="toxic_x", mine_id=mine_id)
    body = r.json()
    assert body["status"] == "VIOLATION" and body["alert_generated"] is True
    alert = ops_client.get(f"/api/alerts/{body['alert_id']}").json()
    assert alert["severity"] == "critical"


def test_unknown_parameter_no_rule_compliant(ops_client):
    r = _ingest(ops_client, 5.0, parameter="unobtainium")
    body = r.json()
    assert body["status"] == "COMPLIANT" and body["rule_id"] is None


def test_ingest_out_of_scope_mine_forbidden(ops_client):
    """Mine scope is checked before existence: a foreign/unknown mine is 403."""
    r = _ingest(ops_client, 5.0, mine_id="ghost-mine")
    assert r.status_code == 403


def test_evaluate_endpoint_returns_results(ops_client):
    created = ops_client.post("/api/environment", json={
        "mine_id": "m-test-0001", "parameter": "pm2_5", "value": 90.0, "unit": "µg/m³",
    })
    assert created.status_code == 201, created.text
    r = ops_client.get("/api/compliance/evaluate/m-test-0001")
    assert r.status_code == 200
    results = r.json()
    assert len(results) >= 1
    assert {res["status"] for res in results} <= {"COMPLIANT", "WARNING", "VIOLATION"}


def test_evaluate_unknown_mine_out_of_scope(ops_client):
    """Mine scope is checked before existence, so an unknown mine is a 403."""
    assert ops_client.get("/api/compliance/evaluate/ghost").status_code == 403
