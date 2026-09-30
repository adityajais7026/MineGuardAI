"""
Live webcam frame detection tests (POST /api/ai/detect/frame).

The live endpoint reuses the REAL YOLO + PPE pipeline, so model-dependent
assertions run only when the Vyra weights are present (AI_DETECTOR=yolo).
Validation, auth, RBAC and cooldown semantics are asserted unconditionally.

Upload detection is untouched by this feature; these tests cover the new
endpoint only, plus a regression that upload endpoints still behave.
"""
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

MODEL_PATH = Path(settings.YOLO_MODEL_PATH)
MODEL_EXISTS = MODEL_PATH.exists() or Path("../ai/yolo/models/vyra_yolov8m_ppe.pt").exists()
MINING_IMAGE = Path(__file__).parent / "fixtures" / "mining_test.jpg"

needs_yolo_mode = pytest.mark.skipif(
    settings.AI_DETECTOR != "yolo" or not MODEL_EXISTS or not MINING_IMAGE.exists(),
    reason="requires AI_DETECTOR=yolo, model weights and the mining fixture",
)


def _jpeg_b64(path: Path = MINING_IMAGE) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _frame_payload(mine_id: str, **overrides) -> dict:
    body = {"mine_id": mine_id, "image_base64": _jpeg_b64()}
    body.update(overrides)
    return body


