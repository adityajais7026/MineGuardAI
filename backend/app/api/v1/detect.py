"""
YOLO media-detection endpoints (enhancement phase + PPE model support).

Flow: authenticated upload -> validation (magic bytes, size, type) ->
real YOLO inference (generic COCO model OR fine-tuned PPE model such as
SafetyVision YOLOv8s — whichever YOLO_MODEL_PATH points to) -> annotated
output -> storage -> camera_events -> safety-rule alerts -> JSON results.

PPE behaviour: violation events/alerts come ONLY from the model's own
violation-class detections (e.g. NO-Hardhat). Nothing is renamed, inferred
from missing detections, or fabricated.

Every response explicitly states the detector used. No fake detections.
"""
import shutil
import tempfile
import time
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import CameraEvent, Mine, RestrictedZone, User
from app.database.session import get_db
from app.services.yolo_detection import PERSON_CLASSES, VEHICLE_CLASSES
from app.services.camera_pipeline import record_yolo_events
from app.services.ppe_policy import associate_with_persons, resolve_thresholds
from app.services.safety_rules import evaluate_safety_rules
from app.services.storage import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_VIDEO_TYPES,
    StorageBackend,
    build_media_path,
    get_storage,
    sniff_mime,
)
from app.services.yolo_detection import (
    YoloNotConfiguredError,
    get_yolo_service,
)

