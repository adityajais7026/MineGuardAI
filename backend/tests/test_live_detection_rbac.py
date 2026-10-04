"""Mine-scoped RBAC for live webcam detection (backend-enforced).

Matrix under test (STEP 6 of the live-detection fix):
    admin                 -> allowed on every mine
    mine_manager          -> allowed ONLY on mines they manage (manager_id)
    safety_officer        -> allowed ONLY on their permitted_mine_ids
    environmental_officer -> allowed ONLY on their permitted_mine_ids
    unauthenticated       -> 401

Denial tests are unconditional and deterministic: the scope check runs BEFORE
the YOLO probe, so 403/401 never depend on model availability. Allowed-path
tests assert HTTP 200 and are skipped in non-YOLO environments (same
convention as test_live_detection.py).

Also covered:
  * ordering proof: with AI_DETECTOR disabled an out-of-scope user still gets
    403 (not 503) — scoping precedes the detector probe;
  * permitted_mine_ids PATCH semantics (dedupe; explicit null = no change);
  * upload detection RBAC is UNCHANGED (environmental_officer still 403);
  * record_yolo_events routes YOLO alerts to the mine's manager.
"""
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.database import models
from app.services.camera_pipeline import record_yolo_events

MINING_IMAGE = Path(__file__).parent / "fixtures" / "mining_test.jpg"

needs_yolo_mode = pytest.mark.skipif(
    settings.AI_DETECTOR != "yolo" or not MINING_IMAGE.exists()
    or not (Path(settings.YOLO_MODEL_PATH).exists()
            or Path("../ai/yolo/models/vyra_yolov8m_ppe.pt").exists()),
    reason="requires AI_DETECTOR=yolo, model weights and the mining fixture",
)

MSG_MANAGER = "restricted to your assigned mine"
MSG_OFFICER = "restricted to the mines assigned to you"


@pytest.fixture(autouse=True)
def _reset_officer_scope(db_session):
    """Keep the shared session-scoped DB pristine: the seeded officers start
    with no permitted mines, and every test in this module must observe that
    baseline regardless of what earlier tests granted (their PATCHes commit)."""
    def _reset():
        for uid in ("u-env-0001", "u-safe-0001"):
            user = db_session.get(models.User, uid)
            if user is not None:
                user.permitted_mine_ids = []
        db_session.commit()

    _reset()
    yield
    _reset()


def _frame_payload(mine_id: str) -> dict:
    return {
        "mine_id": mine_id,
        "image_base64": base64.b64encode(MINING_IMAGE.read_bytes()).decode("ascii"),
    }


