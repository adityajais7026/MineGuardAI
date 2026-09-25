"""
AI / computer-vision detector abstraction (Phase 10).

Architecture:
    CameraFeed/ingest -> Detector.detect(frame) -> Detection -> pipeline -> DB

Two implementations:
  * SimulatedDetector — generates clearly-labelled simulated events.
    Used by default; requires no hardware, weights or network.
  * YOLODetector — optional real inference. It is ONLY constructed when
    AI_DETECTOR=yolo AND ultralytics + OpenCV AND the model file are present;
    otherwise the factory logs a warning and falls back to the simulated
    detector. Detections from YOLO are labelled detection_source="yolo";
    simulated ones "simulated". No code path mislabels simulated output as AI.

get_detector() is the single entry point used by services/pipeline.py.
"""
from __future__ import annotations

import itertools
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)

# Canonical event vocabulary (matches camera_events.event_type CHECK values
# used by schemas + seed data).
EVENT_TYPES = [
    "person_without_helmet",
    "person_without_vest",
    "restricted_zone_entry",
    "vehicle_in_restricted_area",
    "fire_smoke",
    "unsafe_crowding",
]
SEVERITY_BY_EVENT = {
    "person_without_helmet": "high",
    "person_without_vest": "medium",
    "restricted_zone_entry": "critical",
    "vehicle_in_restricted_area": "high",
    "fire_smoke": "critical",
    "unsafe_crowding": "medium",
}
DETECTED_OBJECT = {
    "person_without_helmet": "person",
    "person_without_vest": "person",
    "restricted_zone_entry": "person",
    "vehicle_in_restricted_area": "truck",
    "fire_smoke": "smoke",
    "unsafe_crowding": "group",
}


@dataclass
class Detection:
    """Normalized detector output consumed by the event pipeline."""

    event_type: str
    confidence: float
    detected_object: str | None
    severity: str
    detection_source: str  # "simulated" | "yolo" | "opencv"
    model_version: str | None = None
    image_ref: str | None = None


class BaseDetector(ABC):
    """Interface every detector implementation fulfils."""

    source: str = "simulated"

    @abstractmethod
    def detect(self, camera_id: str, frame: bytes | None = None) -> Detection:
        """Analyse one frame (or a simulated tick when frame is None)."""

    def health(self) -> dict:
        return {"detector": self.__class__.__name__, "source": self.source, "available": True}


_tick_counter = itertools.count()  # extra entropy: guarantees unique seeds
# even for many detects within the same nanosecond-timestamp window


class SimulatedDetector(BaseDetector):
    """
    Random event generator for development/demo.

    HONESTY: output is NOT computer vision. Events carry
    detection_source="simulated" everywhere they are stored or shown.
    """

    source = "simulated"
    model_version = "simulated-v1"

    def detect(self, camera_id: str, frame: bytes | None = None) -> Detection:
        # ns-resolution clock + counter: repeated calls for the same camera
        # must not collapse to identical events (bug fixed in Phase 10).
        seed = f"{camera_id}:{time.time_ns()}:{next(_tick_counter)}"
        rng = random.Random(seed)
        event_type = rng.choice(EVENT_TYPES)
        return Detection(
            event_type=event_type,
            confidence=round(rng.uniform(0.62, 0.97), 2),
            detected_object=DETECTED_OBJECT[event_type],
            severity=SEVERITY_BY_EVENT[event_type],
            detection_source=self.source,
            model_version=self.model_version,
        )


class YOLODetector(BaseDetector):
    """
    Real YOLO inference (optional). Loaded lazily; safe when absent.

    Requirements to enable:
      pip install ultralytics opencv-python
      a trained weights file at settings.YOLO_MODEL_PATH (default
      ai/yolo/models/best.pt) with classes matching EVENT_TYPES above.
    Then set AI_DETECTOR=yolo. Detections are labelled detection_source="yolo".
    """

    source = "yolo"

    def __init__(self, model_path: str):
        try:
            from ultralytics import YOLO  # heavy import: only when enabled
        except ImportError as exc:
            raise RuntimeError(
                "AI_DETECTOR=yolo requires the 'ultralytics' package "
                "(pip install ultralytics opencv-python)"
            ) from exc
        if not os.path.exists(model_path):
            raise RuntimeError(
                f"YOLO weights not found at '{model_path}'. Place a trained "
                "model there or keep AI_DETECTOR=simulated."
            )
        self.model_path = model_path
        self.model = YOLO(model_path)
        self.model_version = f"yolo:{os.path.basename(model_path)}"
        logger.info("YOLODetector loaded model %s", model_path)

    def detect(self, camera_id: str, frame: bytes | None = None) -> Detection:
        import cv2
        import numpy as np

        if frame is None:
            raise ValueError("YOLODetector requires an image frame")
        nparr = np.frombuffer(frame, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Frame could not be decoded")

        results = self.model(img, verbose=False)[0]
        names = results.names
        # Map model classes onto the canonical event vocabulary by name.
        best: Detection | None = None
        for box in results.boxes:
            cls_name = names[int(box.cls)]
            event_type = cls_name.lower().replace(" ", "_")
            if event_type not in EVENT_TYPES:
                event_type = "other"
            conf = float(box.conf)
            if best is None or conf > best.confidence:
                best = Detection(
                    event_type=event_type,
                    confidence=round(conf, 2),
                    detected_object=cls_name,
                    severity=SEVERITY_BY_EVENT.get(event_type, "medium"),
                    detection_source=self.source,
                    model_version=self.model_version,
                )
        if best is None:
            raise ValueError("No detections in frame")
        return best


def get_detector() -> BaseDetector:
    """Factory: honours settings.AI_DETECTOR with safe simulated fallback."""
    if settings.AI_DETECTOR == "yolo":
        try:
            return YOLODetector(settings.YOLO_MODEL_PATH)
        except (RuntimeError, ImportError) as exc:
            logger.warning("YOLO unavailable (%s) — falling back to simulated detector.", exc)
    return SimulatedDetector()
