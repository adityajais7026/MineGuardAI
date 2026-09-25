"""AI package: detector interface, simulated detector and optional YOLO adapter."""
from app.ai.detector import (
    BaseDetector,
    Detection,
    SimulatedDetector,
    YOLODetector,
    get_detector,
)

__all__ = ["BaseDetector", "Detection", "SimulatedDetector", "YOLODetector", "get_detector"]
