"""
YOLO inference service (real computer vision — Ultralytics).

Honesty guarantees enforced here:
  * Inference runs ONLY when a model file is actually loaded; a missing model
    raises a clear configuration error instead of fabricating results.
  * Only classes the model genuinely predicts are reported (COCO classes for
    the pretrained yolo11n: person, car, bus, truck, ...).
  * Specialised mining concepts (helmet/vest/PPE) are NOT claimed unless a
    custom model providing those classes is configured.

Video is processed frame-by-frame with configurable sampling; frames are
never accumulated in memory.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# COCO classes relevant as 'vehicles' for rule evaluation.
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle", "train"}
PERSON_CLASSES = {"person"}


class YoloNotConfiguredError(RuntimeError):
    """Raised when YOLO is requested but the model file is missing/misconfigured."""


@dataclass
class DetectionBox:
    class_name: str
    class_id: int
    confidence: float
    bbox: list[float]  # xyxy pixels

    def as_dict(self) -> dict:
        return {
            "class": self.class_name,
            "class_id": self.class_id,
            "confidence": round(self.confidence, 4),
            "bbox": [round(v, 1) for v in self.bbox],
        }


@dataclass
class VideoStats:
    duration_seconds: float = 0.0
    fps: float = 0.0
    total_frames: int = 0
    processed_frames: int = 0
    processing_seconds: float = 0.0


@dataclass
class VideoResult:
    detections: list[DetectionBox] = field(default_factory=list)  # flattened, per processed frame
    frame_records: list[dict] = field(default_factory=list)       # per-frame summaries
    stats: VideoStats = field(default_factory=VideoStats)
    annotated_video_path: str | None = None


class YoloService:
    """Loads the configured model once; runs real image/video inference."""

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path or settings.YOLO_MODEL_PATH
        self._model = None

    # ------------------------------------------------------------------
    def _load_model(self):
        """Lazy-load the YOLO model; explicit errors when unavailable."""
        if self._model is not None:
            return self._model
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise YoloNotConfiguredError(
                "AI_DETECTOR=yolo requires 'ultralytics' (pip install ultralytics). "
                f"Import failed: {exc}"
            ) from exc

        if not os.path.exists(self.model_path):
            if settings.YOLO_AUTO_DOWNLOAD:
                logger.info("YOLO model missing — downloading pretrained model to %s", self.model_path)
                Path(self.model_path).parent.mkdir(parents=True, exist_ok=True)
                # Official Ultralytics pretrained asset download.
                YOLO("yolo11n.pt")  # downloads to CWD; move into place
                downloaded = Path("yolo11n.pt")
                if downloaded.exists():
                    downloaded.replace(self.model_path)
            if not os.path.exists(self.model_path):
                raise YoloNotConfiguredError(
                    f"YOLO model not found at '{self.model_path}'. Set YOLO_MODEL_PATH to a "
                    "valid Ultralytics weights file, or enable YOLO_AUTO_DOWNLOAD=true."
                )
        self._model = YOLO(self.model_path)
        logger.info("YOLO model loaded: %s (classes: %d)", self.model_path, len(self._model.names))
        return self._model

    # ------------------------------------------------------------------
    def model_info(self) -> dict:
        """Detector status for /api/ai/detector — never claims YOLO without weights."""
        try:
            model = self._load_model()
            return {
                "detector": "YOLODetector",
                "source": "yolo",
                "available": True,
                "model_path": self.model_path,
                "model_task": model.task,
                "classes": len(model.names),
            }
        except (YoloNotConfiguredError, ImportError) as exc:
            return {
                "detector": "YOLODetector",
                "source": "yolo",
                "available": False,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    def detect_image_bytes(
        self, data: bytes, *, confidence: float | None = None, imgsz: int | None = None
    ) -> tuple[list[DetectionBox], bytes]:
        """Run real inference on an image. Returns (detections, annotated_png)."""
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
            imgsz=imgsz or settings.YOLO_IMGSZ,
            verbose=False,
        )[0]

        detections: list[DetectionBox] = []
        for box in result.boxes:
            detections.append(DetectionBox(
                class_name=model.names[int(box.cls)],
                class_id=int(box.cls),
                confidence=float(box.conf),
                bbox=[float(v) for v in box.xyxy[0].tolist()],
            ))

        annotated_png = result.plot()  # BGR ndarray with boxes drawn
        ok, encoded = cv2.imencode(".png", annotated_png)
        if not ok:
            raise ValueError("Annotated image encoding failed")
        return detections, encoded.tobytes()

    # ------------------------------------------------------------------
    def detect_video_file(
        self,
        input_path: str,
        *,
        confidence: float | None = None,
        imgsz: int | None = None,
        frame_stride: int | None = None,
        progress_cb=None,
    ) -> VideoResult:
        """
        Stream a video frame-by-frame (no full-file RAM load), annotating the
        sampled frames and writing a real annotated MP4 via OpenCV.
        """
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

        result = VideoResult(stats=VideoStats(duration_seconds=total / fps if fps else 0.0,
                                              fps=fps, total_frames=total))

        tmp_dir = tempfile.mkdtemp(prefix="mineguard_annot_")
        out_path = str(Path(tmp_dir) / "annotated.mp4")
        writer = cv2.VideoWriter(
            out_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps / stride,  # annotated video plays at sampled rate
            (width, height),
        )

        frame_idx = 0
        start = time.time()
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % stride == 0:
                    prediction = model.predict(frame, conf=conf, imgsz=size, verbose=False)[0]
                    frame_detections: list[DetectionBox] = []
                    for box in prediction.boxes:
                        frame_detections.append(DetectionBox(
                            class_name=model.names[int(box.cls)],
                            class_id=int(box.cls),
                            confidence=float(box.conf),
                            bbox=[float(v) for v in box.xyxy[0].tolist()],
                        ))
                    annotated = prediction.plot()
                    writer.write(annotated)

                    ts = frame_idx / fps if fps else 0.0
                    result.detections.extend(frame_detections)
                    result.frame_records.append({
                        "frame_number": frame_idx,
                        "timestamp_seconds": round(ts, 2),
                        "detections": [d.as_dict() for d in frame_detections],
                    })
                    if progress_cb:
                        progress_cb(frame_idx, total)
                frame_idx += 1
        finally:
            cap.release()
            writer.release()
            result.stats.processed_frames = frame_idx // stride + (1 if frame_idx % stride else 0)
            result.stats.processing_seconds = round(time.time() - start, 2)

        result.annotated_video_path = out_path
        return result


# Module-level singleton so the model loads once per process.
_yolo_service: YoloService | None = None


def get_yolo_service() -> YoloService:
    global _yolo_service
    if _yolo_service is None:
        _yolo_service = YoloService()
    return _yolo_service