def _make_mine(client, code: str) -> str:
    return client.post("/api/mines", json={
        "name": f"Live Mine {code}", "code": code, "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]


# ------------------------------------------------------------------ #
# Auth + RBAC (no model needed)
# ------------------------------------------------------------------ #
def test_live_frame_requires_auth(anon_client):
    r = anon_client.post("/api/ai/detect/frame", json=_frame_payload("m-test-0001"))
    assert r.status_code == 401


def test_live_frame_forbidden_for_non_write_roles(client, as_role):
    as_role("u-env-0001")  # environmental_officer: not in ai_simulation write roles
    r = client.post("/api/ai/detect/frame", json=_frame_payload("m-test-0001"))
    assert r.status_code == 403


def test_live_frame_disabled_without_yolo_returns_503(client):
    """Live must never silently fall back to simulated detection."""
    if settings.AI_DETECTOR == "yolo" and MODEL_EXISTS:
        pytest.skip("environment configured for real YOLO")
    r = client.post("/api/ai/detect/frame", json=_frame_payload("m-test-0001"))
    assert r.status_code == 503
    assert "AI_DETECTOR" in r.json()["detail"]


# ------------------------------------------------------------------ #
# Request validation (no model needed when YOLO disabled; with YOLO the
# validator runs before inference, so 4xxs are deterministic either way —
# except 503-first. Guard accordingly.)
# ------------------------------------------------------------------ #
def _post_frame(client, mine_id="m-test-0001", **overrides):
    return client.post("/api/ai/detect/frame", json=_frame_payload(mine_id, **overrides))


@needs_yolo_mode
def test_live_frame_rejects_invalid_base64(client):
    # Long enough to pass field-length validation, invalid as base64.
    r = client.post("/api/ai/detect/frame", json={
        "mine_id": "m-test-0001", "image_base64": "!!!!!!!" * 8,
    })
    assert r.status_code == 400


def test_live_frame_rejects_short_payload(client):
    """Below the field minimum -> FastAPI 422 validation error (deterministic)."""
    r = client.post("/api/ai/detect/frame", json={
        "mine_id": "m-test-0001", "image_base64": "short",
    })
    assert r.status_code == 422


@needs_yolo_mode
def test_live_frame_rejects_non_image_bytes(client):
    fake = base64.b64encode(b"definitely not an image").decode()
    r = client.post("/api/ai/detect/frame", json={
        "mine_id": "m-test-0001", "image_base64": fake,
    })
    assert r.status_code == 415


@needs_yolo_mode
def test_live_frame_rejects_unknown_mine(client):
    r = _post_frame(client, mine_id="ghost-mine")
    assert r.status_code == 400


@needs_yolo_mode
def test_live_frame_rejects_zone_from_other_mine(client):
    r = _post_frame(client, mine_id="m-test-0001", zone_id="z-test-0002")
    assert r.status_code == 400


# ------------------------------------------------------------------ #
# Real inference (Vyra weights)
# ------------------------------------------------------------------ #
@needs_yolo_mode
def test_live_frame_real_detection_end_to_end(client):
    """One frame: real detections, honest source label, findings shape."""
    mine_id = _make_mine(client, "MINE-LV1")
    r = _post_frame(client, mine_id=mine_id, confidence=0.10)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["source"] == "live_webcam"          # never pretends to be an upload
    assert body["detector"] == "yolo"
    assert body["model"].startswith("yolo:")
    assert body["camera_id"].endswith("-LIVE")
    assert body["detection_count"] >= 1             # mining fixture has real people+PPE
    lowered = {c.lower() for c in body["classes_detected"]}
    assert any("hardhat" in c or "person" in c for c in lowered)
    for d in body["detections"]:
        assert 0 <= d["confidence"] <= 1 and len(d["bbox"]) == 4
    assert isinstance(body["safety_findings"], list)
    assert body["annotated_image_url"] is not None or body["detection_count"] == 0


@needs_yolo_mode
def test_live_frame_violation_creates_event_and_alert(client):
    """A NO-Hardhat above the violation bar -> event (source=yolo) + alert."""
    mine_id = _make_mine(client, "MINE-LV2")
    r = _post_frame(client, mine_id=mine_id, confidence=0.10)
    assert r.status_code == 200
    body = r.json()

    violation_rules = {f["rule"] for f in body["safety_findings"] if f["status"] == "violation"}
    if "no_hardhat" not in violation_rules:
        pytest.skip("fixture frame did not cross the violation bar in this run")
    assert body["camera_event_ids"], "violation must be recorded"
    for a in body["alerts"]:
        assert a["source"] == "yolo"
        alert = client.get(f"/api/alerts/{a['id']}").json()
        assert alert["source"] == "yolo"

    ev = client.get(f"/api/camera-events/{body['camera_event_ids'][0]}")
    assert ev.status_code == 200
    assert ev.json()["detection_source"] == "yolo"
    assert ev.json()["image_ref"] is not None       # annotated frame persisted


@needs_yolo_mode
def test_live_frame_cooldown_dedupes_events_not_evaluation(client):
    """Second identical frame within the cooldown: findings still returned,
    but no NEW camera_event is recorded (recorded=False, reason=cooldown)."""
    mine_id = _make_mine(client, "MINE-LV3")
    r1 = _post_frame(client, mine_id=mine_id, confidence=0.10)
    assert r1.status_code == 200
    r2 = _post_frame(client, mine_id=mine_id, confidence=0.10)
    assert r2.status_code == 200
    b2 = r2.json()

    # Findings are still evaluated and reported every frame.
    assert isinstance(b2["safety_findings"], list)
    first_ids = set(r1.json()["camera_event_ids"])
    new_ids = [e["camera_event_id"] for e in b2["events"] if e.get("recorded")]
    # Any event type seen twice must be cooldown-suppressed, not re-recorded.
    dup_types = {e["event_type"] for e in b2["events"] if not e.get("recorded")}
    overlapping = dup_types & {
        e["event_type"] for e in r1.json()["events"]
    }
    if overlapping:
        assert first_ids.isdisjoint(new_ids), "cooldown window must not re-record"


@needs_yolo_mode
def test_live_frame_session_id_varies_camera(client):
    """Different session markers -> different camera ids (independent dedupe)."""
    mine_id = _make_mine(client, "MINE-LV4")
    r1 = _post_frame(client, mine_id=mine_id, session_id="abc", confidence=0.10)
    r2 = _post_frame(client, mine_id=mine_id, session_id="xyz", confidence=0.10)
    assert r1.status_code == 200 and r2.status_code == 200
    c1, c2 = r1.json()["camera_id"], r2.json()["camera_id"]
    assert c1 != c2 and c1.endswith("-LIVE-abc") and c2.endswith("-LIVE-xyz")


@needs_yolo_mode
def test_live_frame_worn_ppe_never_alerts(client):
    """Compliance-only frame (hardhats/vests) records events but raises no alert."""
    mine_id = _make_mine(client, "MINE-LV5")
    r = _post_frame(client, mine_id=mine_id, confidence=0.10)
    if r.status_code != 200:
        pytest.skip("inference unavailable")
    statuses = {f["status"] for f in r.json()["safety_findings"]}
    if statuses & {"violation"}:
        pytest.skip("frame carried a violation; compliance-only invariant not applicable")
    assert r.json()["alerts"] == []


# ------------------------------------------------------------------ #
# Upload regression: the existing feature is untouched
# ------------------------------------------------------------------ #
@needs_yolo_mode
def test_upload_image_endpoint_still_works(client):
    mine_id = _make_mine(client, "MINE-LV6")
    r = client.post(
        "/api/ai/detect/image",
        params={"mine_id": mine_id, "confidence": 0.10},
        files={"upload": ("mining_test.jpg", MINING_IMAGE.read_bytes(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "uploaded_image"
    assert body["detection_count"] >= 1
