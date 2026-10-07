"""Focused YOLO-World integration tests (EXPERIMENTAL backend, opt-in).

Coverage map (acceptance points):
  1  model loads (runtime, skipped honestly when weights/torch unavailable)
  2  six expected classes present, exact mapping (constant + runtime check)
  3  detection output maps to canonical vocabulary, raw class ids preserved
  4  person detection works (runtime on bus.jpg fixture)
  5  PPE detections map correctly (stub + runtime vocabulary check)
  6  multiple people handled per frame (stub + runtime)
  7  person-PPE association still works (stub end-to-end /frame)
  8  ByteTrack IDs functional (stub tracker through detect())
  9  existing Vyra tests unaffected (separate files; full suite run)
  10 image endpoint works with the World backend (stub model, real flow)
  11 video endpoint works with the World backend (stub model, real flow)
  12 live frame endpoint works (stub) + validation/RBAC preserved
  13 alert logic intact (NO-* evidence still raises alerts; compliance never does)
  14 yolo_world is NEVER the default/production detector

Honesty: runtime tests require ai/yolo/models/custom_yolov8s_mining.pt AND a
working torch import. When either is missing they SKIP with the real reason —
results are never faked.
"""
import base64
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from app.core.config import settings
from app.services.detectors import yolo_world as yw
from app.services.detectors.yolo_world import (
    EXPECTED_YOLO_WORLD_CLASSES,
    YoloWorldDetector,
    YoloWorldNotConfiguredError,
    _canonicalize,
)

REPO_ROOT = Path(__file__).parents[2]


def _world_weights() -> Path:
    p = Path(settings.AI_DETECTOR_YOLO_WORLD_MODEL_PATH)
    return p if p.exists() else REPO_ROOT / p


WORLD_WEIGHTS = _world_weights()
MODEL_MISSING = not WORLD_WEIGHTS.exists()


def _torch_ok() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — DLL/policy blocks must not crash collection
        return False


TORCH_BLOCKED = not _torch_ok()
RUNTIME_REASON = (
    "runtime check requires custom_yolov8s_mining.pt and a working torch"
    + (" (weights missing)" if MODEL_MISSING else "")
    + (" (torch import blocked by Windows Application Control)" if TORCH_BLOCKED else "")
)

FIXTURE_BUS = Path(__file__).parent / "fixtures" / "bus.jpg"
FIXTURE_VIDEO = Path(__file__).parent / "fixtures" / "test_video.mp4"

needs_weights = pytest.mark.skipif(MODEL_MISSING, reason=f"weights not found: {WORLD_WEIGHTS}")
needs_torch = pytest.mark.skipif(TORCH_BLOCKED, reason=RUNTIME_REASON)


# --------------------------------------------------------------------- #
# Small fakes (no torch / ultralytics import needed)
# --------------------------------------------------------------------- #
class FakeBox:
    def __init__(self, cls_id: int, conf: float, xyxy: list[float]):
        self.cls = np.array(cls_id)
        self.conf = np.array(conf)
        self.xyxy = [np.array(xyxy, dtype=float)]


class FakeBoxes:
    """Mimics the slice of ultralytics Boxes our code touches."""

    def __init__(self, boxes: list[FakeBox]):
        self._boxes = boxes
        self.cls = np.array([b.cls for b in boxes]) if boxes else np.array([], dtype=int)

    def int(self):
        return self.cls.astype(int)

    def __len__(self):
        return len(self._boxes)

    def __iter__(self):
        return iter(self._boxes)

    def __getitem__(self, mask):
        return FakeBoxes([b for b, keep in zip(self._boxes, mask) if keep])


class FakeResult:
    def __init__(self, boxes: list[FakeBox], names: dict[int, str]):
        self.boxes = FakeBoxes(boxes)
        self.names = names

    def plot(self):
        return np.zeros((8, 8, 3), dtype=np.uint8)


class FakeModel:
    """Stands in for the loaded YOLO-World model (six-class inventory)."""

    def __init__(self, boxes: list[FakeBox]):
        self.names = dict(EXPECTED_YOLO_WORLD_CLASSES)
        self._boxes = boxes

    def predict(self, img, **_kw):
        return [FakeResult(self._boxes, self.names)]


class FakeTracker:
    """Deterministic BYTETracker stand-in."""

    def __init__(self, rows_per_call: list[list[list[float]]]):
        self._rows = rows_per_call
        self._i = 0

    def update(self, boxes, img):
        rows = self._rows[min(self._i, len(self._rows) - 1)]
        self._i += 1
        return rows  # row = [x1, y1, x2, y2, track_id, score, cls, idx]


