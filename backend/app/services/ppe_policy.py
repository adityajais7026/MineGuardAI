"""PPE decision policy: separate DETECTION confidence from SAFETY DECISION.

Benchmarked on a real underground-mining image + a compliant construction
scene (2026-09-27, see tests/test_ppe_policy.py for the invariants):

  * The SafetyVision model emitted a genuine NO-Hardhat at conf 0.29 while the
    production confidence was 0.40 — a single global threshold hidden a real
    violation. Lowering the global threshold to ~0.10 also surfaced dubious
    detections (e.g. NO-Safety Vest at 0.13 on the same image).
  * Therefore: run inference at a low CAPTURE threshold (candidates), then
    gate VIOLATIONS at a higher, validated, per-class confidence. A
    sub-threshold candidate is never dropped and never alerted: it is reported
    as status=UNDETERMINED for human review.
  * Person-PPE association: a PPE/violation box that overlaps a person box
    (IoU > 0 or containment, area-scaled) is attributed to that person. A
    person with NO associated PPE evidence at all gets status UNDETERMINED —
    NEVER a violation. Absence of detection is not proof of a violation.

All thresholds are configuration-driven; defaults preserve the previous
single-threshold behaviour exactly (capture = violation = YOLO_CONFIDENCE).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class PpeThresholds:
    """Resolved threshold set for one inference run."""

    capture: float
    violation_default: float
    per_class: dict[str, float] = field(default_factory=dict)

    def violation_for(self, model_class: str) -> float:
        """Validated alert bar for a violation class (case-insensitive)."""
        return self.per_class.get(model_class.lower(), self.violation_default)


def resolve_thresholds() -> PpeThresholds:
    """Resolve capture/violation thresholds from configuration.

    None-valued settings fall back to YOLO_CONFIDENCE so existing deployments
    behave exactly as before until the operator opts into the two-stage mode.
    """
    capture = settings.YOLO_CAPTURE_CONFIDENCE
    violation = settings.PPE_VIOLATION_CONFIDENCE
    per_class: dict[str, float] = {}
    if settings.PPE_THRESHOLDS_JSON:
        try:
            raw = json.loads(settings.PPE_THRESHOLDS_JSON)
            per_class = {str(k).lower(): float(v) for k, v in raw.items()}
        except (ValueError, TypeError):
            per_class = {}
    return PpeThresholds(
        capture=float(capture) if capture is not None else settings.YOLO_CONFIDENCE,
        violation_default=float(violation) if violation is not None else settings.YOLO_CONFIDENCE,
        per_class=per_class,
    )


def classify_detection(conf: float, violation_class: str, th: PpeThresholds) -> str:
    """Two-stage classification of one genuine model detection.

    Returns:
      "violation"            — conf >= validated class bar -> event + alert
      "undetermined"         — captured but below the bar -> human review,
                               NEVER a violation, NEVER an alert
      ("compliance" is handled by the caller for worn-PPE classes.)
    """
    return "violation" if conf >= th.violation_for(violation_class) else "undetermined"


def _area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _overlap_frac(small: list[float], big: list[float]) -> float:
    """Fraction of `small` covered by `big` (containment-style association)."""
    ix1, iy1 = max(small[0], big[0]), max(small[1], big[1])
    ix2, iy2 = min(small[2], big[2]), min(small[3], big[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = _area(small)
    return inter / area if area > 0 else 0.0


def associate_with_persons(
    ppe_boxes: list[tuple[str, float, list[float]]],
    person_boxes: list[tuple[float, list[float]]],
    *,
    min_overlap: float = 0.30,
) -> dict[int, list[dict]]:
    """Associate PPE/violation boxes with person boxes (validated geometric rule).

    A PPE box belongs to a person when it overlaps that person's box by at
    least `min_overlap` of the PPE box's area (heads/torsos sit inside the
    person box). Unmatched PPE boxes are still reported by the caller — they
    are genuine model detections — they just have no person attribution.

    Returns: person_index -> list of {class, confidence, bbox, status_source}.
    """
    assoc: dict[int, list[dict]] = {}
    for cls, conf, bbox in ppe_boxes:
        best_idx, best_frac = None, min_overlap
        for idx, (_, pbox) in enumerate(person_boxes):
            frac = _overlap_frac(bbox, pbox)
            if frac > best_frac:
                best_idx, best_frac = idx, frac
        if best_idx is not None:
            assoc.setdefault(best_idx, []).append(
                {"class": cls, "confidence": conf, "bbox": bbox}
            )
    return assoc


def person_ppe_status(assoc: list[dict]) -> str:
    """Honest PPE status for one person from their associated evidence.

    violation-class evidence present -> "VIOLATION" (the model said so);
    worn-PPE evidence only                          -> "PROTECTED";
    nothing at all                                  -> "UNDETERMINED"
    (never "no ppe" — absence of detection is not proof of a violation).
    """
    from app.services.safety_rules import (
        PPE_COMPLIANCE_CLASSES,
        PPE_VIOLATION_CLASSES,
    )

    keys = {a["class"].lower() for a in assoc}
    if keys & set(PPE_VIOLATION_CLASSES):
        return "VIOLATION"
    if keys & set(PPE_COMPLIANCE_CLASSES):
        return "PROTECTED"
    return "UNDETERMINED"
