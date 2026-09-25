"""
End-to-end HTTP smoke test for the Phase 4 CRUD APIs.

Runs against a LIVE server (default http://localhost:8000) and exercises real
reads/writes on the configured database (Supabase PostgreSQL in production,
SQLite dev file locally). Verifies status codes, validation, filters,
workflow transitions and relationship handling.

Usage:
    1. start the backend:  uvicorn app.main:app --port 8000
    2. seed demo data:     python -m app.utils.seed_demo
    3. run:                python scripts/api_smoke_test.py
"""
import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
NOW = datetime.now(timezone.utc)

passed: list[str] = []
failed: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        passed.append(label)
        print(f"  PASS  {label}")
    else:
        failed.append(f"{label} {extra}")
        print(f"  FAIL  {label} {extra}")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=15)

    # ------------------------------------------------------------------ #
    print("== Health ==")
    r = client.get("/health")
    check("GET /health -> 200", r.status_code == 200, r.text)
    r = client.get("/api/health/db")
    check("GET /api/health/db -> connected", r.status_code == 200 and r.json()["connected"] is True, r.text)

    # ------------------------------------------------------------------ #
    print("== Mines ==")
    r = client.get("/api/mines")
    body = r.json()
    check("GET /api/mines lists seeded mines", r.status_code == 200 and body["total"] >= 3, r.text[:200])
    mine_id = body["items"][0]["id"]

    r = client.get(f"/api/mines/{mine_id}/details")
    check("GET /api/mines/{id}/details returns counts", r.status_code == 200 and "counts" in r.json(), r.text[:200])

    r = client.post("/api/mines", json={
        "name": "Smoke Test Mine", "code": "MINE-SMKE", "mine_type": "open_cast",
        "status": "operational", "location": "Test Location", "latitude": 10.0, "longitude": 20.0,
    })
    check("POST /api/mines -> 201", r.status_code == 201, r.text[:200])
    new_mine_id = r.json().get("id")

    r = client.post("/api/mines", json={
        "name": "Dup", "code": "MINE-SMKE", "mine_type": "open_cast",
        "status": "operational", "location": "X",
    })
    check("POST duplicate mine code -> 400", r.status_code == 400, r.text[:200])

    r = client.post("/api/mines", json={
        "name": "Bad", "code": "lower case!", "mine_type": "open_cast",
        "status": "operational", "location": "X", "latitude": 999,
    })
    check("POST invalid mine payload -> 422", r.status_code == 422, r.text[:200])

    r = client.patch(f"/api/mines/{new_mine_id}", json={"status": "maintenance"})
    check("PATCH /api/mines/{id} -> 200", r.status_code == 200 and r.json()["status"] == "maintenance", r.text[:200])

    r = client.get("/api/mines/does-not-exist")
    check("GET unknown mine -> 404", r.status_code == 404, r.text[:200])

    r = client.delete(f"/api/mines/{new_mine_id}")
    check("DELETE /api/mines/{id} -> 204", r.status_code == 204, r.text[:100])
    r = client.get(f"/api/mines/{new_mine_id}")
    check("GET deleted mine -> 404", r.status_code == 404, r.text[:100])

    # ------------------------------------------------------------------ #
    print("== Environmental readings ==")
    r = client.get("/api/environment", params={"mine_id": mine_id, "limit": 5})
    body = r.json()
    check("GET /api/environment paginates", r.status_code == 200 and len(body["items"]) <= 5 and body["total"] > 0, str(body)[:200])

    r = client.get("/api/environment", params={"status": "violation", "limit": 3})
    items = r.json()["items"]
    check("GET /api/environment?status=violation filters", r.status_code == 200 and all(i["status"] == "violation" for i in items), r.text[:200])

    r = client.get("/api/environment", params={"sort": "value", "order": "asc", "limit": 50})
    vals = [i["value"] for i in r.json()["items"]]
    check("GET /api/environment sorts by value asc", r.status_code == 200 and vals == sorted(vals), str(vals[:5]))

    # POST: value above pm2_5 threshold (60) -> violation; below -> normal
    r = client.post("/api/environment", json={
        "mine_id": mine_id, "parameter": "pm2_5", "value": 88.4, "unit": "µg/m³", "source": "simulated",
    })
    check("POST reading above threshold -> violation", r.status_code == 201 and r.json()["status"] == "violation", r.text[:200])
    check("POST reading resolves threshold from rule", r.json().get("threshold") == 60.0, r.text[:200])
    reading_id = r.json().get("id")

    r = client.post("/api/environment", json={
        "mine_id": mine_id, "parameter": "noise", "value": 70.0, "unit": "dB",
    })
    check("POST reading below threshold -> normal", r.status_code == 201 and r.json()["status"] == "normal", r.text[:200])

    r = client.post("/api/environment", json={
        "mine_id": "unknown-mine", "parameter": "pm2_5", "value": 10.0, "unit": "µg/m³",
    })
    check("POST reading with unknown mine -> 400", r.status_code == 400, r.text[:200])

    r = client.get(f"/api/environment/{reading_id}")
    check("GET /api/environment/{id} -> 200", r.status_code == 200, r.text[:200])

    # ------------------------------------------------------------------ #
    print("== Compliance rules ==")
    r = client.get("/api/compliance-rules", params={"parameter": "pm2_5"})
    check("GET /api/compliance-rules filters by parameter", r.status_code == 200 and r.json()["total"] >= 1, r.text[:200])

    r = client.post("/api/compliance-rules", json={
        "name": "Smoke rule", "parameter": "nh3", "operator": ">", "threshold": 25.0,
        "unit": "ppm", "severity": "medium",
    })
    check("POST /api/compliance-rules -> 201", r.status_code == 201, r.text[:200])
    rule_id = r.json().get("id")

    r = client.patch(f"/api/compliance-rules/{rule_id}", json={"is_active": False})
    check("PATCH rule deactivates", r.status_code == 200 and r.json()["is_active"] is False, r.text[:200])

    r = client.post("/api/compliance-rules", json={"name": "Bad", "parameter": "x", "operator": "!=", "threshold": 1, "unit": "u"})
    check("POST rule with invalid operator -> 422", r.status_code == 422, r.text[:200])

    r = client.delete(f"/api/compliance-rules/{rule_id}")
    check("DELETE rule -> 204", r.status_code == 204, r.text[:100])

    # ------------------------------------------------------------------ #
    print("== Alerts ==")
    r = client.get("/api/alerts", params={"status": "new", "limit": 5})
    check("GET /api/alerts?status=new filters", r.status_code == 200 and all(a["status"] == "new" for a in r.json()["items"]), r.text[:200])

    r = client.post("/api/alerts", json={
        "mine_id": mine_id, "alert_type": "safety", "title": "Smoke test alert",
        "severity": "high", "source": "manual",
    })
    check("POST /api/alerts -> 201", r.status_code == 201, r.text[:200])
    alert_id = r.json().get("id")

    r = client.patch(f"/api/alerts/{alert_id}", json={"status": "resolved"})
    check("PATCH resolve-from-new -> 400", r.status_code == 400, r.text[:200])

    r = client.patch(f"/api/alerts/{alert_id}", json={"status": "acknowledged"})
    check("PATCH acknowledge sets acknowledged_at", r.status_code == 200 and r.json()["acknowledged_at"] is not None, r.text[:200])

    r = client.patch(f"/api/alerts/{alert_id}", json={"status": "resolved"})
    check("PATCH resolve sets resolved_at", r.status_code == 200 and r.json()["resolved_at"] is not None, r.text[:200])

    r = client.patch(f"/api/alerts/{alert_id}", json={"status": "new"})
    check("PATCH resolved alert is final -> 400", r.status_code == 400, r.text[:200])

    r = client.post("/api/alerts", json={
        "mine_id": mine_id, "alert_type": "safety", "title": "Assigned", "assigned_to_id": "no-such-user",
    })
    check("POST alert with unknown assignee -> 400", r.status_code == 400, r.text[:200])

    # ------------------------------------------------------------------ #
    print("== Incidents ==")
    r = client.post("/api/incidents", json={
        "mine_id": mine_id, "title": "Smoke test incident", "category": "machinery",
        "severity": "medium", "reported_by_id": "u-safe-0001",
    })
    check("POST /api/incidents -> 201", r.status_code == 201, r.text[:200])
    incident_id = r.json().get("id")

    r = client.post("/api/incidents", json={"mine_id": mine_id, "title": "X", "reported_by_id": "ghost"})
    check("POST incident with unknown reporter -> 400", r.status_code == 400, r.text[:200])

    r = client.patch(f"/api/incidents/{incident_id}", json={"status": "resolved"})
    check("PATCH incident resolved sets resolved_at", r.status_code == 200 and r.json()["resolved_at"] is not None, r.text[:200])

    r = client.get("/api/incidents", params={"category": "machinery"})
    check("GET /api/incidents filters by category", r.status_code == 200 and r.json()["total"] >= 1, r.text[:200])

    # ------------------------------------------------------------------ #
    print("== Inspections ==")
    r = client.post("/api/inspections", json={
        "mine_id": mine_id, "inspector_id": "u-safe-0001", "inspection_type": "safety",
        "status": "scheduled", "scheduled_at": (NOW + timedelta(days=3)).isoformat(),
    })
    check("POST /api/inspections -> 201", r.status_code == 201, r.text[:200])
    inspection_id = r.json().get("id")

    r = client.patch(f"/api/inspections/{inspection_id}", json={"status": "completed"})
    check("PATCH complete with pending result -> 400", r.status_code == 400, r.text[:200])

    r = client.patch(f"/api/inspections/{inspection_id}", json={
        "status": "completed", "compliance_result": "partial", "findings": "Minor issues found (smoke test).",
    })
    body_json = r.json()
    check("PATCH inspection completes with completed_at", r.status_code == 200 and body_json["completed_at"] is not None, r.text[:200])

    r = client.post("/api/inspections", json={
        "mine_id": mine_id, "inspection_type": "safety", "status": "scheduled",
        "scheduled_at": "not-a-date",
    })
    check("POST inspection with bad date -> 422", r.status_code == 422, r.text[:200])

    # ------------------------------------------------------------------ #
    print("== Corrective actions ==")
    r = client.post("/api/corrective-actions", json={
        "description": "Orphan action should fail", "priority": "low",
        "due_date": (NOW + timedelta(days=1)).isoformat(),
    })
    check("POST action without source -> 400", r.status_code == 400, r.text[:200])

    r = client.post("/api/corrective-actions", json={
        "incident_id": incident_id, "description": "Smoke test action", "assigned_to_id": "u-mgr-0001",
        "priority": "high", "due_date": (NOW + timedelta(days=5)).isoformat(),
    })
    check("POST action linked to incident -> 201", r.status_code == 201, r.text[:200])
    action_id = r.json().get("id")

    r = client.patch(f"/api/corrective-actions/{action_id}", json={"status": "completed"})
    check("PATCH action completed sets completion_date", r.status_code == 200 and r.json()["completion_date"] is not None, r.text[:200])

    r = client.get("/api/corrective-actions", params={"status": "overdue"})
    check("GET /api/corrective-actions?status=overdue", r.status_code == 200 and r.json()["total"] >= 1, r.text[:200])

    # ------------------------------------------------------------------ #
    print("== Camera events & zones ==")
    zones = client.get("/api/restricted-zones", params={"mine_id": mine_id}).json()["items"]
    other_zone = client.get("/api/restricted-zones").json()["items"]
    other_zone_id = next(z["id"] for z in other_zone if z["mine_id"] != mine_id)

    r = client.post("/api/camera-events", json={
        "mine_id": mine_id, "zone_id": other_zone_id, "camera_id": "CAM-SMKE",
        "event_type": "person_without_helmet", "confidence": 0.9,
    })
    check("POST event with cross-mine zone -> 400", r.status_code == 400, r.text[:200])

    zone_id = zones[0]["id"] if zones else None
    payload = {
        "mine_id": mine_id, "camera_id": "CAM-SMKE", "event_type": "person_without_helmet",
        "confidence": 0.92, "severity": "high", "detection_source": "simulated",
    }
    if zone_id:
        payload["zone_id"] = zone_id
    r = client.post("/api/camera-events", json=payload)
    check("POST /api/camera-events -> 201 (simulated source)", r.status_code == 201 and r.json()["detection_source"] == "simulated", r.text[:200])
    event_id = r.json().get("id")

    r = client.post("/api/camera-events", json={
        "mine_id": mine_id, "camera_id": "CAM-SMKE", "event_type": "person_without_helmet", "confidence": 1.5,
    })
    check("POST event with confidence>1 -> 422", r.status_code == 422, r.text[:200])

    r = client.patch(f"/api/camera-events/{event_id}", json={"status": "investigating"})
    check("PATCH camera event status -> 200", r.status_code == 200 and r.json()["status"] == "investigating", r.text[:200])

    # ------------------------------------------------------------------ #
    print("== Users ==")
    r = client.get("/api/users", params={"role": "admin"})
    check("GET /api/users filters by role", r.status_code == 200 and r.json()["total"] >= 1, r.text[:200])

    r = client.post("/api/users", json={
        "email": "smoke-test@mineguard.ai", "full_name": "Smoke Test", "role": "safety_officer",
        "password": "S@moke1234",
    })
    check("POST /api/users -> 201 (no hash exposed)", r.status_code == 201 and "hashed_password" not in r.json(), r.text[:200])
    user_id = r.json().get("id")

    r = client.post("/api/users", json={
        "email": "smoke-test@mineguard.ai", "full_name": "Dup", "password": "S@moke1234",
    })
    check("POST duplicate email -> 400", r.status_code == 400, r.text[:200])

    r = client.patch(f"/api/users/{user_id}", json={"role": "environmental_officer", "is_active": False})
    check("PATCH user role/deactivate -> 200", r.status_code == 200 and r.json()["is_active"] is False, r.text[:200])

    r = client.post("/api/users", json={"email": "not-an-email", "full_name": "X", "password": "S@moke1234"})
    check("POST user with invalid email -> 422", r.status_code == 422, r.text[:200])

    # ------------------------------------------------------------------ #
    print()
    print(f"RESULT: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("Failures:")
        for f in failed:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