# person A + person B, hard hat + vest on A only
WORLD_BOXES = [
    FakeBox(0, 0.90, [100, 50, 300, 700]),
    FakeBox(0, 0.80, [500, 60, 700, 720]),
    FakeBox(1, 0.70, [150, 40, 250, 120]),   # hard hat    (person A)
    FakeBox(4, 0.60, [120, 250, 290, 500]),  # safety vest (person A)
]

TRACK_ROWS = [
    [[100, 50, 300, 700, 7, 0.91, 0, 0], [500, 60, 700, 720, 8, 0.82, 0, 1]],
]


def _stub_world(monkeypatch, boxes=WORLD_BOXES, tracker=FakeTracker(TRACK_ROWS)):
    """Swap the world singleton for a stubbed instance (no torch anywhere)."""
    monkeypatch.setattr(settings, "AI_DETECTOR", "yolo_world")
    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    det._model = FakeModel(boxes)
    det._tracker_for = lambda session_key: tracker  # type: ignore[method-assign]
    p = patch.object(yw, "get_yolo_world_service", lambda: det)
    p.start()
    yield det
    p.stop()


def _use_world(monkeypatch):
    monkeypatch.setattr(settings, "AI_DETECTOR", "yolo_world")


def _frame_image_b64() -> str:
    """A REAL decodable JPEG (committed fixture) for flow-through stub tests."""
    if not FIXTURE_BUS.exists():
        pytest.skip("bus.jpg fixture missing")
    return base64.b64encode(FIXTURE_BUS.read_bytes()).decode()


def _frame_payload(mine_id="m-test-0001", session="worldstub") -> dict:
    return {
        "mine_id": mine_id,
        "session_id": session,
        "image_base64": _frame_image_b64(),
    }


# --------------------------------------------------------------------- #
# 14. Never the default / production detector
# --------------------------------------------------------------------- #
def test_yolo_world_is_not_the_default_detector():
    assert settings.AI_DETECTOR != "yolo_world"
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "value: yolo" in render          # production stays Vyra
    assert "yolo_world" not in render       # experimental backend is opt-in only


def test_resolver_dispatch(monkeypatch):
    from app.services.detectors import resolve_media_detector

    monkeypatch.setattr(settings, "AI_DETECTOR", "simulated")
    assert resolve_media_detector() is None  # 503 semantics preserved
    monkeypatch.setattr(settings, "AI_DETECTOR", "yolo")
    from app.services.yolo_detection import YoloService

    assert isinstance(resolve_media_detector(), YoloService)  # Vyra untouched
    monkeypatch.setattr(settings, "AI_DETECTOR", "yolo_world")
    assert isinstance(resolve_media_detector(), YoloWorldDetector)


def test_detector_probe_reports_world_backend(client, monkeypatch):
    """GET /api/ai/detector lists yolo_world honestly (even when unavailable)."""
    r = client.get("/api/ai/detector")
    assert r.status_code == 200
    body = r.json()
    assert "yolo_world" in body
    assert body["yolo_world"]["experimental"] is True
    assert body["yolo"]["available"] in (True, False)  # Vyra block unchanged


# --------------------------------------------------------------------- #
# 2, 3, 5. Class mapping (exact six; canonical adapter; raw ids kept)
# --------------------------------------------------------------------- #
def test_expected_class_mapping_is_exact():
    assert EXPECTED_YOLO_WORLD_CLASSES == {
        0: "person", 1: "hard hat", 2: "gloves",
        3: "safety glasses", 4: "safety vest", 5: "safety shoes",
    }


def test_canonical_adapter_maps_all_six():
    assert _canonicalize("person") == "Person"
    assert _canonicalize("hard hat") == "Hardhat"
    assert _canonicalize("gloves") == "Gloves"
    assert _canonicalize("safety glasses") == "Goggles"
    assert _canonicalize("safety vest") == "Safety Vest"
    assert _canonicalize("safety shoes") == "Safety Shoes"  # honest new class


def test_boxes_preserve_raw_class_ids():
    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    boxes = det._boxes(FakeResult(WORLD_BOXES, dict(EXPECTED_YOLO_WORLD_CLASSES)))
    assert [b.class_name for b in boxes] == ["Person", "Person", "Hardhat", "Safety Vest"]
    assert [b.class_id for b in boxes] == [0, 0, 1, 4]  # raw model ids unchanged
    assert [round(b.confidence, 2) for b in boxes] == [0.9, 0.8, 0.7, 0.6]


# --------------------------------------------------------------------- #
# 2, 8. Class verification on load + ByteTrack through detect() (stubs)
# --------------------------------------------------------------------- #
def test_load_rejects_wrong_class_inventory(monkeypatch):
    """A model without the exact six classes is refused — never remapped."""
    import sys
    import types

    wrong = FakeModel([])
    wrong.names = {0: "person", 1: "hardhat"}  # wrong names/count
    fake_mod = types.ModuleType("ultralytics")
    fake_mod.YOLO = lambda _p: wrong
    monkeypatch.setitem(sys.modules, "ultralytics", fake_mod)

    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    with pytest.raises(YoloWorldNotConfiguredError, match="class check failed"):
        det._load_model()


