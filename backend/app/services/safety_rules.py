"""
Safety rule evaluation over REAL YOLO detections (enhancement phase).

IMPORTANT SEPARATION OF CONCERNS
--------------------------------
A pretrained COCO model detects *objects* (person, car, truck, ...). It does
NOT detect helmets, vests, PPE compliance, falls or "restricted zone" by
itself. This module therefore evaluates **legitimate rules on actual detected
classes** (e.g. a person inside a designated restricted zone), and never
fabricates specialised mining-safety detections.

Rules (each produces at most one alert per image/clip, deduped downstream):
  R1 restricted_zone_person : a *person* detected while the event is bound to
     a restricted zone (the zone binding comes from the upload context, not
     from the model).
  R2 restricted_zone_vehicle: a *vehicle-class* object bound to a restricted
     zone (zone has vehicles_forbidden semantics in the demo data).
  R3 crowd_threshold        : >= N persons in one frame (configurable).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.yolo_detection import PERSON_CLASSES, VEHICLE_CLASSES, DetectionBox

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


def evaluate_safety_rules(
    detections: list[DetectionBox],
    *,
    zone_name: str | None,
    is_restricted_zone: bool,
) -> list[SafetyFinding]:
    """Evaluate configurable rules over actual detections. No fabrication."""
    findings: list[SafetyFinding] = []
    persons = [d for d in detections if d.class_name in PERSON_CLASSES]
    vehicles = [d for d in detections if d.class_name in VEHICLE_CLASSES]

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
