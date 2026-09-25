"""Phase 5 compliance engine tests (deterministic evaluation + alerting)."""
from datetime import datetime, timedelta, timezone


def _fresh_mine(client, code: str) -> str:
    """Alert dedupe is stateful (6h window), so alert-count tests need a
    fresh mine each run to stay independent of test execution order."""
    return client.post("/api/mines", json={
        "name": f"Compliance {code}", "code": code, "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]


def _ingest(client, value, parameter="pm2_5", mine_id="m-test-0001"):
    return client.post("/api/compliance/ingest", params={
        "mine_id": mine_id, "parameter": parameter, "value": value, "unit": "µg/m³",
    })


def test_ingest_below_threshold_compliant_no_alert(client):
    r = _ingest(client, 40.0)  # rule: pm2_5 > 60 -> violation
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "COMPLIANT"
    assert body["alert_generated"] is False
    assert body["rule_id"] == "r-test-0001"


def test_ingest_in_warning_band(client):
    r = _ingest(client, 52.0)  # >= 80% of 60 -> WARNING, no alert
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "WARNING"
    assert body["alert_generated"] is False


def test_ingest_violation_generates_alert(client):
    mine_id = _fresh_mine(client, "MINE-CMP1")
    r = _ingest(client, 95.0, mine_id=mine_id)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "VIOLATION"
    assert body["alert_generated"] is True
    assert body["alert_id"] is not None

    alert = client.get(f"/api/alerts/{body['alert_id']}").json()
    assert alert["source"] == "compliance_engine"
    assert alert["alert_type"] == "environmental"
    assert alert["severity"] == "high"
    assert "simulated" in alert["description"].lower()
    assert alert["source_reading_id"] == body["reading_id"]


def test_duplicate_suppression_within_window(client):
    mine_id = _fresh_mine(client, "MINE-CMP2")
    r1 = _ingest(client, 100.0, mine_id=mine_id)
    r2 = _ingest(client, 110.0, mine_id=mine_id)  # same rule within 6h window
    assert r1.json()["alert_generated"] is True
    assert r2.json()["alert_generated"] is False
    assert r2.json()["alert_id"] is None


def test_severity_comes_from_rule(client):
    client.post("/api/compliance-rules", json={
        "name": "Critical test rule", "parameter": "toxic_x", "operator": ">",
        "threshold": 10.0, "unit": "ppm", "severity": "critical",
    })
    mine_id = _fresh_mine(client, "MINE-CMP3")
    r = _ingest(client, 50.0, parameter="toxic_x", mine_id=mine_id)
    body = r.json()
    assert body["status"] == "VIOLATION" and body["alert_generated"] is True
    alert = client.get(f"/api/alerts/{body['alert_id']}").json()
    assert alert["severity"] == "critical"


def test_unknown_parameter_no_rule_compliant(client):
    r = _ingest(client, 5.0, parameter="unobtainium")
    body = r.json()
    assert body["status"] == "COMPLIANT" and body["rule_id"] is None


def test_ingest_unknown_mine_400(client):
    r = _ingest(client, 5.0, mine_id="ghost-mine")
    assert r.status_code == 400


def test_evaluate_endpoint_returns_results(client):
    client.post("/api/environment", json={
        "mine_id": "m-test-0001", "parameter": "pm2_5", "value": 90.0, "unit": "µg/m³",
    })
    r = client.get("/api/compliance/evaluate/m-test-0001")
    assert r.status_code == 200
    results = r.json()
    assert len(results) >= 1
    assert {res["status"] for res in results} <= {"COMPLIANT", "WARNING", "VIOLATION"}


def test_evaluate_unknown_mine_404(client):
    assert client.get("/api/compliance/evaluate/ghost").status_code == 404
