"""Phase 6 risk classification tests (deterministic formula + endpoints)."""
from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def test_score_bounds_and_determinism(client):
    r1 = client.get("/api/risk/mines/m-test-0001").json()
    r2 = client.get("/api/risk/mines/m-test-0001").json()
    assert 0 <= r1["score"] <= 100
    assert r1["score"] == r2["score"]  # deterministic
    assert r1["level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert "not machine learning" in r1["disclaimer"].lower()


def test_violations_increase_score(client):
    base = client.get("/api/risk/mines/m-test-0001").json()["score"]

    # several violation readings in the last 7 days -> +2 each up to 20
    for value in (95.0, 99.0):
        client.post("/api/environment", json={
            "mine_id": "m-test-0001", "parameter": "pm2_5", "value": value, "unit": "µg/m³",
        })

    after = client.get("/api/risk/mines/m-test-0001").json()["score"]
    assert after > base


def test_overdue_actions_increase_score(client):
    base = client.get("/api/risk/mines/m-test-0001").json()["score"]

    incident = client.post("/api/incidents", json={
        "mine_id": "m-test-0001", "title": "Risk test incident",
    }).json()
    client.post("/api/corrective-actions", json={
        "incident_id": incident["id"], "description": "Overdue for risk test",
        "status": "overdue", "due_date": (NOW - timedelta(days=2)).isoformat(),
    })

    after = client.get("/api/risk/mines/m-test-0001").json()
    assert after["score"] > base
    overdue_factor = next(f for f in after["factors"] if f["factor"] == "overdue_actions")
    assert overdue_factor["points"] >= 5


def test_factors_are_explainable(client):
    body = client.get("/api/risk/mines/m-test-0001").json()
    factor_names = {f["factor"] for f in body["factors"]}
    assert factor_names == {
        "environmental_violations", "active_alerts", "open_incidents",
        "inspection_results", "overdue_actions", "in_progress_actions",
    }
    for f in body["factors"]:
        assert 0 <= f["points"] <= f["max_points"]
        assert f["detail"]
    assert sum(f["max_points"] for f in body["factors"]) == 100


def test_all_mines_endpoint_sorted_desc(client):
    r = client.get("/api/risk/mines")
    assert r.status_code == 200
    scores = [m["score"] for m in r.json()]
    assert scores == sorted(scores, reverse=True)
    assert len(r.json()) >= 2


def test_unknown_mine_404(client):
    assert client.get("/api/risk/mines/ghost").status_code == 404


def test_score_to_level_bands():
    from app.services.risk import score_to_level

    assert score_to_level(0) == "LOW"
    assert score_to_level(24) == "LOW"
    assert score_to_level(25) == "MEDIUM"
    assert score_to_level(49) == "MEDIUM"
    assert score_to_level(50) == "HIGH"
    assert score_to_level(74) == "HIGH"
    assert score_to_level(75) == "CRITICAL"
    assert score_to_level(100) == "CRITICAL"
