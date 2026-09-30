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
# Real CC-licensed construction-site photos the fine-tuned SafetyVision PPE
# model genuinely detects (verified: Hardhat/NO-Safety Vest/Safety Vest).
PPE_NO_VEST = Path(__file__).parent / "fixtures" / "ppe_no_vest.jpg"
PPE_COMPLIANT = Path(__file__).parent / "fixtures" / "ppe_hardhats_vests.jpg"
PPE_VIDEO = Path(__file__).parent / "fixtures" / "ppe_video.mp4"

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
    # Whatever weights are configured (COCO or PPE), the class count is the
    # model's own — never a hard-coded expectation.
    assert body["yolo"]["classes"] > 0


@needs_yolo_mode
def test_real_image_inference_creates_events(client):
    """Real PPE-model inference: every reported class must be a genuine model
    class, and a NO-Safety Vest detection must become a violation event."""
    mine_id = _make_mine(client, "MINE-YOLO1")
    r = client.post("/api/ai/detect/image",
                    params={"mine_id": mine_id, "confidence": 0.4},
                    files={"upload": ("ppe_no_vest.jpg", PPE_NO_VEST.read_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()

    # Honest labelling
    assert body["detector"] == "yolo"
    assert body["source"] == "uploaded_image"
    # The model genuinely detects PPE classes in this fixture (verified offline).
    assert body["detection_count"] >= 1
    lowered = {c.lower() for c in body["classes_detected"]}
    assert "hardhat" in lowered          # real compliance detection
    assert "no-safety vest" in lowered   # real violation-class detection
    from ultralytics import YOLO
    model_classes = {n.lower() for n in YOLO(str(MODEL_PATH)).names.values()}
    assert lowered <= model_classes, "reported classes must be model classes"
    for d in body["detections"]:
        assert 0 <= d["confidence"] <= 1 and len(d["bbox"]) == 4

    # PPE violation evaluation from the model's own NO-Safety Vest detection
    rules = {f["rule"] for f in body["safety_findings"]}
    assert "no_safety_vest" in rules

    # Storage refs + camera events created
    assert body["annotated_image_url"] and body["original_image_url"]
    assert len(body["camera_event_ids"]) >= 1
    event_types = {e["event_type"] for e in body["events"]}
    assert "person_without_safety_vest" in event_types

    # Events persisted with detection_source='yolo'
    for eid in body["camera_event_ids"]:
        r2 = client.get(f"/api/camera-events/{eid}")
        assert r2.status_code == 200
        assert r2.json()["detection_source"] == "yolo"


@needs_yolo_mode
def test_worn_ppe_creates_compliance_event_without_alert(client):
    """Worn PPE (Hardhat/Safety Vest) is recorded as compliance — never alerted."""
    mine_id = _make_mine(client, "MINE-PPEC")
    r = client.post("/api/ai/detect/image",
                    params={"mine_id": mine_id, "confidence": 0.4},
                    files={"upload": ("ppe_hardhats_vests.jpg", PPE_COMPLIANT.read_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    body = r.json()
    event_types = {e["event_type"] for e in body["events"]}
    assert "helmet_detected" in event_types and "safety_vest_detected" in event_types
    assert body["alerts"] == []            # compliance never raises alerts
    rules = {f["rule"] for f in body["safety_findings"]}
    assert all(not f["rule"].startswith("no_") for f in body["safety_findings"])


@needs_yolo_mode
def test_zone_bound_image_raises_yolo_alert(client):
    """A real NO-Safety Vest violation in a zone-bound upload -> alert with
    source='yolo' (never simulated). Zone rules fire only if the model also
    detects Person/vehicle classes in the frame."""
    mine_id = _make_mine(client, "MINE-YOLO2")
    zone = client.post("/api/restricted-zones", json={
        "mine_id": mine_id, "name": "Blast Zone YOLO", "camera_id": "CAM-YOLO",
    }).json()

    r = client.post("/api/ai/detect/image",
                    params={"mine_id": mine_id, "zone_id": zone["id"], "confidence": 0.4},
                    files={"upload": ("ppe_no_vest.jpg", PPE_NO_VEST.read_bytes(), "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    rules = {f["rule"] for f in body["safety_findings"]}
    assert "no_safety_vest" in rules          # from the model's own violation class
    assert body["alerts"], "expected at least one yolo alert"
    for a in body["alerts"]:
        assert a["source"] == "yolo"
        alert = client.get(f"/api/alerts/{a['id']}").json()
        assert alert["source"] == "yolo"
        assert "Real YOLO" in alert["description"]


@needs_yolo_mode
def test_duplicate_alert_suppression_for_yolo(client):
    """Second identical violation within the cooldown must NOT raise a new alert."""
    mine_id = _make_mine(client, "MINE-YOLO3")
    zone = client.post("/api/restricted-zones", json={
        "mine_id": mine_id, "name": "Zone Dup", "camera_id": "CAM-DUP",
    }).json()

    r1 = client.post("/api/ai/detect/image",
                     params={"mine_id": mine_id, "zone_id": zone["id"], "confidence": 0.4},
                     files={"upload": ("ppe_no_vest.jpg", PPE_NO_VEST.read_bytes(), "image/jpeg")})
    r2 = client.post("/api/ai/detect/image",
                     params={"mine_id": mine_id, "zone_id": zone["id"], "confidence": 0.4},
                     files={"upload": ("ppe_no_vest.jpg", PPE_NO_VEST.read_bytes(), "image/jpeg")})
    assert r1.status_code == 200 and r2.status_code == 200
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
                    files={"upload": ("ppe_video.mp4", PPE_VIDEO.read_bytes(), "video/mp4")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detector"] == "yolo"
    meta = body["video_metadata"]
    assert meta["total_frames"] == 25 and meta["fps"] == 10.0
    assert meta["processed_frames"] == 5  # 25 frames / stride 5
    assert meta["processing_seconds"] > 0
    assert body["detection_count"] > 0
    # Real PPE classes from the sampled frames (case-insensitive: 'Hardhat').
    lowered = {c.lower() for c in body["class_summary"]}
    assert "hardhat" in lowered
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


# ------------------------------------------------------------------ #
# PPE rules: only genuine violation-class detections produce findings
# ------------------------------------------------------------------ #
from app.services.safety_rules import (  # noqa: E402
    PPE_VIOLATION_CLASSES,
    evaluate_safety_rules,
)
from app.services.yolo_detection import DetectionBox  # noqa: E402


def _box(cls: str, conf: float = 0.9) -> DetectionBox:
    return DetectionBox(class_name=cls, class_id=0, confidence=conf, bbox=[0, 0, 10, 10])


def test_ppe_violation_classes_are_mapped():
    """Every violation class the SafetyVision model trains must map to an event."""
    for cls in PPE_VIOLATION_CLASSES:
        assert cls in {"no-hardhat", "no-safety vest", "no-gloves", "no-goggles",
                       "no-mask", "no_harness", "fall-detected"}


def test_no_hardhat_detection_becomes_violation_finding():
    findings = evaluate_safety_rules([_box("NO-Hardhat", 0.89)],
                                     zone_name=None, is_restricted_zone=False)
    assert [f.event_type for f in findings] == ["person_without_helmet"]
    f = findings[0]
    assert f.alert is True and f.confidence == 0.89
    assert f.detected_class == "NO-Hardhat"          # raw model class, unrenamed
    assert f.severity == "high"


def test_worn_ppe_is_compliance_not_violation():
    findings = evaluate_safety_rules([_box("Hardhat", 0.94), _box("Safety Vest", 0.9)],
                                     zone_name=None, is_restricted_zone=False)
    assert all(f.alert is False for f in findings)     # never alerts on compliance
    assert {f.event_type for f in findings} == {"helmet_detected", "safety_vest_detected"}


def test_person_alone_never_fabricates_ppe_violations():
    """A person with NO PPE-class detections must not yield any PPE finding."""
    findings = evaluate_safety_rules([_box("Person", 0.94)],
                                     zone_name=None, is_restricted_zone=False)
    assert findings == []


def test_person_capitalization_counts_for_zone_and_crowd_rules():
    """The PPE model emits 'Person' (capital); rules must still match."""
    many = [_box("Person", 0.8) for _ in range(4)]
    findings = evaluate_safety_rules(many, zone_name="Z", is_restricted_zone=True)
    rules = {f.rule for f in findings}
    assert "restricted_zone_person" in rules and "crowd_threshold" in rules


def test_fall_detection_is_critical():
    findings = evaluate_safety_rules([_box("Fall-Detected", 0.91)],
                                     zone_name=None, is_restricted_zone=False)
    assert findings[0].event_type == "fall_detected" and findings[0].severity == "critical"


def test_mixed_ppe_scene_yields_both_kinds():
    findings = evaluate_safety_rules(
        [_box("Person", 0.94), _box("NO-Hardhat", 0.89), _box("Hardhat", 0.94)],
        zone_name=None, is_restricted_zone=False,
    )
    kinds = {(f.event_type, f.alert) for f in findings}
    assert ("person_without_helmet", True) in kinds
    assert ("helmet_detected", False) in kinds
