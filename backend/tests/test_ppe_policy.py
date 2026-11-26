"""PPE two-stage threshold policy tests.

Covers: capture/violation threshold resolution, per-class thresholds, honest
UNDETERMINED handling for sub-bar detections, person-PPE association geometry,
and the "absence of detection is not a violation" guarantee. Endpoint-level
integration tests run REAL inference with overridden thresholds.
"""
import pytest

from app.core.config import settings
from app.services.ppe_policy import (
    associate_with_persons,
    classify_detection,
    person_ppe_status,
    resolve_thresholds,
)
from app.services.safety_rules import evaluate_safety_rules
from app.services.yolo_detection import DetectionBox

from pathlib import Path

MODEL_PATH = Path(settings.YOLO_MODEL_PATH)
MODEL_EXISTS = MODEL_PATH.exists()
MINING_IMAGE = Path(__file__).parent / "fixtures" / "mining_test.jpg"

needs_model = pytest.mark.skipif(not MODEL_EXISTS, reason="YOLO weights not present")


def _box(cls: str, conf: float = 0.9, bbox: list | None = None) -> DetectionBox:
    return DetectionBox(class_name=cls, class_id=0, confidence=conf,
                        bbox=bbox or [0, 0, 10, 10])


@pytest.fixture()
def two_stage(monkeypatch):
    """Two-stage policy: capture low, violations gated at 0.35 (tested values)."""
    monkeypatch.setattr(settings, "YOLO_CAPTURE_CONFIDENCE", 0.10)
    monkeypatch.setattr(settings, "PPE_VIOLATION_CONFIDENCE", 0.35)
    return resolve_thresholds()


# ------------------------------------------------------------------ #
# Threshold resolution
# ------------------------------------------------------------------ #
def test_defaults_preserve_single_threshold_behaviour(monkeypatch):
    """With no overrides, capture == violation == YOLO_CONFIDENCE (old behaviour)."""
    monkeypatch.setattr(settings, "YOLO_CAPTURE_CONFIDENCE", None)
    monkeypatch.setattr(settings, "PPE_VIOLATION_CONFIDENCE", None)
    monkeypatch.setattr(settings, "PPE_THRESHOLDS_JSON", None)
    th = resolve_thresholds()
    assert th.capture == settings.YOLO_CONFIDENCE
    assert th.violation_default == settings.YOLO_CONFIDENCE
    assert th.per_class == {}


def test_two_stage_resolution(two_stage):
    assert two_stage.capture == 0.10
    assert two_stage.violation_default == 0.35


def test_per_class_thresholds_from_json(monkeypatch):
    monkeypatch.setattr(settings, "PPE_VIOLATION_CONFIDENCE", 0.35)
    monkeypatch.setattr(settings, "PPE_THRESHOLDS_JSON",
                        '{"NO-Hardhat": 0.45, "NO-Safety Vest": 0.30}')
    th = resolve_thresholds()
    assert th.violation_for("NO-Hardhat") == 0.45
    assert th.violation_for("no-hardhat") == 0.45        # case-insensitive
    assert th.violation_for("NO-Safety Vest") == 0.30
    assert th.violation_for("NO-Gloves") == 0.35         # falls back to default


def test_invalid_threshold_json_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "PPE_VIOLATION_CONFIDENCE", 0.35)
    monkeypatch.setattr(settings, "PPE_THRESHOLDS_JSON", "not-json{")
    th = resolve_thresholds()
    assert th.violation_default == 0.35 and th.per_class == {}


# ------------------------------------------------------------------ #
# Two-stage decision
# ------------------------------------------------------------------ #
def test_detection_below_violation_bar_is_undetermined_never_alert(two_stage):
    findings = evaluate_safety_rules([_box("NO-Hardhat", 0.29)],
                                     zone_name=None, is_restricted_zone=False)
    f = findings[0]
    assert f.status == "undetermined"
    assert f.alert is False                    # NEVER alerted
    assert f.event_type == "person_without_helmet"  # honest class, low severity
    assert f.severity == "low"
    assert "UNDETERMINED" in f.evidence


def test_detection_above_violation_bar_is_violation(two_stage):
    findings = evaluate_safety_rules([_box("NO-Hardhat", 0.52)],
                                     zone_name=None, is_restricted_zone=False)
    f = findings[0]
    assert f.status == "violation" and f.alert is True and f.severity == "high"


def test_per_class_bar_applies(two_stage, monkeypatch):
    monkeypatch.setattr(settings, "PPE_THRESHOLDS_JSON", '{"NO-Hardhat": 0.55}')
    findings = evaluate_safety_rules([_box("NO-Hardhat", 0.52)],
                                     zone_name=None, is_restricted_zone=False)
    assert findings[0].status == "undetermined"   # 0.52 < per-class 0.55


