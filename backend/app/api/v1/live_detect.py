"""
Live webcam frame detection (separate feature alongside media upload).

Contract: the browser grabs ONE frame from its own webcam stream (canvas ->
JPEG -> base64) and POSTs it here at a low cadence. Each frame runs the SAME
real inference and safety pipeline as an uploaded image:

    get_yolo_service().detect_image_bytes()   (Vyra YOLOv8m / configured model)
    -> resolve_thresholds() two-stage PPE policy (capture low, gate violations)
    -> evaluate_safety_rules()                (real detections only, no fabrication)
    -> record_yolo_events()                   (camera_events + alerts, source='yolo')

Live-specific behaviour (added on top of the upload pipeline; nothing in the
upload path is modified):
  * Per-frame EVENT cooldown: a live feed re-detecting the same violation on
    consecutive frames must not flood camera_events. Within
    LIVE_EVENT_COOLDOWN_SECONDS the finding is evaluated and returned with
    recorded=False / reason='cooldown' — the alert pipeline itself still
    dedupes alerts per camera+event_type over its 60-minute window.
  * Only the annotated result image is persisted per recorded event (a live
    session never stores every raw frame).
  * The response explicitly states source='live_webcam' so the UI can never
    present it as archived media analysis.

Every response states the detector used. No fake detections: an empty frame
yields empty findings and NO events.
"""
import base64
import binascii
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.roles import write_access
from app.core.security import get_current_user
from app.database.models import CameraEvent, User
from app.database.session import get_db
from app.services.camera_pipeline import record_yolo_events
from app.services.ppe_policy import associate_with_persons, resolve_thresholds
from app.services.safety_rules import PPE_HANDLED_CLASSES, evaluate_safety_rules
from app.services.storage import ALLOWED_IMAGE_TYPES, build_media_path, get_storage, sniff_mime
from app.services.yolo_detection import (
    PERSON_CLASSES,
    VEHICLE_CLASSES,
    DetectionBox,
    YoloNotConfiguredError,
    get_yolo_service,
)


def _validate_mine_zone(db: Session, mine_id: str, zone_id: str | None):
    """Same mine/zone validation as the upload endpoints (local copy to avoid a
    private-name import; behaviour is identical, including error messages)."""
    from app.database.models import Mine, RestrictedZone

    if db.get(Mine, mine_id) is None:
        raise HTTPException(status_code=400, detail=f"Unknown mine_id '{mine_id}'")
    zone = None
    if zone_id is not None:
        zone = db.get(RestrictedZone, zone_id)
        if zone is None or zone.mine_id != mine_id:
            raise HTTPException(status_code=400, detail="zone_id does not belong to the given mine")
    return zone

router = APIRouter(
    prefix="/ai/detect",
    tags=["AI Live Detection (YOLO)"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
LiveUser = Annotated[User, Depends(write_access("ai_simulation"))]


class LiveFrameRequest(BaseModel):
    """One webcam frame + capture context (mirrors the image-upload params)."""

    mine_id: str = Field(min_length=1, max_length=60)
    zone_id: str | None = Field(default=None, max_length=60)
    confidence: float | None = Field(default=None, ge=0.05, le=1.0)
    # Raw base64 (or data-URL) of a single JPEG/PNG/WebP frame from getUserMedia.
    image_base64: str = Field(min_length=32)
    # Optional client session marker so distinct live sessions get distinct
    # camera ids (alert dedupe stays per camera; sessions don't mask each other).
    session_id: str | None = Field(default=None, max_length=24)
    # DEBUG-ONLY: save the raw frame to backend/tmp_diag/ for offline inference
    # diagnostics. Never set by the production UI; no effect unless the anchor
    # strategy branch runs.
    debug_capture: bool = False


def _require_yolo() -> None:
    """Same detector guard as the upload endpoints (503, never simulated)."""
    if settings.AI_DETECTOR != "yolo":
        raise HTTPException(
            status_code=503,
            detail=(
                "YOLO detection is disabled (AI_DETECTOR != 'yolo'). Set AI_DETECTOR=yolo "
                "with a valid YOLO_MODEL_PATH to use live detection."
            ),
        )
    try:
        get_yolo_service()._load_model()
    except YoloNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _decode_frame(image_base64: str) -> bytes:
    """Decode a base64 frame and enforce type + size limits on real bytes."""
    payload = image_base64.strip()
    if payload.startswith("data:"):  # data URL form: data:image/jpeg;base64,....
        _, _, payload = payload.partition(",")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Frame is not valid base64: {exc}")
    if not data:
        raise HTTPException(status_code=400, detail="Empty frame")
    max_bytes = settings.MAX_FRAME_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Frame exceeds the {settings.MAX_FRAME_UPLOAD_MB} MB limit",
        )
    actual = sniff_mime(data)
    if actual not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Frame must be a real JPEG/PNG/WebP image (magic-byte check failed)",
        )
    return data


