"""Experimental YOLO-World open-vocabulary PPE detector (OPT-IN).

Status: EXPERIMENTAL — not the production detector. Vyra (YoloService) remains
the production/default detector; this module adds a second, opt-in backend.

Model: custom_yolov8s_mining.pt — yolov8s-world.pt configured with six text
classes via model.set_classes([...]) and saved (NOT fine-tuned on any
MineGuardAI dataset):

    0 person, 1 hard hat, 2 gloves, 3 safety glasses,
    4 safety vest, 5 safety shoes

Colab observations (user-reported, 2026-10): person / hard hat / gloves
detected reliably; safety glasses / safety vest / safety shoes inconsistent.
Default inference size stays 640 (1280 was ~3.5x slower and is never the
default here).

Design rules (mirrors the detectors/ package contract):
  * ADDITIVE ONLY — production YoloService and every Vyra default are
    unchanged; this detector is constructed only when
    AI_DETECTOR=yolo_world (explicit operator opt-in).
  * YoloService-compatible surface (model_info / detect_image_bytes /
    detect_video_file) for the image/video endpoints, plus a
    PersonAnchorDetector-compatible detect() (persons + ByteTrack + PPE in one
    result) for the live endpoint through the shared live_adapter flow.
  * Class adapter: YOLO-World's text classes are presented in the project's
    canonical vocabulary via the EXISTING alias mechanism
    (person_anchor.CANONICAL_CLASS_ALIASES), so ppe_policy / safety_rules /
    _person_report behave identically. Raw class_id values are preserved.
  * ABSENCE HONESTY: this model has NO NO-* classes and none are invented.
    Missing PPE is only ever reflected as missing evidence -> the existing
    policy reports UNDETERMINED for such persons. "PPE COMPLIANT" is never
    claimed from a missed detection.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.yolo_detection import DetectionBox

logger = logging.getLogger(__name__)

# The EXACT six classes the experimental model was configured with.
EXPECTED_YOLO_WORLD_CLASSES: dict[int, str] = {
    0: "person",
    1: "hard hat",
    2: "gloves",
    3: "safety glasses",
    4: "safety vest",
    5: "safety shoes",
}


class YoloWorldNotConfiguredError(RuntimeError):
    """Raised when YOLO-World is requested but missing/misconfigured."""


def _canonicalize(raw_name: str) -> str:
    """YOLO-World text class -> project-canonical class name.

    Reuses the production alias table (person_anchor.CANONICAL_CLASS_ALIASES)
    extended with YOLO-World's space-separated variants. Unknown names pass
    through unchanged (honest reporting of unexpected classes). Vyra class
    names contain none of these keys, so production is untouched.
    """
    from app.services.detectors.person_anchor import CANONICAL_CLASS_ALIASES

    aliases = {
        **CANONICAL_CLASS_ALIASES,
        "hard hat": "Hardhat",
        "safety glasses": "Goggles",
        "safety vest": "Safety Vest",
        "safety shoes": "Safety Shoes",
    }
    return aliases.get(raw_name.strip().lower(), raw_name)


@dataclass
class WorldResult:
    """Combined result of one World inference pass (anchor-style contract)."""
    detections: list[DetectionBox] = field(default_factory=list)  # PPE boxes
    persons: list["object"] = field(default_factory=list)  # PersonBox-shape
    inference_ms: float = 0.0
    crop_ms: float = 0.0  # always 0 (no crop pass in this backend)

    @property
    def ppe_ms(self) -> float:
        return self.inference_ms

    @property
    def total_ms(self) -> float:
        return self.inference_ms

    def as_dict(self) -> dict:
        """Dict for person_anchor-compatible consumers (live adapter)."""
        return {
            "detections": [d.as_dict() for d in self.detections],
            "persons": [p.as_dict() for p in self.persons],
            "inference_ms": round(self.inference_ms, 1),
        }


@dataclass
class WorldVideoStats:
    duration_seconds: float = 0.0
    fps: float = 0.0
    total_frames: int = 0
    processed_frames: int = 0
    processing_seconds: float = 0.0


@dataclass
class WorldVideoResult:
    detections: list[DetectionBox] = field(default_factory=list)
    frame_records: list[dict] = field(default_factory=list)
    stats: WorldVideoStats = field(default_factory=WorldVideoStats)
    annotated_video_path: str | None = None


def _person_iou(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    ua = ((a[2] - a[0]) * (a[3] - a[1])) + ((b[2] - b[0]) * (b[3] - b[1])) - inter
    return inter / ua if ua > 0 else 0.0


class YoloWorldDetector:
    """Open-vocabulary YOLO-World detector (YoloService + anchor surfaces).

    One instance holds one model; per-session ByteTrack trackers are kept
    here (same pattern as PersonAnchorDetector) so /frame sessions get
    persistent person IDs. PPE association itself stays in ppe_policy.
    """

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path or settings.AI_DETECTOR_YOLO_WORLD_MODEL_PATH
        self._model = None
        self._trackers: dict[str, object] = {}
        self._max_trackers = 16

    # ------------------------------------------------------------------ #
    def _load_model(self):
        """Lazy-load; verify the six expected classes EXACTLY (no remapping)."""
        if self._model is not None:
            return self._model
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise YoloWorldNotConfiguredError(
                "AI_DETECTOR=yolo_world requires 'ultralytics' "
                f"(pip install ultralytics). Import failed: {exc}"
            ) from exc
        if not os.path.exists(self.model_path):
            raise YoloWorldNotConfiguredError(
                f"YOLO-World model not found at '{self.model_path}'. Place "
                "custom_yolov8s_mining.pt there (ai/YOLO_WORLD.md has setup "
                "steps) or keep AI_DETECTOR=simulated / 'yolo'."
            )
        model = YOLO(self.model_path)
        names = {int(k): str(v) for k, v in model.names.items()}
        expected = {int(k): v for k, v in EXPECTED_YOLO_WORLD_CLASSES.items()}
        if names != expected:
            raise YoloWorldNotConfiguredError(
                "YOLO-World model class check failed. Expected exactly "
                f"{expected}, got {names}. Re-export the model with "
                "model.set_classes([...]) in the documented order — classes "
                "are never silently remapped."
            )
        self._model = model
        logger.info(
            "YOLO-World model loaded: %s (classes: %d, EXPERIMENTAL)",
            self.model_path, len(names),
        )
        return self._model

    def _tracker_for(self, session_key: str):
        """One ByteTrack instance per live session (IDs persist within it)."""
        tr = self._trackers.get(session_key)
        if tr is None:
            from types import SimpleNamespace

            from ultralytics.trackers.byte_tracker import BYTETracker

            args = SimpleNamespace(
                track_high_thresh=0.25, track_low_thresh=0.1,
                new_track_thresh=0.25, track_buffer=30, match_thresh=0.8,
                fuse_score=True,
            )
            tr = BYTETracker(args)
            if len(self._trackers) >= self._max_trackers:
                self._trackers.pop(next(iter(self._trackers)))
            self._trackers[session_key] = tr
        return tr

    # ------------------------------------------------------------------ #
    def model_info(self) -> dict:
        """Detector status for /api/ai/detector — honest availability."""
        try:
            model = self._load_model()
            return {
                "detector": "YOLOWorldDetector",
                "source": "yolo_world",
                "available": True,
                "experimental": True,
                "model_path": self.model_path,
                "model_task": model.task,
                "classes": len(model.names),
                "class_names": [model.names[i] for i in sorted(model.names)],
            }
        except (YoloWorldNotConfiguredError, ImportError) as exc:
            return {
                "detector": "YOLOWorldDetector",
                "source": "yolo_world",
                "available": False,
                "experimental": True,
                "error": str(exc),
            }

    # ------------------------------------------------------------------ #
    def _boxes(self, result) -> list[DetectionBox]:
        names = result.names  # real ultralytics Results always carry .names
        boxes: list[DetectionBox] = []
        for box in result.boxes:
            cls_id = int(box.cls)
            boxes.append(DetectionBox(
                class_name=_canonicalize(names[cls_id]),
                class_id=cls_id,  # raw model id preserved
                confidence=float(box.conf),
                bbox=[float(v) for v in box.xyxy[0].tolist()],
            ))
        return boxes

    def detect(self, img, *, confidence: float, imgsz: int = 640,
               session_key: str | None = None) -> WorldResult:
        """One live frame: tracked persons + PPE boxes from the SAME pass.

        Mirrors PersonAnchorDetector.detect()'s contract so the shared live
        flow works unchanged; one predict() call supplies both person boxes
        (defs/ids from ByteTrack) and PPE candidate boxes.
        """
        from app.services.detectors.person_anchor import PersonBox

        model = self._load_model()
        result = WorldResult()
        t0 = time.perf_counter()
        # NOTE: plain predict() — never model.track(). Per-session IDs come
        # from OUR BYTETracker instances (same pattern as PersonAnchorDetector),
        # so the ultralytics predictor never enters track mode here.
        pred = model.predict(img, conf=confidence, imgsz=imgsz,
                             verbose=False)[0]

        raw_persons: list[tuple[float, list[float]]] = [
            (float(box.conf), [float(v) for v in box.xyxy[0].tolist()])
            for box in pred.boxes if int(box.cls) == 0
        ]
        tracker = self._tracker_for(session_key) if session_key else None
        if tracker is not None and raw_persons:
            # cls works for real torch tensors and test fakes alike.
            cls_np = np.asarray(pred.boxes.cls).reshape(-1).astype(int)
            tracks = tracker.update(pred.boxes[cls_np == 0], img)
            for t in tracks:  # row = [x1, y1, x2, y2, track_id, score, cls, idx]
                if int(t[6]) != 0:  # COCO person only (World class 0 == person)
                    continue
                result.persons.append(PersonBox(
                    class_name="person", class_id=0, confidence=float(t[5]),
                    bbox=[float(t[0]), float(t[1]), float(t[2]), float(t[3])],
                    track_id=int(t[4]),
                ))
            # Untracked leftovers only when ByteTrack produced nothing for
            # that region (keeps multiple people present even mid-register).
            for conf, bbox in raw_persons:
                if not any(_person_iou(bbox, p.bbox) > 0.5 for p in result.persons):
                    result.persons.append(PersonBox(
                        class_name="person", class_id=0, confidence=conf,
                        bbox=bbox, track_id=None,
                    ))
        else:
            for conf, bbox in raw_persons:
                result.persons.append(PersonBox(
                    class_name="person", class_id=0, confidence=conf,
                    bbox=bbox, track_id=None,
                ))

        for d in self._boxes(pred):
            if d.class_name.lower() == "person":
                continue  # person boxes only from the tracked path above
            result.detections.append(d)

        result.inference_ms = (time.perf_counter() - t0) * 1000
        return result

    # ------------------------------------------------------------------ #
    def detect_image_bytes(
        self, data: bytes, *, confidence: float | None = None, imgsz: int | None = None,
    ) -> tuple[list[DetectionBox], bytes]:
        """Real inference on one image. Returns (detections, annotated_png)."""
        model = self._load_model()
        import cv2
        import numpy as np

        nparr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Image could not be decoded")

        result = model.predict(
            img,
            conf=confidence if confidence is not None else settings.YOLO_CONFIDENCE,
            imgsz=imgsz or settings.YOLO_IMGSZ,  # default 640 — never 1280
            verbose=False,
        )[0]

        detections = self._boxes(result)
        annotated_png = result.plot()
        ok, encoded = cv2.imencode(".png", annotated_png)
        if not ok:
            raise ValueError("Annotated image encoding failed")
        return detections, encoded.tobytes()

    # ------------------------------------------------------------------ #
    def detect_video_file(
        self, input_path: str, *, confidence: float | None = None,
        imgsz: int | None = None, frame_stride: int | None = None, progress_cb=None,
    ) -> WorldVideoResult:
        """Stream a video frame-by-frame (sampled), annotating as it goes."""
        model = self._load_model()
        import cv2

        conf = confidence if confidence is not None else settings.YOLO_CONFIDENCE
        size = imgsz or settings.YOLO_IMGSZ
        stride = max(1, frame_stride or settings.YOLO_FRAME_STRIDE)

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError("Video could not be opened")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        out = WorldVideoResult(stats=WorldVideoStats(
            duration_seconds=total / fps if fps else 0.0, fps=fps, total_frames=total,
        ))
        tmp_dir = tempfile.mkdtemp(prefix="mineguard_world_annot_")
        out_path = str(Path(tmp_dir) / "annotated.mp4")
        writer = cv2.VideoWriter(
            out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps / stride, (width, height),
        )

        frame_idx = 0
        start = time.time()
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % stride == 0:
                    pred = model.predict(frame, conf=conf, imgsz=size, verbose=False)[0]
                    frame_boxes = self._boxes(pred)
                    writer.write(pred.plot())
                    out.detections.extend(frame_boxes)
                    out.frame_records.append({
                        "frame_number": frame_idx,
                        "timestamp_seconds": round(frame_idx / fps, 2) if fps else 0.0,
                        "detections": [d.as_dict() for d in frame_boxes],
                    })
                    if progress_cb:
                        progress_cb(frame_idx, total)
                frame_idx += 1
        finally:
            cap.release()
            writer.release()
            out.stats.processed_frames = frame_idx // stride + (1 if frame_idx % stride else 0)
            out.stats.processing_seconds = round(time.time() - start, 2)

        out.annotated_video_path = out_path
        return out


# Module-level singleton (model loads once per process).
_yolo_world_service: YoloWorldDetector | None = None


def get_yolo_world_service() -> YoloWorldDetector:
    global _yolo_world_service
    if _yolo_world_service is None:
        _yolo_world_service = YoloWorldDetector()
    return _yolo_world_service
