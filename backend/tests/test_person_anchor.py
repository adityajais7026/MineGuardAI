"""
person_anchor strategy tests (opt-in live-detection architecture).

Architecture under test:
    yolo11n (COCO persons) -> ByteTrack IDs -> Vyra PPE (UNCHANGED model)
    -> existing evaluate_safety_rules + associate_with_persons
    -> per-person verdicts -> person-specific cooldown -> immediate alert,
    with annotated-evidence upload moved OFF the alert critical path.

Hard invariants asserted here:
  * default strategy responses are byte-compatible (no persons/report/timings
    keys, alerts carry no track_id) — the opt-in flag never leaks into it;
  * per-person verdicts come from the EXISTING association rule — one person's
    PPE is never attributed to another (spatial-separation probe);
  * person-specific cooldown keys on (camera, track_id, event_type) and the
    camera+event_type cooldown remains the fallback when no track ID exists;
  * record_yolo_events(dedupe_by_object=True) lets two violating persons on
    the same camera raise two alerts (the default key would swallow them);
  * annotated-evidence upload is asynchronous: events are returned with
    image_ref=None and the rows are patched after the upload completes.

The activation tests need real weights (Vyra + yolo11n) and run only when both
are present; invariants that need no model are asserted unconditionally.
"""
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.detectors.person_anchor import PersonAnchorDetector
from app.services.detectors import get_detector_by_name
from app.services.yolo_detection import DetectionBox

# Same resolution rule as production: settings.YOLO_MODEL_PATH or the known
# sibling checkout location used by the benchmark.
def _ppe_weights() -> str:
    from pathlib import Path
    p = Path(settings.YOLO_MODEL_PATH)
    if p.exists():
        return str(p)
    alt = Path("../ai/yolo/models/vyra_yolov8m_ppe.pt")
    return str(alt) if alt.exists() else str(p)


WEIGHTS = _ppe_weights()
ANCHOR_WEIGHTS = settings.PERSON_ANCHOR_MODEL_PATH
import os  # noqa: E402

WEIGHTS_PRESENT = os.path.exists(WEIGHTS)
ANCHOR_PRESENT = os.path.exists(ANCHOR_WEIGHTS)
needs_weights = pytest.mark.skipif(
    not (WEIGHTS_PRESENT and ANCHOR_PRESENT),
    reason=f"requires PPE weights ({WEIGHTS}) and anchor weights ({ANCHOR_WEIGHTS})",
)


# --------------------------------------------------------------------------- #
# 1. Detector unit level (no HTTP): tracking + association invariants
# --------------------------------------------------------------------------- #
@needs_weights
def test_anchor_detector_persons_and_ppe_are_separate():
    """The anchor supplies persons with IDs; Vyra supplies PPE; never mixed."""
    import numpy as np
    import cv2

    det = get_detector_by_name("person_anchor")
    assert isinstance(det, PersonAnchorDetector)
    img = cv2.imread("tests/fixtures/mining_test.jpg")
    assert img is not None
    res = det.detect(img, confidence=0.10, session_key="t-unit-1")
    assert res.persons, "mining fixture must yield persons from the anchor"
    for p in res.persons:
        assert p.class_name == "person" and p.class_id == 0
        assert p.track_id is not None and p.track_id >= 1
        assert len(p.bbox) == 4 and p.bbox[0] < p.bbox[2] and p.bbox[1] < p.bbox[3]
    # PPE detections must never be labeled 'person' (that class belongs to the anchor)
    for d in res.detections:
        assert d.class_name.lower() != "person"
    assert res.ppe_ms > 0 and res.anchor_ms > 0


@needs_weights
def test_anchor_tracker_ids_persist_same_session_and_reset_per_session():
    """Same session key -> same IDs across calls; new key -> fresh numbering."""
    import numpy as np
    import cv2

    det = get_detector_by_name("person_anchor")
    img = cv2.imread("tests/fixtures/mining_test.jpg")
    r1 = det.detect(img, confidence=0.10, session_key="t-track-a")
    r2 = det.detect(img, confidence=0.10, session_key="t-track-a")  # identical frame
    ids1 = [p.track_id for p in r1.persons]
    ids2 = [p.track_id for p in r2.persons]
    assert ids1 == ids2, f"static scene must keep IDs stable: {ids1} vs {ids2}"

    r3 = det.detect(img, confidence=0.10, session_key="t-track-b")
    ids3 = [p.track_id for p in r3.persons]
    assert ids3 and max(ids3) <= len(ids3), "new session restarts numbering at 1"