def _recent_event_exists(db: Session, camera_id: str, event_type: str) -> bool:
    """Live EVENT cooldown: same camera + event_type within the cooldown window."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.LIVE_EVENT_COOLDOWN_SECONDS)
    return db.scalar(
        select(CameraEvent.id).where(
            CameraEvent.camera_id == camera_id,
            CameraEvent.event_type == event_type,
            CameraEvent.occurred_at >= cutoff,
        )
    ) is not None


def _camera_id_for(mine_id: str, session_id: str | None) -> str:
    if session_id:
        safe = "".join(c for c in session_id if c.isalnum() or c == "-")[:12]
        if safe:
            return f"CAM-{mine_id[:6].upper()}-LIVE-{safe}"
    return f"CAM-{mine_id[:6].upper()}-LIVE"


# --------------------------------------------------------------------------- #
# OPT-IN anchor strategy (AI_DETECTOR_STRATEGY=person_anchor)                  #
# COCO person anchor + ByteTrack IDs; PPE still from Vyra only; the existing   #
# policy/association code is reused verbatim. Default strategy is untouched.   #
# --------------------------------------------------------------------------- #

# Person-specific live dedupe: (camera_id, track_id, event_type) -> last
# recorded ts. In-memory BY DESIGN (no schema change): track ids are per-
# session, so persistence would be misleading; the DB-level camera+event_type
# cooldown below remains as the global fallback.
_person_dedupe: dict[tuple[str, int, str], float] = {}
_person_dedupe_lock = threading.Lock()


def _person_in_cooldown(camera_id: str, track_id: int, event_type: str) -> bool:
    key = (camera_id, track_id, event_type)
    now = time.monotonic()
    with _person_dedupe_lock:
        last = _person_dedupe.get(key)
        if last is not None and (now - last) < settings.LIVE_EVENT_COOLDOWN_SECONDS:
            return True
        _person_dedupe[key] = now
        # Bound memory (same spirit as the tracker pool cap).
        if len(_person_dedupe) > 4096:
            _person_dedupe.clear()
        return False


# Temporal confirmation (requirement 11): a violation alerts only when seen
# in N of the last M frames for the same (camera, track_id, event_type).
# Config-gated: N<=1 disables it entirely (single-frame alerting = prior
# behaviour and the guaranteed ~1s alert latency). The window is per PERSON,
# so two people violating independently confirm independently.
_temporal: dict[tuple[str, int, str], deque] = {}
_temporal_lock = threading.Lock()


def _temporal_confirmed(camera_id: str, track_id: int, event_type: str, hit: bool) -> bool:
    n, m = settings.LIVE_TEMPORAL_CONFIRM_N, settings.LIVE_TEMPORAL_CONFIRM_M
    if n <= 1 or m <= 1:
        return True
    key = (camera_id, track_id, event_type)
    with _temporal_lock:
        dq = _temporal.setdefault(key, deque(maxlen=m))
        dq.append(1 if hit else 0)
        if len(_temporal) > 4096:
            _temporal.clear()
        return sum(dq) >= n


def _upload_evidence_async(storage, annotated_png: bytes, mine_id: str,
                           event_ids: list[str]) -> None:
    """Upload the annotated frame AFTER the response is sent (daemon thread).

    Evidence storage is preserved — only its position on the critical path
    changes. Event rows are patched with the image_ref once the upload lands.
    """
    from app.database.session import SessionLocal
    from app.database.models import CameraEvent

    def _run():
        try:
            obj = storage.upload_bytes(
                annotated_png, path=build_media_path(mine_id, "results", "png"),
                mime_type="image/png",
            )
            db = SessionLocal()
            try:
                db.query(CameraEvent).filter(CameraEvent.id.in_(event_ids)).update(
                    {CameraEvent.image_ref: obj.path, CameraEvent.source_media_ref: obj.path},
                    synchronize_session=False,
                )
                db.commit()
            finally:
                db.close()
        except Exception:  # never crash the app for an evidence upload
            import logging
            logging.getLogger(__name__).exception("async evidence upload failed")

    threading.Thread(target=_run, daemon=True, name="live-evidence-upload").start()


def _findings_person_map(findings, ppe_detections, person_boxes) -> list:
    """Resolve the OWNING person (index into person_boxes) for each finding.

    evaluate_safety_rules emits one finding per PPE detection box, in order,
    with zone/crowd findings trailing (detected_class=None) — so findings pair
    back to boxes positionally. Ownership uses the EXISTING
    ppe_policy.associate_with_persons() rule (never duplicated here).
    """
    ppe_boxes = [
        (d.class_name, d.confidence, d.bbox)
        for d in ppe_detections
        if d.class_name.lower() in PPE_HANDLED_CLASSES
    ]
    assoc = associate_with_persons(
        ppe_boxes, [(p.confidence, p.bbox) for p in person_boxes]
    )
    # Invert person->entries into entry-index->person (value match is exact).
    owner_of_ppe: list = [None] * len(ppe_boxes)
    for pidx, entries in assoc.items():
        for e in entries:
            for i, (cls, conf, bbox) in enumerate(ppe_boxes):
                if cls == e["class"] and conf == e["confidence"] and bbox == e["bbox"]:
                    owner_of_ppe[i] = pidx
                    break
    mapping: list = []
    ppe_i = 0
    for f in findings:
        if f.detected_class is not None and f.detected_class.lower() in PPE_HANDLED_CLASSES:
            mapping.append(owner_of_ppe[ppe_i] if ppe_i < len(owner_of_ppe) else None)
            ppe_i += 1
        else:
            mapping.append(None)
    return mapping


def _annotate_anchor_evidence(ppe_detections, persons, raw: bytes) -> bytes:
    """PNG evidence: person boxes (magenta, track IDs) + PPE boxes (green worn /
    red violation). Best-effort — the raw frame is the fallback evidence."""
    try:
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return raw
        for p in persons:
            x1, y1, x2, y2 = (int(v) for v in p.bbox)
            cv2.rectangle(img, (x1, y1), (x2, y2), (255, 0, 255), 2)
            if p.track_id is not None:
                cv2.putText(img, f"#{p.track_id}", (x1, max(16, y1 - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
        for d in ppe_detections:
            x1, y1, x2, y2 = (int(v) for v in d.bbox)
            color = (0, 0, 255) if d.class_name.lower().startswith(("no-", "no_", "fall")) else (0, 200, 0)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            cv2.putText(img, f"{d.class_name} {d.confidence:.2f}",
                        (x1, min(img.shape[0] - 5, y2 + 18)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        ok, buf = cv2.imencode(".png", img)
        return bytes(buf) if ok else raw
    except Exception:
        return raw


def _detect_live_frame_anchor(*, body, db, user, zone, data, effective_conf) -> dict:
    """The /frame endpoint under AI_DETECTOR_STRATEGY=person_anchor.

    yolo11n person anchor + ByteTrack IDs -> Vyra PPE (UNCHANGED model) ->
    existing policy + associate_with_persons -> PER-PERSON verdicts ->
    person-specific dedupe -> immediate alert; annotated-image evidence is
    uploaded AFTER the response (off the alert critical path, still stored).
    """
    import cv2
    import numpy as np

    from app.api.v1.detect import _person_report  # private but reused, not duplicated
    from app.services.detectors import get_anchor_detector

    t_all = time.perf_counter()
    if body.debug_capture:  # dev diagnostic only (see LiveFrameRequest)
        try:
            Path("tmp_diag").mkdir(exist_ok=True)
            Path("tmp_diag/live_frame_capture.jpg").write_bytes(data)
        except Exception:
            pass
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Frame is not a decodable image")

    anchor = get_anchor_detector()
    res = anchor.detect(cv2.cvtColor(img, cv2.COLOR_BGR2RGB),
                        confidence=effective_conf, session_key=_camera_id_for(body.mine_id, body.session_id))

    # The anchor supplies the real person boxes (Vyra emits none), so the
    # EXISTING evaluate_safety_rules keeps its zone/crowd semantics intact.
    # Comparison PPE models that also carry a Person class (e.g. Hansung-PPE)
    # must not double-count: person boxes for the RULES always come from the
    # anchor only. (No-op for Vyra, which has no person class.)
    ppe_detections = [
        d for d in res.detections if d.class_name.lower() not in PERSON_CLASSES
    ]
    detections_for_rules = ppe_detections + [
        DetectionBox(class_name="person", class_id=0, confidence=p.confidence, bbox=p.bbox)
        for p in res.persons
    ]
    findings = evaluate_safety_rules(
        detections_for_rules,
        zone_name=zone.name if zone else None,
        is_restricted_zone=zone is not None,
    )
    pmap = _findings_person_map(findings, ppe_detections, res.persons)
    person_report = _person_report(
        ppe_detections, findings,
        person_boxes=[(p.confidence, p.bbox) for p in res.persons],
        person_ids=[p.track_id for p in res.persons],
    )
    policy_ms = (time.perf_counter() - t_all) * 1000 - res.total_ms

    model_version = (
        f"anchor:{Path(anchor.ppe_model_path).name}"
        f"+{Path(anchor.anchor_model_path).name}"
    )
    camera_id = _camera_id_for(body.mine_id, body.session_id)
    storage = get_storage()
    events_out: list[dict[str, Any]] = []
    alerts_out: list[dict[str, Any]] = []
    recorded_event_ids: list[str] = []

    for i, f in enumerate(findings):
        pidx = pmap[i]
        person = res.persons[pidx] if pidx is not None and pidx < len(res.persons) else None
        label = f"person#{person.track_id}" if person is not None and person.track_id is not None else None

        # Person-specific cooldown keyed by (camera, track_id, event_type);
        # existing camera+event_type cooldown is the fallback when no ID.
        if person is not None and person.track_id is not None:
            # Temporal confirmation BEFORE the cooldown is stamped, so the
            # frame that completes the window is free to record the alert.
            if not _temporal_confirmed(
                camera_id, person.track_id, f.event_type, f.status == "violation"
            ):
                events_out.append({
                    "camera_event_id": None,
                    "event_type": f.event_type,
                    "rule": f.rule,
                    "ppe_status": f.status,
                    "track_id": person.track_id,
                    "recorded": False,
                    "reason": "awaiting_confirmation",
                })
                continue
            in_cooldown = _person_in_cooldown(camera_id, person.track_id, f.event_type)
        else:
            in_cooldown = _recent_event_exists(db, camera_id, f.event_type)
        if in_cooldown:
            events_out.append({
                "camera_event_id": None,
                "event_type": f.event_type,
                "rule": f.rule,
                "ppe_status": f.status,
                "track_id": person.track_id if person else None,
                "recorded": False,
                "reason": "cooldown",
            })
            continue

        # Attribute zone/crowd rules to the best real detection (default parity).
        if f.detected_class is not None:
            subject, top_conf = f.detected_class, (f.confidence or 0.0)
        elif f.rule in {"restricted_zone_person", "crowd_threshold"}:
            subject = "person"
            top_conf = max(
                (d.confidence for d in detections_for_rules if d.class_name.lower() in PERSON_CLASSES),
                default=0.0,
            )
        else:
            best = max(
                (d for d in detections_for_rules if d.class_name.lower() in VEHICLE_CLASSES),
                key=lambda d: d.confidence,
                default=None,
            )
            subject = best.class_name if best else None
            top_conf = best.confidence if best else 0.0

        detail = f"{f.evidence} [live webcam frame; person_anchor]"
        if label:
            detail = f"{f.evidence} ({label}) [live webcam frame; person_anchor]"

        # ALERT IMMEDIATELY: image_ref=None here; evidence uploads async below.
        event, alert = record_yolo_events(
            db,
            mine_id=body.mine_id,
            camera_id=camera_id,
            zone_id=zone.id if zone else None,
            zone_name=zone.name if zone else None,
            event_type=f.event_type,
            severity=f.severity,
            detected_object=label if label else subject,
            confidence=top_conf,
            model_version=model_version,
            image_ref=None,
            source_media_ref=None,
            detail=detail,
            raise_alert=f.alert,
            dedupe_by_object=bool(label),
        )
        recorded_event_ids.append(event.id)
        events_out.append({
            "camera_event_id": event.id,
            "event_type": event.event_type,
            "rule": f.rule,
            "ppe_status": f.status,
            "track_id": person.track_id if person else None,
            "recorded": True,
            "reason": "new",
        })
        if alert:
            alerts_out.append({
                "id": alert.id, "title": alert.title,
                "severity": alert.severity, "source": alert.source,
                "track_id": person.track_id if person else None,
            })

    # Evidence OFF the critical path: uploaded after the response is sent.
    if recorded_event_ids:
        _upload_evidence_async(
            storage, _annotate_anchor_evidence(ppe_detections, res.persons, data),
            body.mine_id, recorded_event_ids,
        )

    return {
        "source": "live_webcam",
        "detector": "yolo",
        "strategy": "person_anchor",
        "model": model_version,
        "mine_id": body.mine_id,
        "zone": {"id": zone.id, "name": zone.name} if zone else None,
        "camera_id": camera_id,
        "detections": [d.as_dict() for d in ppe_detections],
        "detection_count": len(ppe_detections),
        "classes_detected": sorted({d.class_name for d in ppe_detections}),
        "persons": [p.as_dict() for p in res.persons],
        "person_ppe_report": person_report,
        "safety_findings": [
            {
                "rule": f.rule, "event_type": f.event_type, "severity": f.severity,
                "evidence": f.evidence, "status": f.status,
                "confidence": round(f.confidence, 3) if f.confidence is not None else None,
                "track_id": (res.persons[pmap[i]].track_id
                             if pmap[i] is not None and pmap[i] < len(res.persons) else None),
            }
            for i, f in enumerate(findings)
        ],
        "events": events_out,
        "camera_event_ids": recorded_event_ids,
        "alerts": alerts_out,
        # Signed URL is created asynchronously; the UI polls nothing — the
        # evidence appears on the event record once the upload lands.
        "annotated_image_url": None,
        "evidence_upload": "async" if recorded_event_ids else None,
        "storage_provider": settings.STORAGE_PROVIDER,
        "timings": {
            "ppe_ms": round(res.ppe_ms, 1),
            "anchor_ms": round(res.anchor_ms, 1),
            "crop_ms": round(getattr(res, "crop_ms", 0.0), 1),
            "policy_ms": round(policy_ms, 1),
            "total_response_ms": round((time.perf_counter() - t_all) * 1000, 1),
            "strategy": "person_anchor",
        },
        "captured_by": user.email,
    }


@router.post("/frame")
def detect_live_frame(
    body: LiveFrameRequest,
    db: DbSession,
    user: LiveUser,
) -> dict[str, Any]:
    """Run the real PPE pipeline on ONE live webcam frame. Separate from uploads."""
    _require_yolo()
    zone = _validate_mine_zone(db, body.mine_id, body.zone_id)
    data = _decode_frame(body.image_base64)

    # Two-stage PPE policy: capture low, gate violations per-class (upload parity).
    th = resolve_thresholds()
    effective_conf = body.confidence if body.confidence is not None else th.capture

    # OPT-IN anchor strategy: everything below stays the untouched default path.
    if settings.AI_DETECTOR_STRATEGY == "person_anchor":
        return _detect_live_frame_anchor(
            body=body, db=db, user=user, zone=zone, data=data,
            effective_conf=effective_conf,
        )

    try:
        detections, annotated_png = get_yolo_service().detect_image_bytes(
            data, confidence=effective_conf
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    findings = evaluate_safety_rules(
        detections, zone_name=zone.name if zone else None, is_restricted_zone=zone is not None
    )

    model_version = f"yolo:{Path(settings.YOLO_MODEL_PATH).name}"
    camera_id = _camera_id_for(body.mine_id, body.session_id)
    storage = get_storage()
    events_out: list[dict[str, Any]] = []
    alerts_out: list[dict[str, Any]] = []
    annotated_obj = None

    for f in findings:
        # Attribute zone/crowd rules to the best real detection (same as video path).
        if f.detected_class is not None:
            subject, top_conf = f.detected_class, (f.confidence or 0.0)
        elif f.rule in {"restricted_zone_person", "crowd_threshold"}:
            subject = "person"
            top_conf = max(
                (d.confidence for d in detections if d.class_name.lower() in PERSON_CLASSES),
                default=0.0,
            )
        else:  # restricted_zone_vehicle
            best = max(
                (d for d in detections if d.class_name.lower() in VEHICLE_CLASSES),
                key=lambda d: d.confidence,
                default=None,
            )
            subject = best.class_name if best else None
            top_conf = best.confidence if best else 0.0

        # Live cooldown: evaluate + report, but do not flood camera_events.
        in_cooldown = _recent_event_exists(db, camera_id, f.event_type)
        if in_cooldown:
            events_out.append({
                "camera_event_id": None,
                "event_type": f.event_type,
                "rule": f.rule,
                "ppe_status": f.status,
                "recorded": False,
                "reason": "cooldown",
            })
            continue

        # Persist the annotated frame only when an event is actually recorded.
        if annotated_obj is None:
            annotated_obj = storage.upload_bytes(
                annotated_png, path=build_media_path(body.mine_id, "results", "png"),
                mime_type="image/png",
            )

        event, alert = record_yolo_events(
            db,
            mine_id=body.mine_id,
            camera_id=camera_id,
            zone_id=zone.id if zone else None,
            zone_name=zone.name if zone else None,
            event_type=f.event_type,
            severity=f.severity,
            detected_object=subject,
            confidence=top_conf,
            model_version=model_version,
            image_ref=annotated_obj.path,
            source_media_ref=annotated_obj.path,
            detail=f"{f.evidence} [live webcam frame]",
            raise_alert=f.alert,  # compliance/undetermined never alert
        )
        events_out.append({
            "camera_event_id": event.id,
            "event_type": event.event_type,
            "rule": f.rule,
            "ppe_status": f.status,
            "recorded": True,
            "reason": "new",
        })
        if alert:
            alerts_out.append({
                "id": alert.id, "title": alert.title,
                "severity": alert.severity, "source": alert.source,
            })

    return {
        "source": "live_webcam",
        "detector": "yolo",
        "model": model_version,
        "mine_id": body.mine_id,
        "zone": {"id": zone.id, "name": zone.name} if zone else None,
        "camera_id": camera_id,
        "detections": [d.as_dict() for d in detections],
        "detection_count": len(detections),
        "classes_detected": sorted({d.class_name for d in detections}),
        "safety_findings": [
            {
                "rule": f.rule, "event_type": f.event_type, "severity": f.severity,
                "evidence": f.evidence, "status": f.status,
                "confidence": round(f.confidence, 3) if f.confidence is not None else None,
            }
            for f in findings
        ],
        "events": events_out,
        "camera_event_ids": [e["camera_event_id"] for e in events_out if e["camera_event_id"]],
        "alerts": alerts_out,
        "annotated_image_url": (
            storage.create_access_url(annotated_obj.path) if annotated_obj else None
        ),
        "storage_provider": getattr(annotated_obj, "provider", "none"),
        "captured_by": user.email,
    }
