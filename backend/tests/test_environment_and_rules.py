"""Environmental readings + compliance rules API tests."""


def test_list_readings_filter_and_pagination(client):
    r = client.get("/api/environment", params={"mine_id": "m-test-0001", "limit": 1})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["total"] >= 1


def test_create_reading_above_threshold_is_violation(client):
    r = client.post("/api/environment", json={
        "mine_id": "m-test-0001", "parameter": "pm2_5", "value": 120.0, "unit": "µg/m³",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "violation"
    assert body["threshold"] == 60.0          # resolved from the seeded rule
    assert body["rule_id"] == "r-test-0001"   # traceability link


def test_create_reading_below_threshold_is_normal(client):
    r = client.post("/api/environment", json={
        "mine_id": "m-test-0001", "parameter": "noise", "value": 70.0, "unit": "dB",
    })
    assert r.status_code == 201
    body = r.json()
    # No noise rule seeded -> neutral threshold, status normal
    assert body["status"] == "normal"
    assert body["rule_id"] is None


def test_create_reading_unknown_mine_400(client):
    r = client.post("/api/environment", json={
        "mine_id": "ghost", "parameter": "pm2_5", "value": 1.0, "unit": "µg/m³",
    })
    assert r.status_code == 400


def test_reading_sort_by_value(client):
    r = client.get("/api/environment", params={"sort": "value", "order": "asc", "limit": 20})
    values = [item["value"] for item in r.json()["items"]]
    assert values == sorted(values)


def test_rule_crud_and_validation(client):
    r = client.post("/api/compliance-rules", json={
        "name": "NH3 limit", "parameter": "nh3", "operator": ">",
        "threshold": 25.0, "unit": "ppm", "severity": "medium",
    })
    assert r.status_code == 201
    rule_id = r.json()["id"]

    r = client.patch(f"/api/compliance-rules/{rule_id}", json={"threshold": 30.0, "is_active": False})
    assert r.status_code == 200 and r.json()["threshold"] == 30.0

    assert client.delete(f"/api/compliance-rules/{rule_id}").status_code == 204
    assert client.get(f"/api/compliance-rules/{rule_id}").status_code == 404

    # invalid operator is rejected by schema validation
    r = client.post("/api/compliance-rules", json={
        "name": "Bad", "parameter": "x", "operator": "!=", "threshold": 1, "unit": "u",
    })
    assert r.status_code == 422
