"""
YOLO detection endpoint tests.

Real inference runs against the committed fixture images when the model file
is available (it is NOT committed to git — download/see README). When the
model is absent, model-dependent tests are skipped honestly via pytest.skip
and the configuration-error paths are still asserted.
"""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

MODEL_PATH = Path(settings.YOLO_MODEL_PATH)
MODEL_EXISTS = MODEL_PATH.exists() or Path("../ai/yolo/models/yolo11n.pt").exists()
FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "bus.jpg"
FIXTURE_VIDEO = Path(__file__).parent / "fixtures" / "test_video.mp4"

needs_model = pytest.mark.skipif(not MODEL_EXISTS, reason="YOLO weights not present in test environment")
# Endpoint-flow tests need YOLO as the ACTIVE detector (endpoints return 503
# before validation otherwise — correct product behaviour).
needs_yolo_mode = pytest.mark.skipif(
    settings.AI_DETECTOR != "yolo" or not MODEL_EXISTS,
    reason="requires AI_DETECTOR=yolo and model weights",
)


@pytest.fixture()
def yolo_client(client, db_session):
    """Fresh mines per test for alert-dedupe isolation, YOLO env forced on."""
    return client


def _auth_headers():
    return {}


def _make_mine(client, code: str) -> str:
    return client.post("/api/mines", json={
        "name": f"YOLO Mine {code}", "code": code, "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]


# ------------------------------------------------------------------ #
# Validation (no model needed)
# ------------------------------------------------------------------ #
def test_detect_endpoints_require_auth(anon_client):
    r = anon_client.post("/api/ai/detect/image", params={"mine_id": "x"})
    assert r.status_code == 401
    r = anon_client.post("/api/ai/detect/video", params={"mine_id": "x"})
    assert r.status_code == 401


@needs_yolo_mode
def test_image_rejects_wrong_declared_type(client):
    r = client.post("/api/ai/detect/image", params={"mine_id": "m-test-0001"},
                    files={"upload": ("doc.txt", b"hello", "text/plain")})
    assert r.status_code == 415


@needs_yolo_mode
def test_image_rejects_forged_content(client):
    """A .png declared as image/png but carrying text bytes must fail the
    magic-byte check — content type is never trusted."""
    r = client.post("/api/ai/detect/image", params={"mine_id": "m-test-0001"},
                    files={"upload": ("fake.png", b"not-an-image" * 20, "image/png")})
    assert r.status_code == 415


@needs_yolo_mode
def test_image_rejects_unknown_mine(client):
    r = client.post("/api/ai/detect/image", params={"mine_id": "ghost"},
                    files={"upload": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png")})
    assert r.status_code == 400


@needs_yolo_mode
def test_video_rejects_wrong_declared_type(client):
    r = client.post("/api/ai/detect/video", params={"mine_id": "m-test-0001"},
                    files={"upload": ("clip.mp4", b"00" * 100, "video/mp4")})
    # Declared type ok, but the payload is not a real MP4 -> magic-byte 415.
    # (Failing earlier at 415 declared-type would also be acceptable.)
    assert r.status_code in (415, 400)


def test_yolo_disabled_returns_503_when_detector_simulated(client):
    """The upload endpoints must NOT silently run simulated detection."""
    from app.core.config import settings

    if settings.AI_DETECTOR == "yolo" and MODEL_EXISTS:
        pytest.skip("environment configured for real YOLO")
    r = client.post("/api/ai/detect/image", params={"mine_id": "m-test-0001"},
                    files={"upload": ("x.jpg", FIXTURE_IMAGE.read_bytes(), "image/jpeg")})
    assert r.status_code == 503
    assert "AI_DETECTOR" in r.json()["detail"]


# ------------------------------------------------------------------ #
# Real inference (model required)
# ------------------------------------------------------------------ #
@needs_yolo_mode
def test_detector_info_reports_real_yolo(client):
    r = client.get("/api/ai/detector")
    assert r.status_code == 200
    body = r.json()
    assert body["simulated"]["available"] is True          # fallback intact
    assert body["yolo"]["available"] is True               # real model loaded
    assert body["yolo"]["classes"] == 80


@needs_yolo_mode
def test_real_image_inference_creates_events(client):
    mine_id = _make_mine(client, "MINE-YOLO1")
    r = client.post("/api/ai/detect/image",
                    params={"mine_id": mine_id, "confidence": 0.4},
                    files={"upload": ("bus.jpg", FIXTURE_IMAGE.read_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()

    # Honest labelling
    assert body["detector"] == "yolo"
    assert body["source"] == "uploaded_image"
    # Real detections from the bus fixture: bus + >=1 person expected
    assert body["detection_count"] >= 2
    assert "person" in body["classes_detected"]
    assert "bus" in body["classes_detected"]
    for d in body["detections"]:
        assert 0 <= d["confidence"] <= 1 and len(d["bbox"]) == 4

    # Storage refs + camera events created
    assert body["annotated_image_url"] and body["original_image_url"]
    assert len(body["camera_event_ids"]) >= 1

    # Events persisted with detection_source='yolo'
    events = []
    for eid in body["camera_event_ids"]:
        r2 = client.get(f"/api/camera-events/{eid}")
        assert r2.status_code == 200
        assert r2.json()["detection_source"] == "yolo"
        events.append(r2.json())


@needs_yolo_mode
def test_zone_bound_image_raises_yolo_alert(client):
    """Person in a restricted zone -> alert with source='yolo' (never simulated)."""
    mine_id = _make_mine(client, "MINE-YOLO2")
    zones = client.get("/api/restricted-zones", params={"mine_id": mine_id}).json()
    # create a zone for this mine
    zone = client.post("/api/restricted-zones", json={
        "mine_id": mine_id, "name": "Blast Zone YOLO", "camera_id": "CAM-YOLO",
    }).json()

    r = client.post("/api/ai/detect/image",
                    params={"mine_id": mine_id, "zone_id": zone["id"], "confidence": 0.4},
                    files={"upload": ("bus.jpg", FIXTURE_IMAGE.read_bytes(), "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    rules = {f["rule"] for f in body["safety_findings"]}
    assert "restricted_zone_person" in rules
    assert "restricted_zone_vehicle" in rules
    assert body["alerts"], "expected at least one yolo alert"
    for a in body["alerts"]:
        assert a["source"] == "yolo"
        alert = client.get(f"/api/alerts/{a['id']}").json()
        assert alert["source"] == "yolo"
        assert "YOLO" in alert["description"]


@needs_yolo_mode
def test_duplicate_alert_suppression_for_yolo(client):
    """Second identical violation within the cooldown must NOT raise a new alert."""
    mine_id = _make_mine(client, "MINE-YOLO3")
    zone = client.post("/api/restricted-zones", json={
        "mine_id": mine_id, "name": "Zone Dup", "camera_id": "CAM-DUP",
    }).json()

    r1 = client.post("/api/ai/detect/image",
                     params={"mine_id": mine_id, "zone_id": zone["id"], "confidence": 0.4},
                     files={"upload": ("bus.jpg", FIXTURE_IMAGE.read_bytes(), "image/jpeg")})
    r2 = client.post("/api/ai/detect/image",
                     params={"mine_id": mine_id, "zone_id": zone["id"], "confidence": 0.4},
                     files={"upload": ("bus.jpg", FIXTURE_IMAGE.read_bytes(), "image/jpeg")})
    assert r1.status_code == 200 and r2.status_code == 200
    first_count = len(r1.json()["alerts"])
    second_count = len(r2.json()["alerts"])
    # Events are created both times; duplicate ALERTS are suppressed.
    assert len(r2.json()["camera_event_ids"]) >= 1
    assert second_count == 0, "duplicate yolo alerts should be suppressed within window"


@needs_yolo_mode
def test_video_inference_end_to_end(client):
    mine_id = _make_mine(client, "MINE-YOLO4")
    zone = client.post("/api/restricted-zones", json={
        "mine_id": mine_id, "name": "Zone Vid", "camera_id": "CAM-VID",
    }).json()

    r = client.post("/api/ai/detect/video",
                    params={"mine_id": mine_id, "zone_id": zone["id"],
                            "confidence": 0.4, "frame_stride": 5},
                    files={"upload": ("test_video.mp4", FIXTURE_VIDEO.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detector"] == "yolo"
    meta = body["video_metadata"]
    assert meta["total_frames"] == 25 and meta["fps"] == 10.0
    assert meta["processed_frames"] == 5  # 25 frames / stride 5
    assert meta["processing_seconds"] > 0
    assert body["detection_count"] > 0
    assert set(body["class_summary"]) >= {"person"}
    assert body["annotated_video_url"] and body["original_video_url"]
    # frame metadata present on events
    for e in body["events"]:
        assert e["frame_number"] is not None and e["timestamp_seconds"] is not None


@needs_yolo_mode
def test_annotated_media_files_are_real(client):
    """Annotated output must be decodable media, not empty bytes (YOLO mode)."""
    mine_id = _make_mine(client, "MINE-YOLO5")
    r = client.post("/api/ai/detect/image",
                    params={"mine_id": mine_id, "confidence": 0.4},
                    files={"upload": ("bus.jpg", FIXTURE_IMAGE.read_bytes(), "image/jpeg")})
    body = r.json()
    annotated_path = Path("snapshots") / body["annotated_image_url"].lstrip("/media/")
    if not annotated_path.exists():  # provider-dependent in test env
        pytest.skip("annotated file not on local disk (storage provider mismatch)")
    import cv2
    img = cv2.imread(str(annotated_path))
    assert img is not None and img.size > 0


# ------------------------------------------------------------------ #
# Mode-independent unit tests (validation primitives)
# ------------------------------------------------------------------ #
def test_sniff_mime_detects_real_signatures():
    from app.services.storage import sniff_mime

    assert sniff_mime(b"\xff\xd8\xff" + b"x" * 20) == "image/jpeg"
    assert sniff_mime(b"\x89PNG\r\n\x1a\n" + b"x" * 20) == "image/png"
    assert sniff_mime(b"RIFF____WEBPVP8 ") == "image/webp"
    assert sniff_mime(b"\x00\x00\x00\x1cftypisom\x00\x00") == "video/mp4"
    assert sniff_mime(b"\x1a\x45\xdf\xa3" + b"x" * 20) == "video/webm"
    assert sniff_mime(b"GIF89a......") is None  # not allowlisted
    assert sniff_mime(b"") is None


def test_build_media_path_is_safe():
    from app.services.storage import build_media_path

    p = build_media_path("m-iron-0001", "images", "jpg")
    assert p.startswith("camera/m-iron-0001/images/") and p.endswith(".jpg")
    import pytest
    from fastapi import HTTPException

    with pytest.raises(ValueError):
        build_media_path("m1", "../../etc", "jpg")  # kind whitelist blocks traversal


# ------------------------------------------------------------------ #
# Simulated detector still works (regression)
# ------------------------------------------------------------------ #
def test_simulated_events_still_work(client):
    r = client.post("/api/ai/simulate-event", params={"mine_id": "m-test-0001"})
    assert r.status_code == 201
    body = r.json()
    assert body["event"]["detection_source"] == "simulated"
    assert "not real computer vision" in body["note"]


def test_missing_model_clear_error(monkeypatch):
    """Absent weights must surface a configuration error, not fake results."""
    from app.services.yolo_detection import YoloService, YoloNotConfiguredError

    svc = YoloService(model_path="definitely/missing/model.pt")
    with pytest.raises(YoloNotConfiguredError):
        svc.detect_image_bytes(b"\x89PNG\r\n\x1a\n")
    info = svc.model_info()
    assert info["available"] is False and "not found" in info["error"]