router = APIRouter(
    prefix="/ai/detect",
    tags=["AI Detection (YOLO)"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
WriteUser = Annotated[User, Depends(write_access("ai_simulation"))]

MAX_IMAGE_BYTES = settings.MAX_IMAGE_UPLOAD_MB * 1024 * 1024
MAX_VIDEO_BYTES = settings.MAX_VIDEO_UPLOAD_MB * 1024 * 1024


class DetectionItem(BaseModel):
    class_name: str
    class_id: int
    confidence: float
    bbox: list[float]
    frame_number: int | None = None
    timestamp_seconds: float | None = None
    camera_event_id: str | None = None


def _person_report(detections, findings, *, person_boxes=None, person_ids=None) -> list[dict] | None:
    """Person-centric PPE summary: associate the model's own PPE boxes with
    person boxes and report honest per-person status (never fabricated).
    UNDETERMINED when the model gives no confident PPE evidence for a person.

    `person_boxes`/`person_ids` (optional) let the live anchor strategy supply
    COCO-person boxes + ByteTrack IDs; when omitted the behaviour is exactly
    the pre-anchor one (person boxes derived from the detections themselves).
    """
    from app.services.safety_rules import PPE_HANDLED_CLASSES

    th = resolve_thresholds()
    ppe_boxes = [
        (d.class_name, d.confidence, d.bbox)
        for d in detections
        if d.class_name.lower() in PPE_HANDLED_CLASSES
    ]
    if person_boxes is None:
        person_boxes = [
            (d.confidence, d.bbox) for d in detections if d.class_name.lower() in PERSON_CLASSES
        ]
    if not person_boxes:
        return None
    assoc = associate_with_persons(ppe_boxes, person_boxes)
    violation_by_class: dict[str, str] = {
        f.detected_class.lower(): f.status for f in findings if f.detected_class
    }
    report = []
    _HELMET_FAMILY = {"hardhat"}
    _VEST_FAMILY = {"safety vest"}
    for idx, (pconf, pbox) in enumerate(person_boxes):
        tid = person_ids[idx] if person_ids and idx < len(person_ids) else None
        entries = assoc.get(idx, [])
        statuses = [violation_by_class.get(e["class"].lower(), "compliance") for e in entries]
        if "violation" in statuses:
            status = "VIOLATION"
        elif "undetermined" in statuses:
            status = "UNDETERMINED"
        elif entries:
            # VERDICT HONESTY: single-class evidence (e.g. only a vest, when
            # ordinary clothing has a measured false-vest mode) is NOT full
            # compliance — PARTIAL, never PROTECTED.
            families = {
                "helmet" if e["class"].lower() in _HELMET_FAMILY
                else "vest" if e["class"].lower() in _VEST_FAMILY
                else "other"
                for e in entries
            }
            status = ("PROTECTED" if {"helmet", "vest"} <= families else "PARTIAL")
        else:
            status = "UNDETERMINED"
        report.append({
            "person_index": idx,
            "track_id": tid,
            "person_confidence": round(pconf, 3),
            "person_bbox": [round(v, 1) for v in pbox],
            "ppe": [
                {
                    "class": e["class"],
                    "confidence": round(e["confidence"], 3),
                    "bbox": [round(v, 1) for v in e["bbox"]],
                    "decision": violation_by_class.get(e["class"].lower(), "compliance"),
                }
                for e in entries
            ],
            "ppe_status": status,
        })
    return report


def _validate_mine_zone(db: Session, mine_id: str, zone_id: str | None):
    if db.get(Mine, mine_id) is None:
        raise HTTPException(status_code=400, detail=f"Unknown mine_id '{mine_id}'")
    zone = None
    if zone_id is not None:
        zone = db.get(RestrictedZone, zone_id)
        if zone is None or zone.mine_id != mine_id:
            raise HTTPException(status_code=400, detail="zone_id does not belong to the given mine")
    return zone


def _read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Read with size cap enforcement before anything else touches the bytes."""
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    return data


def _check_declared_type(upload: UploadFile, allowed: dict) -> str:
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Content-Type '{declared or 'unknown'}' not allowed. Permitted: {sorted(allowed)}",
        )
    return declared


def _check_actual_type(data: bytes, allowed: dict) -> str:
    actual = sniff_mime(data)
    if actual is None or actual not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File content does not match an allowed media type (magic-byte check failed)",
        )
    return actual


def _detect_for_media(kind: str):
    """Resolve the configured detector; YOLO required for these endpoints.

    Works with any Ultralytics-detect weights at YOLO_MODEL_PATH (generic
    COCO or fine-tuned PPE); classes drive the downstream rules honestly.
    """
    from app.ai.detector import get_detector

    if settings.AI_DETECTOR != "yolo":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "YOLO detection is disabled (AI_DETECTOR != 'yolo'). Set AI_DETECTOR=yolo "
                "with a valid YOLO_MODEL_PATH. Simulated events remain available via "
                "/api/ai/simulate-event."
            ),
        )
    try:
        get_yolo_service()._load_model()
    except YoloNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post("/image")
def detect_image(
    db: DbSession,
    user: WriteUser,
    upload: UploadFile,
    mine_id: str = Query(...),
    zone_id: str | None = Query(default=None),
    confidence: float = Query(default=None, ge=0.05, le=1.0),
) -> dict[str, Any]:
    """Upload an image, run real YOLO inference, store media, create events/alerts."""
    _detect_for_media("image")
    zone = _validate_mine_zone(db, mine_id, zone_id)
    declared = _check_declared_type(upload, ALLOWED_IMAGE_TYPES)
    data = _read_upload(upload, MAX_IMAGE_BYTES)
    actual = _check_actual_type(data, ALLOWED_IMAGE_TYPES)

    storage: StorageBackend = get_storage()
    ext = ALLOWED_IMAGE_TYPES[actual]
    original_path = build_media_path(mine_id, "images", ext)

    # Two-stage PPE policy: infer at the low CAPTURE threshold so genuine
    # sub-violation-bar detections are not lost, then gate violations per-class
    # in the rules engine. When unset, capture == YOLO_CONFIDENCE (unchanged).
    th = resolve_thresholds()
    effective_conf = confidence if confidence is not None else th.capture
    try:
        detections, annotated_png = get_yolo_service().detect_image_bytes(data, confidence=effective_conf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    original_obj = storage.upload_bytes(data, path=original_path, mime_type=actual)
    annotated_obj = storage.upload_bytes(
        annotated_png, path=build_media_path(mine_id, "results", "png"), mime_type="image/png"
    )

    # Safety-rule evaluation over the REAL detections (zone context from upload).
    findings = evaluate_safety_rules(
        detections, zone_name=zone.name if zone else None, is_restricted_zone=zone is not None
    )
    findings_by_event_type: dict[str, Any] = {}
    for f in findings:
        findings_by_event_type[f.event_type] = f

    model_version = f"yolo:{Path(settings.YOLO_MODEL_PATH).name}"
    events_out: list[dict[str, Any]] = []
    alerts_out: list[dict[str, Any]] = []

    camera_id = zone.camera_id if zone and zone.camera_id else f"CAM-{mine_id[:6].upper()}-UP"

    # One representative event per distinct detected class (bounded, meaningful),
    # plus an event per safety-rule finding. PPE classes are handled from the
    # model's own detections; unmapped classes keep the object/zone logic.
    best_by_class: dict[str, Any] = {}
    for d in detections:
        if d.class_name not in best_by_class or d.confidence > best_by_class[d.class_name].confidence:
            best_by_class[d.class_name] = d

    def _ppe_finding_for(cls: str, conf: float):
        cls_lower = cls.lower()
        for f in findings:
            if (
                f.detected_class is not None
                and f.detected_class.lower() == cls_lower
                and f.confidence is not None
                and abs(f.confidence - conf) < 1e-6
            ):
                return f
        return None

    for class_name, d in best_by_class.items():
        ppe = _ppe_finding_for(class_name, d.confidence)
        if ppe is not None:
            # PPE-worn findings record compliance WITHOUT raising an alert;
            # violation findings raise one (deduped downstream).
            event, alert = record_yolo_events(
                db,
                mine_id=mine_id, camera_id=camera_id,
                zone_id=zone.id if zone else None, zone_name=zone.name if zone else None,
                event_type=ppe.event_type, severity=ppe.severity,
                detected_object=class_name,
                confidence=d.confidence,
                model_version=model_version,
                image_ref=annotated_obj.path,
                source_media_ref=original_obj.path,
                detail=(ppe.evidence + (f" in restricted zone '{zone.name}'" if zone else "")),
                raise_alert=ppe.alert,
            )
        else:
            is_person = class_name.lower() in PERSON_CLASSES
            is_vehicle = class_name.lower() in VEHICLE_CLASSES
            raise_alert = (is_person or is_vehicle) and zone is not None
            if is_person and zone is not None:
                event_type = "restricted_zone_entry"
            elif is_vehicle and zone is not None:
                event_type = "vehicle_in_restricted_area"
            else:
                event_type = "other"
            # 'other' events record the raw object detection; no alert is raised.
            finding = findings_by_event_type.get(event_type) if event_type != "other" else None
            event, alert = record_yolo_events(
                db,
                mine_id=mine_id, camera_id=camera_id,
                zone_id=zone.id if zone else None, zone_name=zone.name if zone else None,
                event_type=event_type,
                severity=(finding.severity if finding else ("high" if raise_alert else "medium")),
                detected_object=class_name,
                confidence=d.confidence,
                model_version=model_version,
                image_ref=annotated_obj.path,
                source_media_ref=original_obj.path,
                detail=f"class '{class_name}' conf {d.confidence:.2f} bbox {d.bbox}",
            )
        events_out.append({"camera_event_id": event.id, "class": class_name,
                           "confidence": round(d.confidence, 3), "event_type": event.event_type,
                           "ppe_status": ppe.status if ppe else None})
        if alert:
            alerts_out.append({"id": alert.id, "title": alert.title,
                               "severity": alert.severity, "source": alert.source})

    for f in findings:
        if f.event_type in {"unsafe_crowding"}:
            event, alert = record_yolo_events(
                db,
                mine_id=mine_id,
                camera_id=(zone.camera_id if zone and zone.camera_id else f"CAM-{mine_id[:6].upper()}-UP"),
                zone_id=zone.id if zone else None,
                zone_name=zone.name if zone else None,
                event_type=f.event_type,
                severity=f.severity,
                detected_object="group",
                confidence=max((d.confidence for d in detections if d.class_name == "person"), default=0.0),
                model_version=model_version,
                image_ref=annotated_obj.path,
                source_media_ref=original_obj.path,
                detail=f.evidence,
            )
            events_out.append({"camera_event_id": event.id, "class": "group",
                               "confidence": event.confidence, "event_type": event.event_type})
            if alert:
                alerts_out.append({"id": alert.id, "title": alert.title,
                                   "severity": alert.severity, "source": alert.source})

    original_url = storage.create_access_url(original_obj.path) if storage else None
    annotated_url = storage.create_access_url(annotated_obj.path) if storage else None

    return {
        "source": "uploaded_image",
        "detector": "yolo",
        "model": model_version,
        "mine_id": mine_id,
        "zone": {"id": zone.id, "name": zone.name} if zone else None,
        "detections": [d.as_dict() for d in detections],
        "detection_count": len(detections),
        "classes_detected": sorted({d.class_name for d in detections}),
        "safety_findings": [
            {"rule": f.rule, "event_type": f.event_type, "severity": f.severity,
             "evidence": f.evidence, "status": f.status,
             "confidence": round(f.confidence, 3) if f.confidence is not None else None}
            for f in findings
        ],
        "annotated_image_url": annotated_url,
        "original_image_url": original_url,
        "camera_event_ids": [e["camera_event_id"] for e in events_out],
        "events": events_out,
        "alerts": alerts_out,
        "storage_provider": getattr(original_obj, "provider", "unknown"),
        "uploaded_by": user.email,
        "person_ppe_report": _person_report(detections, findings),
    }


@router.post("/video")
def detect_video(
    db: DbSession,
    user: WriteUser,
    upload: UploadFile,
    mine_id: str = Query(...),
    zone_id: str | None = Query(default=None),
    confidence: float = Query(default=None, ge=0.05, le=1.0),
    frame_stride: int = Query(default=None, ge=1, le=100),
) -> dict[str, Any]:
    """Upload a video, run real frame-sampled YOLO inference, store annotated output."""
    _detect_for_media("video")
    zone = _validate_mine_zone(db, mine_id, zone_id)
    # Declared type is checked up front; content (magic-byte) validation and
    # the size-capped read happen ONCE, directly into the temp file below —
    # the stream must not be consumed twice.
    declared = _check_declared_type(upload, ALLOWED_VIDEO_TYPES)
    actual = declared

    storage: StorageBackend = get_storage()
    ext = ALLOWED_VIDEO_TYPES[actual]
    original_path = build_media_path(mine_id, "videos", ext)

    # Stream to a temp file (never hold the whole video in RAM).
    # NOTE: the upload stream is read exactly ONCE (size-capped); all later
    # validation reads happen from the temp file on disk.
    tmp_dir = tempfile.mkdtemp(prefix="mineguard_upload_")
    tmp_input = str(Path(tmp_dir) / f"input.{ext}")
    result = None
    original_obj = None
    annotated_obj = None
    processing_seconds = 0.0
    try:
        written = 0
        with open(tmp_input, "wb") as fh:
            while chunk := upload.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_VIDEO_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Video exceeds the {MAX_VIDEO_BYTES // (1024 * 1024)} MB upload limit",
                    )
                fh.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="Empty file")

        # Magic-byte check from the persisted file head.
        with open(tmp_input, "rb") as fh:
            head = fh.read(16)
        if sniff_mime(head) not in ALLOWED_VIDEO_TYPES:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                detail="Video content failed the magic-byte check")

        # Same two-stage policy as images: capture low, gate per-class later.
        th = resolve_thresholds()
        effective_conf = confidence if confidence is not None else th.capture
        started = time.time()
        result = get_yolo_service().detect_video_file(
            tmp_input, confidence=effective_conf, frame_stride=frame_stride,
        )
        processing_seconds = round(time.time() - started, 2)

        # Persist BOTH media files to storage while the temp files still exist.
        original_obj = storage.upload_bytes(
            Path(tmp_input).read_bytes(), path=original_path, mime_type=actual,
        )
        if result.annotated_video_path:
            annotated_obj = storage.upload_bytes(
                Path(result.annotated_video_path).read_bytes(),
                path=build_media_path(mine_id, "results", "mp4"), mime_type="video/mp4",
            )
    finally:
        # All temp files (input + annotated output) are removed after uploads
        # complete, or on any error path — nothing is left on disk.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if result is not None and result.annotated_video_path:
            shutil.rmtree(str(Path(result.annotated_video_path).parent), ignore_errors=True)

    # Safety-rule evaluation over the flattened frame detections.
    findings = evaluate_safety_rules(
        result.detections, zone_name=zone.name if zone else None, is_restricted_zone=zone is not None
    )


    model_version = f"yolo:{Path(settings.YOLO_MODEL_PATH).name}"
    camera_id = zone.camera_id if zone and zone.camera_id else f"CAM-{mine_id[:6].upper()}-VID"
    events_out: list[dict[str, Any]] = []
    alerts_out: list[dict[str, Any]] = []

    # One event per (rule, most significant occurrence) — bounded and explainable:
    # a rule first seen as sub-threshold (undetermined) in frame N must not mask
    # the same rule crossing the violation bar in frame M — the VIOLATION wins.
    from app.services.yolo_detection import DetectionBox

    handled_rules: dict[str, str] = {}  # rule -> best status seen (violation > undetermined > compliance)
    for rec in result.frame_records:
        frame_boxes = [
            DetectionBox(
                class_name=d["class"], class_id=d["class_id"],
                confidence=d["confidence"], bbox=d["bbox"],
            )
            for d in rec["detections"]
        ]
        frame_findings = evaluate_safety_rules(
            frame_boxes, zone_name=zone.name if zone else None, is_restricted_zone=zone is not None
        )
        for f in frame_findings:
            prev = handled_rules.get(f.rule)
            if prev == "violation":
                continue  # already recorded at full severity
            if prev is not None and f.status != "violation":
                continue  # already recorded at equal-or-higher significance
            handled_rules[f.rule] = f.status
            # PPE findings carry their triggering class + model confidence.
            # Zone/crowd rules attribute to the best-matching person/vehicle
            # detection in the same frame.
            if f.detected_class is not None:
                subject, top_conf = f.detected_class, (f.confidence or 0.0)
            elif f.rule == "restricted_zone_person" or f.rule == "crowd_threshold":
                subject, top_conf = "person", max(
                    (d["confidence"] for d in rec["detections"] if d["class"] == "person"),
                    default=0.0,
                )
            else:  # restricted_zone_vehicle
                vehicle_dets = [d for d in rec["detections"] if d["class"] in
                                {"car", "truck", "bus", "motorcycle", "bicycle"}]
                best = max(vehicle_dets, key=lambda d: d["confidence"], default=None)
                subject = best["class"] if best else None
                top_conf = best["confidence"] if best else 0.0
            event, alert = record_yolo_events(
                db,
                mine_id=mine_id, camera_id=camera_id,
                zone_id=zone.id if zone else None, zone_name=zone.name if zone else None,
                event_type=f.event_type, severity=f.severity,
                detected_object=subject,
                confidence=top_conf, model_version=model_version,
                image_ref=annotated_obj.path if annotated_obj else None,
                source_media_ref=original_obj.path,
                detail=f"{f.evidence} @ {rec['timestamp_seconds']}s (frame {rec['frame_number']})",
                frame_number=rec["frame_number"],
                video_timestamp=rec["timestamp_seconds"],
                raise_alert=f.alert,  # compliance detections record, never alert
            )
            events_out.append({
                "camera_event_id": event.id, "event_type": event.event_type,
                "frame_number": rec["frame_number"], "timestamp_seconds": rec["timestamp_seconds"],
                "rule": f.rule, "ppe_status": f.status,
            })
            if alert:
                alerts_out.append({"id": alert.id, "title": alert.title,
                                   "severity": alert.severity, "source": alert.source})

    # Class summary from all real detections.
    class_counts: dict[str, int] = {}
    for d in result.detections:
        class_counts[d.class_name] = class_counts.get(d.class_name, 0) + 1

    return {
        "source": "uploaded_video",
        "detector": "yolo",
        "model": model_version,
        "mine_id": mine_id,
        "zone": {"id": zone.id, "name": zone.name} if zone else None,
        "video_metadata": {
            "filename": upload.filename,
            "duration_seconds": round(result.stats.duration_seconds, 2),
            "fps": round(result.stats.fps, 2),
            "total_frames": result.stats.total_frames,
            "processed_frames": result.stats.processed_frames,
            "frame_stride": frame_stride or settings.YOLO_FRAME_STRIDE,
            "processing_seconds": processing_seconds,
        },
        "detection_count": len(result.detections),
        "classes_detected": sorted(class_counts),
        "class_summary": class_counts,
        "safety_findings": [
            {"rule": f.rule, "event_type": f.event_type, "severity": f.severity,
             "evidence": f.evidence, "status": f.status,
             "confidence": round(f.confidence, 3) if f.confidence is not None else None}
            for f in findings
        ],
        "annotated_video_url": storage.create_access_url(annotated_obj.path) if annotated_obj else None,
        "original_video_url": storage.create_access_url(original_obj.path) if storage else None,
        "camera_event_ids": [e["camera_event_id"] for e in events_out],
        "events": events_out,
        "alerts": alerts_out,
        "storage_provider": getattr(original_obj, "provider", "unknown"),
        "uploaded_by": user.email,
        "person_ppe_report": _person_report(result.detections, findings),
    }