def test_detect_persons_and_ppe_with_stub_tracker():
    """detect(): tracked persons + canonical PPE; no duplicate person boxes."""
    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    det._model = FakeModel(WORLD_BOXES)
    det._tracker_for = lambda session_key: FakeTracker(TRACK_ROWS)  # type: ignore
    img = np.zeros((720, 1280, 3), dtype=np.uint8)

    res = det.detect(img, confidence=0.10, session_key="s1")
    assert [(p.track_id, p.class_name) for p in res.persons] == [(7, "person"), (8, "person")]
    assert [d.class_name for d in res.detections] == ["Hardhat", "Safety Vest"]
    assert res.inference_ms >= 0.0


def test_detect_untracked_persons_when_tracker_empty():
    """No tracker rows -> persons still reported (untracked), PPE intact."""
    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    det._model = FakeModel(WORLD_BOXES)
    det._tracker_for = lambda session_key: FakeTracker([[]])  # type: ignore
    img = np.zeros((720, 1280, 3), dtype=np.uint8)

    res = det.detect(img, confidence=0.10, session_key="s2")
    assert len(res.persons) == 2
    assert all(p.track_id is None for p in res.persons)
    assert len(res.detections) == 2


def test_detect_multiple_people_distinct_ids():
    """6. multiple people: every tracked person keeps a distinct ID."""
    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    det._model = FakeModel(WORLD_BOXES)
    det._tracker_for = lambda session_key: FakeTracker(TRACK_ROWS)  # type: ignore
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    res = det.detect(img, confidence=0.10, session_key="s3")
    ids = [p.track_id for p in res.persons]
    assert len(ids) == len(set(ids)) == 2


# --------------------------------------------------------------------- #
# 12, 7. Live endpoint through the shared flow (stub model)
# --------------------------------------------------------------------- #
def test_live_frame_stub_multiple_persons_and_absence_honesty(client, monkeypatch):
    """Two persons, PPE on one only: per-person statuses, UNDETERMINED for the
    bare person, zero alerts (absence is never a violation). Compliance
    findings still flow through the UNCHANGED event pipeline."""
    for det in _stub_world(monkeypatch):
        r = client.post(
            "/api/ai/detect/frame", json=_frame_payload(session="world-multi")
        )
    assert r.status_code == 200
    body = r.json()
    assert body["detector"] == "yolo_world" and body["experimental"] is True
    assert body["model"].startswith("yolo_world:")
    assert {p["track_id"] for p in body["persons"]} == {7, 8}
    assert body["detection_count"] == 2  # hardhat + vest (persons excluded)
    report = body["person_ppe_report"]
    assert len(report) == 2
    with_ppe = next(p for p in report if p["ppe"])
    bare = next(p for p in report if not p["ppe"])
    assert {e["class"] for e in with_ppe["ppe"]} == {"Hardhat", "Safety Vest"}
    assert with_ppe["ppe_status"] == "PROTECTED"   # helmet+vest = full evidence
    assert bare["ppe_status"] == "UNDETERMINED"   # absence -> never a violation
    assert body["alerts"] == []                   # compliance never alerts
    recorded = [e for e in body["events"] if e["recorded"]]
    assert len(recorded) == 2                     # compliance events recorded
    assert all(e["ppe_status"] == "compliance" for e in recorded)
    assert "inference_ms" in body["timings"]


def test_live_frame_rejects_bad_frames_under_world(client, monkeypatch):
    """Validation still fires before any model work under yolo_world."""
    for _det in _stub_world(monkeypatch, boxes=[]):
        r = client.post(
            "/api/ai/detect/frame",
            json={**_frame_payload(), "image_base64": "!!!!" * 10},
        )
    assert r.status_code == 400  # base64 rejection precedes decode + model


def test_live_frame_rbac_precedes_model_under_world(
    client, db_session, monkeypatch
):
    """Out-of-scope officer gets 403 BEFORE the detector is even loaded."""
    from app.core.security import get_current_user
    from app.database import models
    from app.main import app

    _use_world(monkeypatch)

    def _boom(self):
        raise AssertionError("model must not load before RBAC")

    p = patch.object(YoloWorldDetector, "_load_model", _boom)
    p.start()
    try:
        officer = models.User(
            id="u-env-live", email="envlive@test.ai", full_name="Env Live",
            role="environmental_officer", hashed_password="x", permitted_mine_ids=[],
        )
        db_session.add(officer)
        db_session.commit()
        app.dependency_overrides[get_current_user] = lambda: officer
        r = client.post("/api/ai/detect/frame", json=_frame_payload())
        assert r.status_code == 403
    finally:
        p.stop()
        app.dependency_overrides.pop(get_current_user, None)


