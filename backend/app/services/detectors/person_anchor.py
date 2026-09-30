"""Person-anchor detector strategy: keep the production PPE model (Vyra) and
add a lightweight COCO person detector purely to supply PERSON boxes + IDs.

Architecture (opt-in via AI_DETECTOR_STRATEGY=person_anchor):

    COCO yolo11n  ->  person boxes  ->  ByteTrack  ->  persistent person IDs
    Vyra yolov8m  ->  PPE boxes (hardhat/vest/... — UNCHANGED production model)
                  ↓
    ppe_policy.associate_with_persons()   (EXISTING policy code, untouched)
                  ↓
    per-person PPE verdicts + person-specific alerts

Measured basis (tmp_diag/bench_models.py, 2026-09-28):
  * Vyra emits NO 'Person' class at all (verified at conf floor 0.01) — so the
    production per-person association layer is inert without an anchor.
  * yolo11n anchor run: ~48 ms avg @640 CPU, 4-8 persons/scene, robust to
    ~150 px tall persons.

ByteTrack: the Ultralytics model-level tracker is stateful, so ONE tracker
instance per live session is kept here (keyed by session key) with
persist=True between frames of the same session. IDs are only guaranteed
stable WITHIN a session; a new session restarts numbering (documented).

Evidence honesty:
  * Person boxes carry class_name='person' (COCO convention) so the existing
    association works unmodified.
  * NO PPE classification is ever taken from the anchor model.
  * Class inventories are reported honestly (no fabricated Boots/Gloves).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from app.services.yolo_detection import DetectionBox

logger = logging.getLogger(__name__)


@dataclass
class PersonBox:
    """One person with a persistent (within-session) ByteTrack ID."""
    class_name: str          # always 'person'
    class_id: int            # always 0
    confidence: float
    bbox: list[float]        # xyxy pixels
    track_id: int | None     # None only if the tracker dropped the box this frame

    def as_dict(self) -> dict:
        return {
            "class": self.class_name,
            "class_id": self.class_id,
            "confidence": round(self.confidence, 4),
            "bbox": [round(v, 1) for v in self.bbox],
            "track_id": self.track_id,
        }


@dataclass
class AnchorResult:
    """Combined result of the anchor (persons+IDs) and the PPE model."""
    detections: list[DetectionBox] = field(default_factory=list)  # PPE boxes (Vyra)
    persons: list[PersonBox] = field(default_factory=list)        # person boxes + IDs
    ppe_ms: float = 0.0
    anchor_ms: float = 0.0
    crop_ms: float = 0.0  # per-person crop pass (0 when disabled)

    @property
    def total_ms(self) -> float:
        return self.ppe_ms + self.anchor_ms + self.crop_ms


# --------------------------------------------------------------------------- #
# Class-name adapter (ADDITIVE, no-op for the production Vyra model).
#
# The PPE policy / association / UI layers speak Vyra's internal vocabulary
# ('Hardhat', 'NO-Hardhat', 'Safety Vest', ...). Alternate PPE models trained
# on the normalized custom taxonomy use snake_case names ('no_helmet', ...).
# This alias table presents such models in the production vocabulary so the
# EXISTING policy logic handles them unchanged. Vyra's own names contain none
# of the alias keys, so production behavior is byte-identical. The model's
# raw class_id is preserved on every DetectionBox (internal classes unchanged).
CANONICAL_CLASS_ALIASES: dict[str, str] = {
    "helmet": "Hardhat",
    "no_helmet": "NO-Hardhat",
    "safety_vest": "Safety Vest",
    "no_safety_vest": "NO-Safety Vest",
    "gloves": "Gloves",
    "no_gloves": "NO-Gloves",
    "goggles": "Goggles",
    "no_goggles": "NO-Goggles",
    "mask": "Mask",
    "no_mask": "NO-Mask",
    "person": "Person",
}


def _canonicalize_class(raw_name: str) -> str:
    return CANONICAL_CLASS_ALIASES.get(raw_name.strip().lower(), raw_name)


class PersonAnchorDetector:
    """COCO person anchor (yolo11n) + ByteTrack, with the configured PPE model.

    One instance holds per-session trackers; call with the same session key to
    keep IDs persistent across frames of that session.
    """

    def __init__(self, ppe_model_path: str, anchor_model_path: str,
                 anchor_conf: float = 0.25, max_trackers: int = 16,
                 crop_ppe: bool = False, crop_imgsz: int = 1280,
                 crop_padding: float = 0.12, crop_every_n: int = 1,
                 crop_max_persons: int = 2):
        self.ppe_model_path = ppe_model_path
        self.anchor_model_path = anchor_model_path
        self.anchor_conf = anchor_conf
        # ADDITIVE per-person crop inference (diagnosed on real webcam frames:
        # full-frame letterboxing shrinks heads below Vyra's operating scale;
        # a padded person crop at imgsz 1280 recovers weak evidence). The
        # full-frame PPE pass ALWAYS runs; crops only ADD candidates.
        self.crop_ppe = crop_ppe
        self.crop_imgsz = crop_imgsz
        self.crop_padding = crop_padding
        # Latency guardrails: the hi-res crop pass runs every Nth frame of a
        # session (1 = every frame) and for at most this many persons.
        self.crop_every_n = max(1, crop_every_n)
        self.crop_max_persons = max(1, crop_max_persons)
        self._frame_counts: dict[str, int] = {}
        self._ppe = None
        self._anchor = None
        self._trackers: dict[str, object] = {}
        self._max_trackers = max_trackers

    def _load(self):
        if self._ppe is None or self._anchor is None:
            from ultralytics import YOLO
            if not os.path.exists(self.ppe_model_path):
                raise FileNotFoundError(f"PPE model missing: {self.ppe_model_path}")
            if not os.path.exists(self.anchor_model_path):
                raise FileNotFoundError(f"Anchor model missing: {self.anchor_model_path}")
            self._ppe = YOLO(self.ppe_model_path)
            self._anchor = YOLO(self.anchor_model_path)
            logger.info("PersonAnchorDetector loaded: PPE=%s anchor=%s",
                        os.path.basename(self.ppe_model_path), os.path.basename(self.anchor_model_path))
        return self._ppe, self._anchor

    def _tracker_for(self, session_key: str):
        """One ByteTrack instance per live session (IDs persist within it)."""
        tr = self._trackers.get(session_key)
        if tr is None:
            from ultralytics.trackers.byte_tracker import BYTETracker
            from types import SimpleNamespace
            args = SimpleNamespace(
                track_high_thresh=0.25, track_low_thresh=0.1, new_track_thresh=0.25,
                track_buffer=30, match_thresh=0.8, fuse_score=True,
            )
            tr = BYTETracker(args)  # one per live session; IDs persist within it
            # Bound memory: drop the oldest tracker beyond the cap.
            if len(self._trackers) >= self._max_trackers:
                self._trackers.pop(next(iter(self._trackers)))
            self._trackers[session_key] = tr
        return tr

    def info(self) -> dict:
        ppe, anchor = self._load()
        return {
            "strategy": "person_anchor",
            "ppe_model": os.path.basename(self.ppe_model_path),
            "ppe_classes": len(ppe.names),
            "ppe_class_names": sorted(ppe.names.values()),
            "anchor_model": os.path.basename(self.anchor_model_path),
            "anchor_conf": self.anchor_conf,
            "tracker": "bytetrack",
            "id_scope": "per-session",
            "crop_ppe": self.crop_ppe,
            "crop_imgsz": self.crop_imgsz if self.crop_ppe else None,
        }

    def detect(self, img, *, confidence: float, imgsz: int = 640,
               session_key: str | None = None) -> AnchorResult:
        """One frame: anchor (persons+track IDs) + PPE model (unchanged classes)."""
        ppe_model, anchor_model = self._load()
        result = AnchorResult()

        # --- anchor: person boxes + persistent IDs (ByteTrack) --------------
        t0 = time.perf_counter()
        tracker = self._tracker_for(session_key) if session_key else None
        ar = anchor_model.predict(img, conf=self.anchor_conf, imgsz=imgsz, verbose=False)[0]
        if tracker is not None and len(ar.boxes):
            # BYTETracker consumes a Results-like object (.conf/.xywh/.cls with
            # boolean indexing) — Boxes provides exactly that.
            tracks = tracker.update(ar.boxes, img)
            for t in tracks:  # row = [x1, y1, x2, y2, track_id, score, cls, idx]
                if int(t[6]) != 0:  # COCO person only
                    continue
                result.persons.append(PersonBox(
                    class_name="person", class_id=0, confidence=float(t[5]),
                    bbox=[float(t[0]), float(t[1]), float(t[2]), float(t[3])],
                    track_id=int(t[4]),
                ))
        else:
            for box in ar.boxes:
                if int(box.cls) == 0:
                    result.persons.append(PersonBox(
                        class_name="person", class_id=0, confidence=float(box.conf),
                        bbox=[float(v) for v in box.xyxy[0].tolist()], track_id=None,
                    ))
        result.anchor_ms = (time.perf_counter() - t0) * 1000

        # --- PPE model: production Vyra, unchanged (full frame) -------------
        t1 = time.perf_counter()
        pr = ppe_model.predict(img, conf=confidence, imgsz=imgsz, verbose=False)[0]
        result.ppe_ms = (time.perf_counter() - t1) * 1000
        for box in pr.boxes:
            result.detections.append(DetectionBox(
                class_name=_canonicalize_class(ppe_model.names[int(box.cls)]),
                class_id=int(box.cls),
                confidence=float(box.conf),
                bbox=[float(v) for v in box.xyxy[0].tolist()],
            ))

        # --- ADDITIVE: per-person padded crops (one batched pass) -----------
        if self.crop_ppe and result.persons:
            n = self._frame_counts.get(session_key or "_", 0) + 1
            self._frame_counts[session_key or "_"] = n
            if (n - 1) % self.crop_every_n == 0:
                result.crop_ms = self._crop_pass(
                    img, ppe_model, confidence, result,
                )
        return result

    def _person_crop(self, img, p: "PersonBox") -> tuple[int, int]:
        """Padded person crop (full useful body region, clamped to bounds).

        Returns the crop origin (ox, oy); a crop box at (cx, cy) maps back to
        frame coords by pure translation (cx+ox, cy+oy) — no scaling, no
        offsets invented.
        """
        H, W = img.shape[:2]
        x1, y1, x2, y2 = p.bbox
        pw, ph = x2 - x1, y2 - y1
        ox = max(0, int(x1 - self.crop_padding * pw))
        oy = max(0, int(y1 - self.crop_padding * ph))
        cx2 = min(W, int(x2 + self.crop_padding * pw))
        cy2 = min(H, int(y2 + self.crop_padding * ph))
        p._crop = img[oy:cy2, ox:cx2]  # type: ignore[attr-defined]
        p._crop_origin = (ox, oy)      # type: ignore[attr-defined]
        return ox, oy

    def _crop_pass(self, img, ppe_model, confidence: float,
                   result: "AnchorResult") -> float:
        """Run Vyra on each padded person crop (ONE batched predict call) and
        merge the back-mapped boxes into result.detections.

        Acceptance rules (learned from the live-frame six-config diagnosis):
          * 'fall-detected' is NEVER taken from a crop — a fall is a FULL-FRAME
            scene property (person on the ground); a crop cannot see context.
          * Alerting (violation) classes are kept only at conf >= 0.50 OR when
            corroborated by a full-frame detection of the same class (IoU>0.3).
            Rationale: the crop pass DID produce a false Fall-Detected 0.439
            and other weak artifacts; 0.50 sits above the 0.35 policy bar so
            crop-only noise can never alert.
          * Compliance classes are kept at the capture threshold — they never
            alert, they only improve per-person status evidence.
          * Duplicate suppression: same class overlapping an existing box with
            IoU > 0.5 keeps only the higher-confidence copy.
        """
        from app.services.safety_rules import PPE_VIOLATION_CLASSES
        from app.services.ppe_policy import resolve_thresholds
        import numpy as np

        th = resolve_thresholds()  # read-only use of the EXISTING policy bars

        # Latency guardrails: cap how many persons get the expensive hi-res
        # pass (largest first = nearest to camera) and how often it runs.
        persons = sorted(
            (p for p in result.persons if (p.bbox[3] - p.bbox[1]) >= 100),
            key=lambda p: (p.bbox[2] - p.bbox[0]) * (p.bbox[3] - p.bbox[1]),
            reverse=True,
        )[: max(1, self.crop_max_persons)]
        if not persons:
            return 0.0
        crops, origins = [], []
        for p in persons:
            ox, oy = self._person_crop(img, p)
            crops.append(p._crop)  # type: ignore[attr-defined]
            origins.append((ox, oy))

        t0 = time.perf_counter()
        batch = ppe_model.predict(
            crops, conf=confidence, imgsz=self.crop_imgsz, verbose=False,
        )
        elapsed = (time.perf_counter() - t0) * 1000

        def _iou(a, b) -> float:
            ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
            ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            ua = ((a[2] - a[0]) * (a[3] - a[1])) + ((b[2] - b[0]) * (b[3] - b[1])) - inter
            return inter / ua if ua > 0 else 0.0

        for pr, (ox, oy) in zip(batch, origins):
            for box in pr.boxes:
                bbox = [
                    float(box.xyxy[0][0]) + ox, float(box.xyxy[0][1]) + oy,
                    float(box.xyxy[0][2]) + ox, float(box.xyxy[0][3]) + oy,
                ]  # crop px -> frame px: pure translation
                cls_name = _canonicalize_class(ppe_model.names[int(box.cls)])
                key = cls_name.lower()
                conf = float(box.conf)
                if key == "fall-detected":
                    continue  # context-dependent: never from a crop
                if key in PPE_VIOLATION_CLASSES:
                    corroborated = any(
                        d.class_name == cls_name and _iou(d.bbox, bbox) > 0.3
                        for d in result.detections
                    )
                    if not corroborated:
                        # Crop-only violation evidence: keep what the policy can
                        # treat honestly — below the violation bar (reported as
                        # UNDETERMINED for review, can never alert) or clearly
                        # strong (>= 0.50). The [bar, 0.50) band is discarded:
                        # strong enough to alert, too weak to trust from a crop.
                        bar = th.violation_for(key)
                        if bar <= conf < 0.50:
                            continue
                # Duplicate suppression: keep the stronger of two copies.
                dup_idx = next(
                    (i for i, d in enumerate(result.detections)
                     if d.class_name == cls_name and _iou(d.bbox, bbox) > 0.5),
                    None,
                )
                if dup_idx is not None:
                    if result.detections[dup_idx].confidence < conf:
                        result.detections[dup_idx] = DetectionBox(
                            class_name=cls_name, class_id=int(box.cls),
                            confidence=conf, bbox=bbox,
                        )
                    continue
                result.detections.append(DetectionBox(
                    class_name=cls_name, class_id=int(box.cls),
                    confidence=conf, bbox=bbox,
                ))
        return elapsed
