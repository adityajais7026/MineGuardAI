"""Cross-mine isolation acceptance tests (spec section 45).

"Demo Coal Mine A" and "Demo Coal Mine B" exist side by side with four
distinct users: a manager per mine, plus a safety and an environmental
officer permitted ONLY on mine A. For every role we verify:

  * only in-scope mines are listed
  * in-scope resources read fine
  * foreign resources (direct id, ?mine_id=, POST/PATCH body mine_id) all
    fail with 403 (or are silently excluded from filtered listings)

The backend is authoritative: no trust is placed in any client-supplied
mine_id, and admin consistently sees both mines (scope sanity).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.database import models

A_ID = "m-iso-a-0001"
B_ID = "m-iso-b-0001"

MGR_A = "u-iso-mgr-a"
MGR_B = "u-iso-mgr-b"
SAFE_A = "u-iso-safe-a"
ENV_A = "u-iso-env-a"

# (role fixture user, roles that may POST into this area)
ENV_WRITERS = {MGR_A, SAFE_A, ENV_A}
ZONE_WRITERS = {MGR_A, SAFE_A}


@pytest.fixture(scope="module")
def demo(db_session):
    """Seed the two demo mines, their users and mirrored resources."""
    now = datetime.now(timezone.utc)
    db_session.add_all([
        models.User(id=MGR_A, email="iso-mgr-a@test.ai", full_name="A Manager",
                    role="mine_manager", hashed_password="x"),
        models.User(id=MGR_B, email="iso-mgr-b@test.ai", full_name="B Manager",
                    role="mine_manager", hashed_password="x"),
        models.User(id=SAFE_A, email="iso-safe-a@test.ai", full_name="A Safety",
                    role="safety_officer", hashed_password="x",
                    permitted_mine_ids=[A_ID]),
        models.User(id=ENV_A, email="iso-env-a@test.ai", full_name="A Env",
                    role="environmental_officer", hashed_password="x",
                    permitted_mine_ids=[A_ID]),
        models.Mine(id=A_ID, name="Demo Coal Mine A", code="MINE-ISO-A",
                    mine_type="underground", status="operational",
                    location="Sector A", manager_id=MGR_A),
        models.Mine(id=B_ID, name="Demo Coal Mine B", code="MINE-ISO-B",
                    mine_type="open_cast", status="operational",
                    location="Sector B", manager_id=MGR_B),
        models.RestrictedZone(id="z-iso-a-0001", mine_id=A_ID, name="A Blast Zone", camera_id="CAM-ISO-A1"),
        models.RestrictedZone(id="z-iso-b-0001", mine_id=B_ID, name="B Blast Zone", camera_id="CAM-ISO-B1"),
        models.EnvironmentalReading(id="rd-iso-a-0001", mine_id=A_ID, parameter="pm2_5",
                                    value=30.0, unit="µg/m³", threshold=60.0,
                                    status="normal", source="simulated", recorded_at=now),
        models.EnvironmentalReading(id="rd-iso-b-0001", mine_id=B_ID, parameter="pm2_5",
                                    value=90.0, unit="µg/m³", threshold=60.0,
                                    status="violation", source="simulated", recorded_at=now),
        models.CameraEvent(id="ce-iso-a-0001", mine_id=A_ID, camera_id="CAM-ISO-A1",
                           event_type="person_without_helmet", confidence=0.9),
        models.CameraEvent(id="ce-iso-b-0001", mine_id=B_ID, camera_id="CAM-ISO-B1",
                           event_type="person_without_helmet", confidence=0.9),
        models.Alert(id="al-iso-a-0001", mine_id=A_ID, alert_type="environmental",
                     title="A alert", severity="high"),
        models.Alert(id="al-iso-b-0001", mine_id=B_ID, alert_type="environmental",
                     title="B alert", severity="high"),
        models.Incident(id="inc-iso-a-0001", mine_id=A_ID, title="A incident"),
        models.Incident(id="inc-iso-b-0001", mine_id=B_ID, title="B incident"),
        models.Inspection(id="insp-iso-a-0001", mine_id=A_ID, scheduled_at=now),
        models.Inspection(id="insp-iso-b-0001", mine_id=B_ID, scheduled_at=now),
        models.CorrectiveAction(id="ca-iso-a-0001", incident_id="inc-iso-a-0001",
                                description="Fix A thing", due_date=now + timedelta(days=7)),
        models.CorrectiveAction(id="ca-iso-b-0001", incident_id="inc-iso-b-0001",
                                description="Fix B thing", due_date=now + timedelta(days=7)),
    ])
    db_session.commit()
    return db_session


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def _as(client, as_role, user_id):
    as_role(user_id)
    return client


SCOPED_USERS = [MGR_A, SAFE_A, ENV_A]


def _foreign_read_endpoints():
    """(endpoint, fixture-id) pairs that read one resource by direct id in B."""
    return [
        ("/api/environment/{}", "rd-iso-b-0001"),
        ("/api/camera-events/{}", "ce-iso-b-0001"),
        ("/api/alerts/{}", "al-iso-b-0001"),
        ("/api/incidents/{}", "inc-iso-b-0001"),
        ("/api/inspections/{}", "insp-iso-b-0001"),
        ("/api/restricted-zones/{}", "z-iso-b-0001"),
        ("/api/corrective-actions/{}", "ca-iso-b-0001"),
    ]


# ------------------------------------------------------------------ #
# Sampling scope
# ------------------------------------------------------------------ #
@pytest.mark.parametrize("user_id", SCOPED_USERS)
def test_scope_lists_only_own_mine(client, as_role, demo, user_id):
    r = _as(client, as_role, user_id).get("/api/mines")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["items"]}
    assert A_ID in ids, "in-scope mine must be listed"
    assert B_ID not in ids, "out-of-scope mine must NOT be listed"


@pytest.mark.parametrize("user_id", SCOPED_USERS)
def test_scope_includes_assigned_mine_in_risk_list(client, as_role, demo, user_id):
    r = _as(client, as_role, user_id).get("/api/risk/mines")
    assert r.status_code == 200
    ids = {a["mine_id"] for a in r.json()}
    assert A_ID in ids
    assert B_ID not in ids


def test_admin_sees_both_demo_mines(client, demo):
    r = client.get("/api/mines")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["items"]}
    assert {A_ID, B_ID} <= ids


def test_manager_of_a_cannot_see_mine_b_row(client, as_role, demo):
    assert _as(client, as_role, MGR_A).get(f"/api/mines/{B_ID}").status_code == 403
    assert _as(client, as_role, MGR_A).get("/api/mines/MINE-ISO-B").status_code == 404


def test_in_scope_mine_reads_succeed(client, as_role, demo):
    for user_id in SCOPED_USERS:
        c = _as(client, as_role, user_id)
        assert c.get(f"/api/mines/{A_ID}").status_code == 200
        assert c.get(f"/api/mines/{A_ID}/details").status_code == 200


@pytest.mark.parametrize("user_id", SCOPED_USERS)
def test_details_endpoint_blocks_foreign_mine(client, as_role, demo, user_id):
    r = _as(client, as_role, user_id).get(f"/api/mines/{B_ID}/details")
    assert r.status_code == 403


# ------------------------------------------------------------------ #
# Direct-id reads and cross-mine ?mine_id=
# ------------------------------------------------------------------ #
@pytest.mark.parametrize("user_id", SCOPED_USERS)
def test_unfiltered_listings_contain_only_mine_a_rows(client, as_role, demo, user_id):
    """Unfiltered listings must contain A records only for scoped users."""
    checklisted = [
        ("/api/environment", "rd-iso-a-0001", "rd-iso-b-0001"),
        ("/api/camera-events", "ce-iso-a-0001", "ce-iso-b-0001"),
        ("/api/alerts", "al-iso-a-0001", "al-iso-b-0001"),
        ("/api/incidents", "inc-iso-a-0001", "inc-iso-b-0001"),
        ("/api/inspections", "insp-iso-a-0001", "insp-iso-b-0001"),
        ("/api/restricted-zones", "z-iso-a-0001", "z-iso-b-0001"),
        ("/api/corrective-actions", "ca-iso-a-0001", "ca-iso-b-0001"),
    ]
    for user_id in SCOPED_USERS:
        c = _as(client, as_role, user_id)
        for url, a_uid, b_uid in checklisted:
            items = c.get(url).json().get("items", [])
            assert isinstance(items, list)
            seen = set()
            for it in items:
                seen.add(it.get("id") or it.get("cid") or "")
            assert b_uid not in seen, f"{url} leaked a mine B row as {user_id}"
            assert a_uid in seen, f"{url} is missing its own mine A row as {user_id}"


def test_direct_foreign_resource_ids_are_forbidden(client, as_role, demo):
    for user_id in SCOPED_USERS:
        c = _as(client, as_role, user_id)
        for template, uid in _foreign_read_endpoints():
            r = c.get(template.format(uid))
            assert r.status_code == 403, f"GET {template.format(uid)} as {user_id} -> {r.status_code}"


# ------------------------------------------------------------------ #
# ?mine_id= query crossings
# ------------------------------------------------------------------ #
def test_environment_list_requires_scope_for_mine_filter(client, as_role, demo):
    for user_id in SCOPED_USERS:
        r = _as(client, as_role, user_id).get(f"/api/environment?mine_id={B_ID}")
        assert r.status_code == 403, f"env list ?mine_id=B as {user_id} -> {r.status_code}"
        r = _as(client, as_role, user_id).get(f"/api/environment?mine_id={A_ID}")
        assert r.status_code == 200
        assert {i["id"] for i in r.json()["items"]} == {"rd-iso-a-0001"}


@pytest.mark.parametrize("user_id", SCOPED_USERS)
def test_filtered_foreign_mine_listings_leak_nothing(client, as_role, demo, user_id):
    """Listings with ?mine_id=B combine the mine filter with the user's scope,
    so for an A-scoped user they may only ever return zero B rows."""
    b_remote_ids = {
        "/api/camera-events": "ce-iso-b-0001",
        "/api/alerts": "al-iso-b-0001",
        "/api/incidents": "inc-iso-b-0001",
        "/api/inspections": "insp-iso-b-0001",
        "/api/restricted-zones": "z-iso-b-0001",
    }
    c = _as(client, as_role, user_id)
    for url, remote_id in b_remote_ids.items():
        r = c.get(url, params={"mine_id": B_ID})
        assert r.status_code == 200, url
        assert remote_id not in {i.get("id", "") for i in r.json()["items"]}


@pytest.mark.parametrize("user_id", SCOPED_USERS)
def test_dashboard_summary_rejects_foreign_mine(client, as_role, demo, user_id):
    r = _as(client, as_role, user_id).get("/api/dashboard/summary", params={"mine_id": B_ID})
    assert r.status_code == 403


@pytest.mark.parametrize("user_id", SCOPED_USERS)
def test_risk_of_foreign_mine_is_forbidden(client, as_role, demo, user_id):
    assert _as(client, as_role, user_id).get(f"/api/risk/mines/{B_ID}").status_code == 403


# ------------------------------------------------------------------ #
# Snapshot resource creation with a foreign mine_id in the body
# ------------------------------------------------------------------ #
def _env_post_count(db_session, mine_id):
    from sqlalchemy import select, func
    return db_session.scalar(select(func.count()).select_from(models.EnvironmentalReading)
                             .where(models.EnvironmentalReading.mine_id == mine_id))


def test_env_reading_new_rows_never_land_in_mine_b(client, as_role, demo, db_session):
    before = _env_post_count(db_session, B_ID)
    for user_id in ENV_WRITERS:
        _as(client, as_role, user_id).post("/api/environment", json={
            "mine_id": B_ID, "parameter": "co", "value": 10.0,
            "unit": "ppm", "source": "manual",
        })
    assert _env_post_count(db_session, B_ID) == before


def test_camera_event_with_foreign_mine_id_is_forbidden(client, as_role, demo, db_session):
    r = _as(client, as_role, SAFE_A).post("/api/camera-events", json={
        "mine_id": B_ID, "camera_id": "CAM-ISO-A1",
        "event_type": "person_without_helmet", "confidence": 0.9,
        "severity": "high",
    })
    assert r.status_code == 403


def test_zone_with_foreign_mine_id_is_forbidden(client, as_role, demo, db_session):
    c = _as(client, as_role, SAFE_A)
    r = c.post("/api/restricted-zones", json={
        "mine_id": B_ID, "name": "Sneaky Zone", "camera_id": "CAM-X",
    })
    assert r.status_code == 403
    # Confirmed: the sneaky zone never landed anywhere.
    r = _as(client, as_role, MGR_A).post("/api/restricted-zones", json={
        "mine_id": B_ID, "name": "Sneaky Zone 2", "camera_id": "CAM-X2",
    })
    assert r.status_code == 403


def test_managers_cannot_patch_a_foreign_mine(client, as_role, demo):
    r = _as(client, as_role, MGR_A).patch(f"/api/mines/{B_ID}", json={"location": "hacked"})
    assert r.status_code == 403
    r = _as(client, as_role, ENV_A).patch(f"/api/mines/{B_ID}", json={"location": "hacked"})
    assert r.status_code in (403, 401)


def test_in_scope_writes_still_work(client, as_role, demo):
    """Confirmed legit A-scope write paths stay functional (isolation must not
    break the normal path)."""
    r = _as(client, as_role, SAFE_A).post("/api/camera-events", json={
        "mine_id": A_ID, "camera_id": "CAM-ISO-A1",
        "event_type": "person_without_vest", "confidence": 0.8,
    })
    assert r.status_code == 201