# --------------------------------------------------------------------------- #
# 2. Policy mapping helpers (pure functions; no model needed)
# --------------------------------------------------------------------------- #
def _person(cx: float, cy: float, w: float, h: float):
    """Synthetic tracked person centered at (cx, cy)."""
    from app.services.detectors.person_anchor import PersonBox
    return PersonBox(class_name="person", class_id=0, confidence=0.9,
                     bbox=[cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                     track_id=7)


def _ppe(cls: str, bbox, conf=0.9):
    return DetectionBox(class_name=cls, class_id=0, confidence=conf, bbox=list(bbox))


def test_findings_person_map_attributes_by_geometry():
    """A violation box overlapping person A maps to A, never to distant B."""
    from app.api.v1.live_detect import _findings_person_map
    from app.services.safety_rules import evaluate_safety_rules

    pa = _person(200, 400, 120, 300)
    pb = _person(800, 400, 120, 300)
    pb.track_id = 8
    ppe = [_ppe("NO-Hardhat", [150, 260, 250, 340])]  # inside A's head area
    detections = ppe + [
        DetectionBox(class_name="person", class_id=0, confidence=0.9, bbox=pa.bbox),
        DetectionBox(class_name="person", class_id=0, confidence=0.9, bbox=pb.bbox),
    ]
    findings = evaluate_safety_rules(detections, zone_name=None, is_restricted_zone=False)
    pmap = _findings_person_map(findings, ppe, [pa, pb])
    # Exactly one PPE finding; it belongs to person index 0 (track 7).
    ppe_findings = [i for i, f in enumerate(findings) if f.detected_class is not None]
    assert len(ppe_findings) == 1
    assert pmap[ppe_findings[0]] == 0


def test_findings_person_map_unmatched_ppe_has_no_owner():
    """A PPE box on empty space carries no person attribution (honest None)."""
    from app.api.v1.live_detect import _findings_person_map
    from app.services.safety_rules import evaluate_safety_rules

    pa = _person(200, 400, 120, 300)
    ppe = [_ppe("NO-Hardhat", [900, 260, 1000, 340])]  # far from A
    detections = ppe + [
        DetectionBox(class_name="person", class_id=0, confidence=0.9, bbox=pa.bbox),
    ]
    findings = evaluate_safety_rules(detections, zone_name=None, is_restricted_zone=False)
    pmap = _findings_person_map(findings, ppe, [pa])
    ppe_findings = [i for i, f in enumerate(findings) if f.detected_class is not None]
    assert pmap[ppe_findings[0]] is None


def test_two_spaced_violations_map_to_their_own_persons():
    """Person A = helmet, Person B = NO-Hardhat: B's violation never hits A."""
    from app.api.v1.live_detect import _findings_person_map
    from app.services.safety_rules import evaluate_safety_rules

    pa = _person(200, 400, 120, 300); pa.track_id = 1
    pb = _person(800, 400, 120, 300); pb.track_id = 2
    ppe = [
        _ppe("Hardhat", [150, 260, 250, 340]),        # A's head
        _ppe("NO-Hardhat", [750, 260, 850, 340]),     # B's head
    ]
    detections = ppe + [
        DetectionBox(class_name="person", class_id=0, confidence=0.9, bbox=pa.bbox),
        DetectionBox(class_name="person", class_id=0, confidence=0.9, bbox=pb.bbox),
    ]
    findings = evaluate_safety_rules(detections, zone_name=None, is_restricted_zone=False)
    pmap = _findings_person_map(findings, ppe, [pa, pb])
    owners = [pmap[i] for i, f in enumerate(findings) if f.detected_class is not None]
    assert owners == [0, 1]  # helmet->A, violation->B (positional order preserved)


# --------------------------------------------------------------------------- #
# 3. Per-person alert dedupe at the pipeline level (no model needed)
# --------------------------------------------------------------------------- #
def test_record_yolo_events_dedupe_by_object_separates_persons(db_session, client):
    """Two persons, same camera+event_type, dedupe_by_object=True -> 2 alerts.

    The default key (camera+event_type) would swallow the second one.
    """
    from app.services.camera_pipeline import record_yolo_events
    from app.database.models import Alert

    def _rec(track: str):
        return record_yolo_events(
            db_session,
            mine_id="m-test-0001", camera_id="CAM-DEDUPE-T", zone_id=None, zone_name=None,
            event_type="person_without_helmet", severity="high",
            detected_object=f"person#{track}", confidence=0.8,
            model_version="anchor:test", image_ref=None, source_media_ref=None,
            detail="probe", raise_alert=True, dedupe_by_object=True,
        )

    _, alert_a = _rec(7)
    _, alert_b = _rec(8)
    _, alert_a2 = _rec(7)  # same person again -> suppressed by object key
    assert alert_a is not None and alert_b is not None
    assert alert_a2 is None
    assert alert_a.source == "yolo"

    # Default behaviour unchanged: same camera+event_type without object key
    _, d1 = record_yolo_events(
        db_session, mine_id="m-test-0001", camera_id="CAM-DEDUPE-D", zone_id=None,
        zone_name=None, event_type="person_without_helmet", severity="high",
        detected_object="NO-Hardhat", confidence=0.8, model_version="yolo:test",
        image_ref=None, source_media_ref=None, detail="probe", raise_alert=True,
    )
    _, d2 = record_yolo_events(
        db_session, mine_id="m-test-0001", camera_id="CAM-DEDUPE-D", zone_id=None,
        zone_name=None, event_type="person_without_helmet", severity="high",
        detected_object="NO-Hardhat", confidence=0.8, model_version="yolo:test",
        image_ref=None, source_media_ref=None, detail="probe 2", raise_alert=True,
    )
    assert d1 is not None and d2 is None  # camera+event_type dedupe intact


def test_person_cooldown_keys_on_track_id_and_camera():
    """(camera, track_id, event_type) is the identity; other keys unaffected."""
    import app.api.v1.live_detect as ld

    ld._person_dedupe.clear()
    assert not ld._person_in_cooldown("CAM-X", 7, "person_without_helmet")
    assert ld._person_in_cooldown("CAM-X", 7, "person_without_helmet")
    # different person / different camera / different event type -> fresh
    assert not ld._person_in_cooldown("CAM-X", 8, "person_without_helmet")
    assert not ld._person_in_cooldown("CAM-Y", 7, "person_without_helmet")
    assert not ld._person_in_cooldown("CAM-X", 7, "person_without_safety_vest")
    ld._person_dedupe.clear()


# --------------------------------------------------------------------------- #
# 4. Endpoint level, strategy activated (needs weights)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def anchor_client(client, monkeypatch):
    """TestClient with AI_DETECTOR_STRATEGY forced to person_anchor."""
    monkeypatch.setattr(settings, "AI_DETECTOR_STRATEGY", "person_anchor")
    import app.api.v1.live_detect as ld
    ld._person_dedupe.clear()
    yield client
    monkeypatch.setattr(settings, "AI_DETECTOR_STRATEGY", "default")
    ld._person_dedupe.clear()


def _frame_payload(mine_id: str, **overrides):
    import base64
    from pathlib import Path
    jpg = Path(__file__).parent / "fixtures" / "mining_test.jpg"
    body = {"mine_id": mine_id, "image_base64": base64.b64encode(jpg.read_bytes()).decode()}
    body.update(overrides)
    return body


@needs_weights
def test_anchor_response_shape_and_person_report(anchor_client):
    """Activated strategy returns persons + per-person report + timings."""
    mine = anchor_client.post("/api/mines", json={
        "name": "Anchor Mine A", "code": "ANCH-A1", "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]
    r = anchor_client.post("/api/ai/detect/frame", json=_frame_payload(mine, confidence=0.10))
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["strategy"] == "person_anchor"
    assert body["model"].startswith("anchor:vyra")
    assert body["annotated_image_url"] is None          # upload moved async
    assert body["evidence_upload"] == "async"
    assert body["timings"]["strategy"] == "person_anchor"
    for key in ("ppe_ms", "anchor_ms", "policy_ms", "total_response_ms"):
        assert key in body["timings"]
    assert body["persons"], "fixture frame must contain tracked persons"
    for p in body["persons"]:
        assert p["class"] == "person" and p["track_id"] is not None
    # Per-person verdicts: one row per tracked person, never cross-attributed
    report = body["person_ppe_report"]
    assert report is not None and len(report) == len(body["persons"])
    for row in report:
        assert row["track_id"] is not None
        for e in row["ppe"]:
            assert 0.0 <= e["confidence"] <= 1.0
    # findings carry their owning track id
    for f in body["safety_findings"]:
        assert "track_id" in f


@needs_weights
def test_anchor_person_cooldown_and_stable_ids_second_frame(anchor_client):
    """Second identical frame: same IDs, everything person-keyed is cooled down."""
    mine = anchor_client.post("/api/mines", json={
        "name": "Anchor Mine B", "code": "ANCH-B1", "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]
    r1 = anchor_client.post("/api/ai/detect/frame", json=_frame_payload(mine, confidence=0.10))
    assert r1.status_code == 200
    r2 = anchor_client.post("/api/ai/detect/frame", json=_frame_payload(mine, confidence=0.10))
    assert r2.status_code == 200
    b2 = r2.json()
    ids1 = sorted(p["track_id"] for p in r1.json()["persons"])
    ids2 = sorted(p["track_id"] for p in b2["persons"])
    assert ids1 == ids2
    # static frame: every person-keyed finding must be cooldown-suppressed
    person_keyed = [e for e in b2["events"] if e.get("track_id") is not None]
    if person_keyed:
        assert all(not e["recorded"] and e["reason"] == "cooldown" for e in person_keyed)


@needs_weights
def test_anchor_events_are_returned_without_blocking_on_evidence(anchor_client, db_session, monkeypatch):
    """Events persist with image_ref=None; the async upload patches them later."""
    import app.database.session as dbsess

    # Point SessionLocal at the TEST engine so the daemon thread patches THIS db.
    monkeypatch.setattr(dbsess, "SessionLocal", dbsess.sessionmaker(
        bind=db_session.get_bind(), autoflush=False, expire_on_commit=False))

    mine = anchor_client.post("/api/mines", json={
        "name": "Anchor Mine C", "code": "ANCH-C1", "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]
    r = anchor_client.post("/api/ai/detect/frame", json=_frame_payload(mine, confidence=0.10))
    assert r.status_code == 200
    body = r.json()
    assert body["camera_event_ids"], "fixture must record events"

    # Immediately: rows exist with no image yet (upload off the critical path).
    for eid in body["camera_event_ids"]:
        ev = anchor_client.get(f"/api/camera-events/{eid}").json()
        assert ev["image_ref"] is None

    # Let the daemon finish, then the rows must be patched with real evidence.
    deadline = time.time() + 15
    patched = 0
    while time.time() < deadline and patched < len(body["camera_event_ids"]):
        time.sleep(1.0)
        patched = sum(
            1 for eid in body["camera_event_ids"]
            if anchor_client.get(f"/api/camera-events/{eid}").json()["image_ref"]
        )
    assert patched == len(body["camera_event_ids"]), (
        "async evidence upload must patch every recorded event"
    )


@needs_weights
def test_anchor_violation_alerts_carry_track_id(anchor_client):
    """When a violation is attributed to a tracked person, the alert row knows."""
    mine = anchor_client.post("/api/mines", json={
        "name": "Anchor Mine D", "code": "ANCH-D1", "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]
    r = anchor_client.post("/api/ai/detect/frame", json=_frame_payload(mine, confidence=0.10))
    assert r.status_code == 200
    body = r.json()
    for a in body["alerts"]:
        assert "track_id" in a
        assert a["source"] == "yolo"


# --------------------------------------------------------------------------- #
# 5. Default strategy byte-compatibility (regression guard)
# --------------------------------------------------------------------------- #
def _default_keys(payload_check_client, mine_id):
    r = payload_check_client.post("/api/ai/detect/frame", json=_frame_payload(mine_id, confidence=0.10))
    return r


@needs_weights
def test_default_strategy_stays_byte_compatible(client):
    """With the flag at its default, the /frame response must not gain new keys."""
    mine = client.post("/api/mines", json={
        "name": "Default Mine Z", "code": "DFLT-Z1", "mine_type": "open_cast",
        "status": "operational", "location": "Test",
    }).json()["id"]
    r = _default_keys(client, mine)
    assert r.status_code == 200
    body = r.json()
    assert "strategy" not in body
    assert "persons" not in body
    assert "person_ppe_report" not in body
    assert "timings" not in body
    assert "evidence_upload" not in body
    for a in body["alerts"]:
        assert "track_id" not in a
    assert body["model"].startswith("yolo:")
    # and events still persist WITH annotated evidence synchronously
    assert body["annotated_image_url"] is not None or body["detection_count"] == 0


# --------------------------------------------------------------------------- #
# 6. ADDITIVE person-crop PPE pass (hardened merge rules)
# --------------------------------------------------------------------------- #
def test_crop_pass_merge_rules_unit():
    """Crop merge rules, exercised directly with a stubbed batch predict:
    Fall-Detected never from a crop; crop-only violation in [bar, 0.50) dropped;
    sub-bar violation kept (honest UNDETERMINED); compliance kept; every kept
    box back-mapped by pure translation into the person's neighbourhood."""
    import numpy as np
    from types import SimpleNamespace
    from app.services.detectors.person_anchor import PersonAnchorDetector, PersonBox

    det = PersonAnchorDetector(
        ppe_model_path="stub", anchor_model_path="stub",
        crop_ppe=True, crop_imgsz=1280, crop_padding=0.12,
    )

    class _B:
        def __init__(self, cls, conf, xyxy):
            self.cls, self.conf, self._xy = cls, conf, xyxy

        @property
        def xyxy(self):
            return np.array([self._xy])

    ppe_model = SimpleNamespace(names={0: "Fall-Detected", 1: "NO-Hardhat", 2: "Hardhat"})

    def fake_predict(imgs, conf, imgsz, verbose):
        results = []
        for img in imgs:
            H, W = img.shape[:2]
            results.append(SimpleNamespace(boxes=[
                _B(0, 0.439, [0.05 * W, 0.05 * H, 0.45 * W, 0.45 * H]),  # fall -> excluded
                _B(1, 0.42, [0.10 * W, 0.50 * H, 0.40 * W, 0.70 * H]),   # [bar,0.50) -> dropped
                _B(1, 0.18, [0.50 * W, 0.50 * H, 0.80 * W, 0.70 * H]),   # sub-bar -> kept
                _B(2, 0.62, [0.50 * W, 0.05 * H, 0.90 * W, 0.25 * H]),   # compliance -> kept
            ]))
        return results

    ppe_model.predict = fake_predict

    img = np.zeros((480, 640, 3), dtype=np.uint8)
    from app.services.detectors.person_anchor import AnchorResult
    result = AnchorResult()
    result.persons = [PersonBox(class_name="person", class_id=0, confidence=0.9,
                                bbox=[100, 100, 300, 400], track_id=1)]
    det._crop_pass(img, ppe_model, 0.10, result)

    names = [(d.class_name, round(d.confidence, 3)) for d in result.detections]
    assert ("Fall-Detected", 0.439) not in names, "fall must never come from a crop"
    assert ("NO-Hardhat", 0.42) not in names, "[bar,0.50) crop-only violation must drop"
    assert ("NO-Hardhat", 0.18) in names, "sub-bar candidate kept for honest review"
    assert ("Hardhat", 0.62) in names, "compliance candidate kept"
    for d in result.detections:  # translation-only back-mapping, no offsets
        assert 70 <= d.bbox[0] and d.bbox[2] <= 330


@needs_weights
def test_crop_mode_no_fullframe_regression():
    """With crop_ppe ON the fixture keeps ALL its full-frame evidence."""
    import cv2
    from app.services.detectors.person_anchor import PersonAnchorDetector

    det = PersonAnchorDetector(
        ppe_model_path=WEIGHTS, anchor_model_path=ANCHOR_WEIGHTS,
        crop_ppe=True, crop_imgsz=1280, crop_padding=0.12, crop_max_persons=4,
    )
    base = PersonAnchorDetector(ppe_model_path=WEIGHTS, anchor_model_path=ANCHOR_WEIGHTS)
    img = cv2.imread("tests/fixtures/mining_test.jpg")
    no_crop = base.detect(img, confidence=0.10, session_key=None)
    with_crop = det.detect(img, confidence=0.10, session_key=None)
    # Invariant: every full-frame detection survives in the crop run — same
    # class, same box (IoU > 0.5), confidence only ever upgraded (the merge
    # keeps the stronger copy when both passes see the same object).
    def _iou(a, b):
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        ua = ((a[2] - a[0]) * (a[3] - a[1])) + ((b[2] - b[0]) * (b[3] - b[1])) - inter
        return inter / ua if ua > 0 else 0.0

    for d in no_crop.detections:
        match = [
            c for c in with_crop.detections
            if c.class_name == d.class_name and _iou(c.bbox, d.bbox) > 0.5
            and c.confidence >= d.confidence - 1e-3
        ]
        assert match, f"full-frame evidence lost: {d.class_name} {d.confidence:.2f} {d.bbox}"
    assert not any(d.class_name.lower() == "fall-detected" for d in with_crop.detections)
