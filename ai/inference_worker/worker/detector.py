"""Vyra PPE inference — the real model, loaded once, no fallbacks.

Mirrors the backend's `YoloService.detect_image_bytes` (same ultralytics
predict + `result.plot()` annotated PNG) but lives in its own process and
touches nothing from `backend/app` — no config, no DB, no business logic.
Only real model output is ever reported; load failures surface as HTTP 503.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class VyraNotLoadedError(RuntimeError):
    """Vyra could not be loaded — must lead to HTTP 503, never fake output."""


class VyraDetector:
    """Loads the existing Vyra weights once; runs real image inference."""

    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self.model = None
        self.classes: dict[int, str] | None = None
        self.load_error: str | None = None
        self.load_seconds: float = 0.0

    def load(self) -> None:
        """Load Vyra exactly once. Failures are stored and surfaced as 503."""
        try:
            from ultralytics import YOLO
        except Exception as exc:  # ImportError and import-time crashes
            self.load_error = f"ultralytics unavailable: {exc}"
            logger.error("Vyra load failed: %s", self.load_error)
            return

        load_start = time.perf_counter()
        try:
            if not Path(self.model_path).exists():
                raise FileNotFoundError(
                    f"Vyra weights not found at {self.model_path!r}"
                )
            logger.info("Loading Vyra from %s...", self.model_path)
            self.model = YOLO(self.model_path)
            self.classes = dict(self.model.names)
        except Exception as exc:
            self.model = None
            self.classes = None
            self.load_error = f"{type(exc).__name__}: {exc}"
            logger.error("Vyra load failed: %s", self.load_error)
            return

        self.load_seconds = round(time.perf_counter() - load_start, 3)
        logger.info(
            "Vyra loaded in %.2fs (%d classes)", self.load_seconds, len(self.classes)
        )

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def detect(
        self,
        data: bytes,
        *,
        confidence: float,
        imgsz: int,
        annotate: bool = True,
    ) -> dict:
        """Real inference on already-magic-checked JPEG/PNG bytes."""
        if not self.loaded:
            raise VyraNotLoadedError(self.load_error or "Vyra model is not loaded")

        import cv2
        import numpy as np

        nparr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Image decodes to no pixels (malformed image)")

        t0 = time.perf_counter()
        result = self.model.predict(
            img, conf=confidence, imgsz=imgsz, device="cpu", verbose=False
        )[0]
        inference_ms = (time.perf_counter() - t0) * 1000

        detections: list[dict] = []
        for box in result.boxes:
            detections.append(
                {
                    "class": self.classes[int(box.cls)],
                    "class_id": int(box.cls),
                    "confidence": round(float(box.conf), 4),
                    "bbox": [round(float(v), 1) for v in box.xyxy[0].tolist()],
                }
            )

        annotated_png: bytes | None = None
        if annotate:
            annotated_bgr = result.plot()  # ndarray with real model boxes drawn
            ok, encoded = cv2.imencode(".png", annotated_bgr)
            if not ok:
                raise ValueError("Annotated image encoding failed")
            annotated_png = encoded.tobytes()

        return {
            "detections": detections,
            "detection_count": len(detections),
            "classes_detected": sorted({d["class"] for d in detections}),
            "inference_ms": round(inference_ms, 1),
            "imgsz": imgsz,
            "conf": confidence,
            "annotated_png": annotated_png,
        }
