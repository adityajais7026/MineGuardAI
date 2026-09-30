"""
Safety rule evaluation over REAL YOLO detections (enhancement phase + PPE).

IMPORTANT SEPARATION OF CONCERNS
--------------------------------
Rules are evaluated ONLY over classes the configured model actually detects.
With the generic COCO model (person, car, truck, ...) only the object/zone
rules R1-R3 can fire — PPE violations are never inferred. With a fine-tuned
PPE model (e.g. SafetyVision YOLOv8s, whose trained classes include
NO-Hardhat / NO-Safety Vest / ...), the *model's own* violation-class
detections drive the PPE findings below. Absence of a PPE detection is never
treated as a violation, and class names are never renamed.

Zone rules (zone binding comes from the upload context, not the model):
  R1 restricted_zone_person : a *person* detected while the event is bound to
     a restricted zone.
  R2 restricted_zone_vehicle: a *vehicle-class* object bound to a restricted
     zone (only when the configured model has vehicle classes).
  R3 crowd_threshold        : >= N persons in one frame (configurable).

PPE rules (only when the model genuinely provides the class):
  each NO-* / Fall-Detected detection -> a violation finding that raises an
  alert; each worn-PPE detection (Hardhat, Safety Vest, ...) -> a compliance
  finding that records the event WITHOUT raising an alert.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.ppe_policy import classify_detection, resolve_thresholds
from app.services.yolo_detection import PERSON_CLASSES, VEHICLE_CLASSES, DetectionBox

# --------------------------------------------------------------------------- #
# PPE class mapping — exact class names of the fine-tuned SafetyVision YOLOv8s
# PPE model (verified against the weights file; matched case-insensitively).
#   class (lowercased) -> (event_type, severity, raises_alert, rule_name)
# Violation classes exist because the model was TRAINED on them; no violation
# is ever inferred from a missing detection.
# NOTE: the model has NO boots/protective-footwear classes, so footwear rules
# are intentionally absent — they cannot be honestly supported yet.
# --------------------------------------------------------------------------- #
PPE_VIOLATION_CLASSES: dict[str, tuple[str, str, bool, str]] = {
    "no-hardhat": ("person_without_helmet", "high", True, "no_hardhat"),
    "no-safety vest": ("person_without_safety_vest", "high", True, "no_safety_vest"),
    "no-gloves": ("person_without_gloves", "medium", True, "no_gloves"),
    "no-goggles": ("person_without_goggles", "medium", True, "no_goggles"),
    "no-mask": ("person_without_mask", "medium", True, "no_mask"),
    "no_harness": ("person_without_harness", "high", True, "no_harness"),
    "fall-detected": ("fall_detected", "critical", True, "fall_detected"),
}

# Worn-PPE classes -> compliance event types (recorded, never alerted).
PPE_COMPLIANCE_CLASSES: dict[str, str] = {
    "hardhat": "helmet_detected",
    "safety vest": "safety_vest_detected",
    "gloves": "gloves_detected",
    "goggles": "goggles_detected",
    "mask": "mask_detected",
}

# All classes with dedicated PPE handling (excluded from generic 'other' events).
PPE_HANDLED_CLASSES = frozenset(PPE_VIOLATION_CLASSES) | frozenset(PPE_COMPLIANCE_CLASSES)

# Alert type mapping used by the camera pipeline.
RULE_EVENT_TYPES = {
    "restricted_zone_person": "restricted_zone_entry",
    "restricted_zone_vehicle": "vehicle_in_restricted_area",
    "crowd_threshold": "unsafe_crowding",
}
RULE_SEVERITY = {
    "restricted_zone_person": "critical",
    "restricted_zone_vehicle": "high",
    "crowd_threshold": "medium",
}


@dataclass
class SafetyFinding:
    rule: str
    event_type: str
    severity: str
    evidence: str  # human-readable explanation from real detection data
    alert: bool = True            # False -> record only (compliance detections)
    confidence: float | None = None   # model confidence of the triggering detection
    detected_class: str | None = None  # raw model class name (never renamed)
    # Two-stage decision outcome for PPE detections:
    #   "violation"    -> above the validated class bar: event + alert
    #   "undetermined" -> genuine capture, below the bar: review, never alert
    #   "compliance"   -> worn-PPE detection: record only
    status: str = "violation"


def evaluate_safety_rules(
    detections: list[DetectionBox],
    *,
    zone_name: str | None,
    is_restricted_zone: bool,
) -> list[SafetyFinding]:
    """Evaluate configurable rules over actual detections. No fabrication."""
    findings: list[SafetyFinding] = []
    th = resolve_thresholds()
    # Case-insensitive matching: e.g. the SafetyVision PPE model emits 'Person'.
    persons = [d for d in detections if d.class_name.lower() in PERSON_CLASSES]
    vehicles = [d for d in detections if d.class_name.lower() in VEHICLE_CLASSES]

    # ---- PPE rules: only from genuine violation-class detections -------------
    # Two-stage decision: the model's detection is real, but it only becomes a
    # VIOLATION (event + alert) above the validated per-class bar; below it the
    # finding is UNDETERMINED — reported for review, never alerted.
    for d in detections:
        key = d.class_name.lower()
        if key in PPE_VIOLATION_CLASSES:
            event_type, severity, _alert, rule = PPE_VIOLATION_CLASSES[key]
            decision = classify_detection(d.confidence, key, th)
            if decision == "violation":
                findings.append(SafetyFinding(
                    rule=rule,
                    event_type=event_type,
                    severity=severity,
                    evidence=(
                        f"{d.class_name} detected (confidence {d.confidence:.2f}) "
                        f"by the PPE model"
                    ),
                    alert=True,
                    confidence=d.confidence,
                    detected_class=d.class_name,
                    status="violation",
                ))
            else:
                findings.append(SafetyFinding(
                    rule=rule,
                    event_type=event_type,  # the model DID detect this class;
                    severity="low",         # below the bar -> review, no alert
                    evidence=(
                        f"{d.class_name} detected (confidence {d.confidence:.2f}) "
                        f"below the violation threshold "
                        f"({th.violation_for(key):.2f}) — PPE STATUS: UNDETERMINED, "
                        f"manual review recommended"
                    ),
                    alert=False,
                    confidence=d.confidence,
                    detected_class=d.class_name,
                    status="undetermined",
                ))
        elif key in PPE_COMPLIANCE_CLASSES:
            findings.append(SafetyFinding(
                rule=f"{key.replace(' ', '_').replace('-', '_')}_detected",
                event_type=PPE_COMPLIANCE_CLASSES[key],
                severity="low",
                evidence=(
                    f"{d.class_name} detected (confidence {d.confidence:.2f}) "
                    f"by the PPE model — PPE worn"
                ),
                alert=False,
                confidence=d.confidence,
                detected_class=d.class_name,
                status="compliance",
            ))

    if is_restricted_zone and persons:
        best = max(persons, key=lambda d: d.confidence)
        findings.append(SafetyFinding(
            rule="restricted_zone_person",
            event_type=RULE_EVENT_TYPES["restricted_zone_person"],
            severity=RULE_SEVERITY["restricted_zone_person"],
            evidence=(
                f"person detected (confidence {best.confidence:.2f}) in restricted zone "
                f"'{zone_name or 'unknown'}' — zone binding from upload context"
            ),
        ))

    if is_restricted_zone and vehicles:
        best = max(vehicles, key=lambda d: d.confidence)
        findings.append(SafetyFinding(
            rule="restricted_zone_vehicle",
            event_type=RULE_EVENT_TYPES["restricted_zone_vehicle"],
            severity=RULE_SEVERITY["restricted_zone_vehicle"],
            evidence=(
                f"{best.class_name} detected (confidence {best.confidence:.2f}) in restricted "
                f"zone '{zone_name or 'unknown'}'"
            ),
        ))

    crowd_n = settings.YOLO_CROWD_THRESHOLD
    if len(persons) >= crowd_n:
        findings.append(SafetyFinding(
            rule="crowd_threshold",
            event_type=RULE_EVENT_TYPES["crowd_threshold"],
            severity=RULE_SEVERITY["crowd_threshold"],
            evidence=f"{len(persons)} persons detected (threshold {crowd_n})",
        ))

    return findings