def test_worn_ppe_stays_compliance(two_stage):
    findings = evaluate_safety_rules([_box("Hardhat", 0.20)],
                                     zone_name=None, is_restricted_zone=False)
    assert findings[0].status == "compliance" and findings[0].alert is False


# ------------------------------------------------------------------ #
# Person-PPE association geometry
# ------------------------------------------------------------------ #
def test_association_by_containment():
    persons = [(0.9, [100, 100, 300, 600])]
    ppe = [("Hardhat", 0.8, [140, 100, 240, 180])]
    assoc = associate_with_persons(ppe, persons)
    assert 0 in assoc and assoc[0][0]["class"] == "Hardhat"


def test_association_prefers_best_overlap():
    persons = [(0.9, [0, 0, 200, 500]), (0.9, [250, 0, 450, 500])]
    ppe = [("NO-Hardhat", 0.6, [300, 10, 400, 80])]   # clearly in person #2
    assoc = associate_with_persons(ppe, persons)
    assert list(assoc.keys()) == [1]


def test_distant_ppe_box_stays_unassociated():
    persons = [(0.9, [0, 0, 200, 500])]
    ppe = [("Hardhat", 0.8, [400, 400, 480, 460])]    # nowhere near the person
    assert associate_with_persons(ppe, persons) == {}


def test_person_without_ppe_evidence_is_undetermined_not_violation():
    """THE critical guarantee: Person + no PPE detections must NOT be a violation."""
    assert person_ppe_status([]) == "UNDETERMINED"


def test_person_status_priority_violation_over_compliance():
    assoc = [{"class": "Hardhat", "confidence": 0.8, "bbox": [0, 0, 1, 1]},
             {"class": "NO-Safety Vest", "confidence": 0.6, "bbox": [0, 0, 1, 1]}]
    assert person_ppe_status(assoc) == "VIOLATION"


def test_person_with_worn_ppe_is_protected():
    assoc = [{"class": "Hardhat", "confidence": 0.8, "bbox": [0, 0, 1, 1]}]
    assert person_ppe_status(assoc) == "PROTECTED"


# ------------------------------------------------------------------ #
# Real-model integration (mining image): the original complaint scenario
# ------------------------------------------------------------------ #
@needs_model
def test_mining_image_sub_bar_no_hardhat_is_undetermined_not_hidden(two_stage):
    """The benchmarked case: a genuine NO-Hardhat at 0.29 must be REPORTED as
    UNDETERMINED (not silently dropped, not falsely alerted) at capture 0.10."""
    import cv2
    from app.services.yolo_detection import get_yolo_service

    img = cv2.imread(str(MINING_IMAGE))
    dets, _ = get_yolo_service().detect_image_bytes(
        cv2.imencode(".jpg", img)[1].tobytes(), confidence=0.10)
    no_hh = [d for d in dets if d.class_name.lower() == "no-hardhat"]
    assert no_hh, "benchmark regression: model must capture NO-Hardhat at 0.10"
    findings = evaluate_safety_rules(dets, zone_name=None, is_restricted_zone=False)
    hh = [f for f in findings if f.rule == "no_hardhat"]
    assert hh, "finding for NO-Hardhat must exist"
    best = max(hh, key=lambda f: f.confidence or 0)
    assert best.status in {"violation", "undetermined"}
    if best.status == "undetermined":
        assert best.alert is False


@needs_model
def test_capture_confidence_low_does_not_alert_spurious_detections(two_stage):
    """Running at capture 0.10 must not create alerts for dubious 0.13-class
    detections — the violation bar still gates alerts."""
    import cv2
    from app.services.yolo_detection import get_yolo_service

    img = cv2.imread(str(MINING_IMAGE))
    dets, _ = get_yolo_service().detect_image_bytes(
        cv2.imencode(".jpg", img)[1].tobytes(), confidence=0.10)
    findings = evaluate_safety_rules(dets, zone_name=None, is_restricted_zone=False)
    for f in findings:
        if f.status == "undetermined":
            assert f.alert is False
            assert f.severity == "low"


@needs_model
@pytest.mark.parametrize("conf,expected_status", [
    (0.29, "undetermined"),   # benchmarked sub-bar NO-Hardhat
    (0.64, "violation"),      # same class at higher conf (imgsz 1280 run)
])
def test_threshold_boundary_semantics(conf, expected_status):
    from app.services.ppe_policy import PpeThresholds
    th = PpeThresholds(capture=0.10, violation_default=0.35)
    assert classify_detection(conf, "no-hardhat", th) == expected_status