def _make_managed_mine(client: TestClient, code: str, manager_id: str | None) -> str:
    r = client.post("/api/mines", json={
        "name": f"RBAC Mine {code}", "code": code, "mine_type": "open_cast",
        "status": "operational", "location": "Test", "manager_id": manager_id,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _grant(client: TestClient, user_id: str, mine_ids: list[str]) -> None:
    r = client.patch(f"/api/users/{user_id}", json={"permitted_mine_ids": mine_ids})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ #
# 1. Authentication + the four-role matrix
# ------------------------------------------------------------------ #
def test_frame_requires_auth(anon_client):
    r = anon_client.post("/api/ai/detect/frame", json=_frame_payload("m-test-0001"))
    assert r.status_code == 401


@needs_yolo_mode
def test_admin_allowed_on_any_mine(client):
    mine = _make_managed_mine(client, "RBAC-AD1", manager_id=None)
    r = client.post("/api/ai/detect/frame", json=_frame_payload(mine))
    assert r.status_code == 200, r.text


@needs_yolo_mode
def test_environmental_officer_allowed_on_permitted_mine(client, as_role):
    mine = _make_managed_mine(client, "RBAC-EV1", manager_id=None)
    _grant(client, "u-env-0001", [mine])  # admin grants the officer this mine
    as_role("u-env-0001")                 # then the OFFICER calls the endpoint
    r = client.post("/api/ai/detect/frame", json=_frame_payload(mine))
    assert r.status_code == 200, r.text


@needs_yolo_mode
def test_safety_officer_allowed_on_permitted_mine(client, as_role):
    mine = _make_managed_mine(client, "RBAC-SO1", manager_id=None)
    _grant(client, "u-safe-0001", [mine])
    as_role("u-safe-0001")
    r = client.post("/api/ai/detect/frame", json=_frame_payload(mine))
    assert r.status_code == 200, r.text


@needs_yolo_mode
def test_mine_manager_allowed_on_managed_mine(client, as_role):
    mine = _make_managed_mine(client, "RBAC-MM1", manager_id="u-mgr-0001")
    as_role("u-mgr-0001")
    r = client.post("/api/ai/detect/frame", json=_frame_payload(mine))
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ #
# 2. Cross-mine denials (deterministic — RBAC precedes the YOLO probe)
# ------------------------------------------------------------------ #
def test_environmental_officer_rejected_without_any_permission(client, as_role):
    as_role("u-env-0001")  # seeded with permitted_mine_ids = []
    r = client.post("/api/ai/detect/frame", json=_frame_payload("m-test-0001"))
    assert r.status_code == 403
    assert MSG_OFFICER in r.json()["detail"]


def test_environmental_officer_rejected_on_unpermitted_mine(client, as_role):
    _grant(client, "u-env-0001", ["m-test-0001"])  # permitted mine A only
    as_role("u-env-0001")
    r = client.post("/api/ai/detect/frame", json=_frame_payload("m-other-0001"))
    assert r.status_code == 403
    assert MSG_OFFICER in r.json()["detail"]


def test_safety_officer_rejected_on_unpermitted_mine(client, as_role):
    _grant(client, "u-safe-0001", ["m-test-0001"])
    as_role("u-safe-0001")
    r = client.post("/api/ai/detect/frame", json=_frame_payload("m-other-0001"))
    assert r.status_code == 403
    assert MSG_OFFICER in r.json()["detail"]


def test_mine_manager_rejected_on_someone_elses_mine(client, as_role):
    # m-other-0001 has no manager; a manager who is NOT its manager is denied.
    as_role("u-mgr-0001")
    r = client.post("/api/ai/detect/frame", json=_frame_payload("m-other-0001"))
    assert r.status_code == 403
    assert MSG_MANAGER in r.json()["detail"]


def test_scoping_enforced_before_yolo_probe(client, as_role, monkeypatch):
    """With YOLO disabled an out-of-scope officer gets 403, never 503 —
    proof that authorization runs before any detector/media work."""
    monkeypatch.setattr(settings, "AI_DETECTOR", "simulated")
    as_role("u-env-0001")
    r = client.post("/api/ai/detect/frame", json=_frame_payload("m-test-0001"))
    assert r.status_code == 403
    assert MSG_OFFICER in r.json()["detail"]


# ------------------------------------------------------------------ #
# 3. permitted_mine_ids admin surface (PATCH semantics)
# ------------------------------------------------------------------ #
def test_patch_dedupes_and_returns_scope(client):
    r = client.patch("/api/users/u-safe-0001", json={
        "permitted_mine_ids": ["m-a", "m-a", "m-b", "m-a"],
    })
    assert r.status_code == 200
    assert r.json()["permitted_mine_ids"] == ["m-a", "m-b"]


def test_patch_null_leaves_scope_unchanged(client):
    r1 = client.patch("/api/users/u-safe-0001", json={"permitted_mine_ids": ["m-a"]})
    assert r1.status_code == 200
    r2 = client.patch("/api/users/u-safe-0001", json={"permitted_mine_ids": None})
    assert r2.status_code == 200
    assert r2.json()["permitted_mine_ids"] == ["m-a"]  # explicit null = no change


def test_patch_empty_list_clears_scope(client):
    r1 = client.patch("/api/users/u-safe-0001", json={"permitted_mine_ids": ["m-a"]})
    assert r1.status_code == 200
    r2 = client.patch("/api/users/u-safe-0001", json={"permitted_mine_ids": []})
    assert r2.status_code == 200
    assert r2.json()["permitted_mine_ids"] == []


def test_upload_rbac_unchanged_for_environmental_officer(client, as_role):
    """Upload detection keeps its original role map: the officer is still 403
    there (only the LIVE endpoint gained mine-scoped access)."""
    as_role("u-env-0001")
    r = client.post(
        "/api/ai/detect/image",
        params={"mine_id": "m-test-0001"},
        files={"file": ("f.jpg", MINING_IMAGE.read_bytes(), "image/jpeg")},
    )
    assert r.status_code == 403


# ------------------------------------------------------------------ #
# 4. Alert routing: YOLO alerts belong to the mine's manager
# ------------------------------------------------------------------ #
def test_yolo_alert_assigned_to_mine_manager(db_session):
    """record_yolo_events (shared by upload + live paths) stamps
    assigned_to_id with mines.manager_id for genuine alerts."""
    manager = models.User(
        id="u-mgr-rbac", email="rbac-mgr@test.ai", full_name="RBAC Manager",
        role="mine_manager", hashed_password="x",
    )
    mine = models.Mine(
        id="m-rbac-alert", name="RBAC Alert Mine", code="RBAC-AL",
        mine_type="open_cast", status="operational", location="Test",
        manager_id=manager.id,
    )
    db_session.add_all([manager, mine])
    db_session.commit()
    try:
        event, alert = record_yolo_events(
            db_session,
            mine_id=mine.id,
            camera_id="CAM-RBAC-ALERT-1",
            zone_id=None,
            zone_name=None,
            event_type="person_without_helmet",
            severity="high",
            detected_object="person#1",
            confidence=0.55,
            model_version="yolo:vyra_yolov8m_ppe.pt",
            image_ref=None,
            source_media_ref=None,
            detail="unit-test violation",
            raise_alert=True,
        )
        assert alert is not None
        assert alert.assigned_to_id == manager.id
        assert alert.source == "yolo"
        assert alert.mine_id == mine.id
        # --- cleanup (record_yolo_events commits) ---
        db_session.delete(alert)
        db_session.delete(event)
        db_session.commit()
    finally:
        db_session.delete(mine)
        db_session.delete(manager)
        db_session.commit()
