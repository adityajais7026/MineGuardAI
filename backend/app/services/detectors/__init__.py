"""Common detector abstraction for MineGuardAI.

Goal (architecture evaluation phase): let different PPE models and detection
strategies be benchmarked and swapped WITHOUT rewriting the application.

Design rules:
  * ADDITIVE ONLY — the production YoloService is preserved verbatim and
    remains the default until benchmarks justify a change. Nothing in the
    existing endpoints/policy/pipeline is modified.
  * Every detector returns the same shape the app already consumes:
    list[DetectionBox] (+ optional tracking IDs and inference timing).
  * Every detector states its class inventory honestly; no fabricated
    capabilities (a model without Boots reports no Boots).
"""
from app.core.config import settings
from app.services.yolo_detection import DetectionBox  # re-export: shared shape


def get_detector_by_name(name: str):
    """Factory for benchmark/evaluation use (production default unchanged).

    name = "vyra"            -> the production YoloService (unchanged path)
    name = "person_anchor"   -> Vyra PPE + yolo11n person anchor (per-person)
    Anything else            -> ValueError (never silently substitute).
    """
    from app.core.config import settings

    if name == "vyra":
        from app.services.yolo_detection import get_yolo_service
        return get_yolo_service()
    if name == "person_anchor":
        from app.services.detectors.person_anchor import PersonAnchorDetector
        ppe_model = (
            settings.PERSON_ANCHOR_PPE_MODEL_PATH or settings.YOLO_MODEL_PATH
        )
        return PersonAnchorDetector(
            ppe_model_path=ppe_model,
            anchor_model_path=settings.PERSON_ANCHOR_MODEL_PATH,
            anchor_conf=settings.PERSON_ANCHOR_CONF,
            crop_ppe=settings.PERSON_ANCHOR_CROP_PPE,
            crop_imgsz=settings.PERSON_ANCHOR_CROP_IMGSZ,
            crop_padding=settings.PERSON_ANCHOR_CROP_PADDING,
            crop_every_n=settings.PERSON_ANCHOR_CROP_EVERY_N,
            crop_max_persons=settings.PERSON_ANCHOR_CROP_MAX_PERSONS,
        )
    raise ValueError(f"Unknown detector strategy: '{name}'")


def resolve_media_detector():
    """Detector that owns image/video/frame inference, chosen by AI_DETECTOR.

    "simulated" or unknown  -> None (endpoints keep their 503 semantics)
    "yolo"                  -> production YoloService (Vyra) — UNCHANGED default
    "yolo_world"            -> EXPERIMENTAL open-vocabulary detector (opt-in)

    Both backends share the YoloService public surface
    (model_info / detect_image_bytes / detect_video_file), so callers need no
    branching and no parallel pipeline exists.
    """
    if settings.AI_DETECTOR == "yolo":
        from app.services.yolo_detection import get_yolo_service
        return get_yolo_service()
    if settings.AI_DETECTOR == "yolo_world":
        from app.services.detectors.yolo_world import get_yolo_world_service
        return get_yolo_world_service()
    return None


_anchor_singleton: object | None = None


def get_anchor_detector():
    """Process-wide singleton for the opt-in anchor strategy (lazy)."""
    global _anchor_singleton
    if _anchor_singleton is None:
        _anchor_singleton = get_detector_by_name("person_anchor")
    return _anchor_singleton


__all__ = ["DetectionBox", "get_detector_by_name", "resolve_media_detector"]