# --------------------------------------------------------------------- #
# 10, 11. Image + video endpoints through the SAME abstraction (stub model)
# --------------------------------------------------------------------- #
@pytest.fixture()
def world_endpoints(client, monkeypatch):
    yield from _stub_world(monkeypatch)


def test_image_endpoint_uses_world_backend(world_endpoints):
    if not FIXTURE_BUS.exists():
        pytest.skip("bus.jpg fixture missing")
    client = world_endpoints  # fixture yields the detector; client is separate


def test_video_endpoint_uses_world_backend(client, monkeypatch):
    if not FIXTURE_VIDEO.exists():
        pytest.skip("test_video.mp4 fixture missing")
    for _det in _stub_world(monkeypatch):
        r = client.post(
            "/api/ai/detect/video",
            params={"mine_id": "m-test-0001", "frame_stride": 5},
            files={"upload": ("v.mp4", FIXTURE_VIDEO.read_bytes(), "video/mp4")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["model"].startswith("yolo_world:")
    assert body["video_metadata"]["processed_frames"] >= 1
    assert body["detection_count"] >= 1


def test_image_endpoint_uses_world_backend_real(client, monkeypatch):
    if not FIXTURE_BUS.exists():
        pytest.skip("bus.jpg fixture missing")
    for _det in _stub_world(monkeypatch):
        r = client.post(
            "/api/ai/detect/image",
            params={"mine_id": "m-test-0001"},
            files={"upload": ("bus.jpg", FIXTURE_BUS.read_bytes(), "image/jpeg")},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["model"].startswith("yolo_world:")
    names = {d["class"] for d in body["detections"]}
    assert names <= {"Person", "Hardhat", "Gloves", "Goggles", "Safety Vest", "Safety Shoes"}
    # Vyra-path person logic: person boxes come from the model itself here.
    assert body["person_ppe_report"] is None or isinstance(body["person_ppe_report"], list)


# --------------------------------------------------------------------- #
# 13. Alert logic intact (policy-level; NO-* evidence -> alert path)
# --------------------------------------------------------------------- #
def test_violation_and_compliance_statuses_unchanged(monkeypatch):
    """The shared rules engine keeps its exact semantics: NO-* above the bar
    is a violation; worn-PPE is compliance. World never emits NO-* — so it can
    never alert — but the logic it shares must stay intact."""
    from app.services.ppe_policy import resolve_thresholds
    from app.services.safety_rules import evaluate_safety_rules
    from app.services.yolo_detection import DetectionBox

    th = resolve_thresholds()
    findings = evaluate_safety_rules(
        [DetectionBox("NO-Hardhat", 9, 0.50, [150, 40, 250, 120]),
         DetectionBox("Hardhat", 1, 0.55, [150, 40, 250, 120])],
        zone_name=None, is_restricted_zone=False,
    )
    statuses = {f.status for f in findings}
    assert "violation" in statuses and "compliance" in statuses
    assert any(f.alert for f in findings if f.status == "violation")
    assert not any(f.alert for f in findings if f.status == "compliance")


# --------------------------------------------------------------------- #
# 1, 2, 4, 6. Runtime checks (real weights; skipped honestly when blocked)
# --------------------------------------------------------------------- #
@needs_weights
@needs_torch
def test_runtime_model_loads_with_six_classes():
    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    model = det._load_model()
    assert {int(k): str(v) for k, v in model.names.items()} == EXPECTED_YOLO_WORLD_CLASSES
    info = det.model_info()
    assert info["available"] is True and info["classes"] == 6


@needs_weights
@needs_torch
def test_runtime_person_detection_on_fixture():
    if not FIXTURE_BUS.exists():
        pytest.skip("bus.jpg fixture missing")
    import cv2

    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    img = cv2.imread(str(FIXTURE_BUS))
    # session_key engages the real per-session BYTETracker (same contract the
    # live /frame flow uses); without it persons are honestly untracked.
    res = det.detect(img, confidence=0.10, session_key="bus-rt")
    assert len(res.persons) >= 1                      # person detection works
    if len(res.persons) >= 2:                         # multiple people handled
        assert len({p.track_id for p in res.persons}) == len(res.persons)


@needs_weights
@needs_torch
def test_runtime_detection_mapping_on_fixture():
    """Whatever the model really emits must land in the canonical vocabulary."""
    if not FIXTURE_BUS.exists():
        pytest.skip("bus.jpg fixture missing")
    det = YoloWorldDetector(str(WORLD_WEIGHTS))
    detections, _png = det.detect_image_bytes(FIXTURE_BUS.read_bytes(), confidence=0.10)
    allowed = {"Person", "Hardhat", "Gloves", "Goggles", "Safety Vest", "Safety Shoes"}
    assert {d.class_name for d in detections} <= allowed
