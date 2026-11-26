"""Reusable live-frame flow for person-aware detectors (person_boxed).

The person_anchor strategy (live_detect._detect_live_frame_anchor) established
this flow: person boxes + ByteTrack IDs -> PPE detections -> EXISTING policy,
association, temporal confirmation, dedupe and alert pipeline -> async evidence.

YOLO-World joins the SAME flow via live_frame_with_world() — a strategy switch
on one parameterized detector call, not a separate live-camera implementation.
Differences from the anchor strategy are detector-level only:
  * one model pass supplies both persons (with ByteTrack IDs) and PPE boxes;
  * no anchor pass / crop pass;
  * model_version labels the experimental world backend;
  * absence honesty: the six text classes are all positive, so no NO-*
    detections exist — missing PPE shows up as UNDETERMINED per-person status
    via the unchanged ppe_policy (never as a fabricated violation).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from app.core.config import settings
from app.services.safety_rules import evaluate_safety_rules
from app.services.yolo_detection import (
    PERSON_CLASSES,
    VEHICLE_CLASSES,
    DetectionBox,
)

logger = logging.getLogger(__name__)


def _live_frame_with_person_boxes(
    *, body, db, user, zone, data: bytes, effective_conf: float,
    detector_call: Callable[[Any], Any],
    detector_name: str, strategy_label: str, model_version: str,
) -> dict[str, Any]:
    """The established person-aware live flow, parameterized by one detector.

    `detector_call(decoded_img)` receives the frame decoded exactly like the
    anchor flow does (BGR -> RGB numpy) and returns an anchor-compatible
    result (persons + PPE). All downstream stages reuse the EXISTING building
    blocks verbatim (never duplicated): detect._person_report, live_detect
    helpers, camera_pipeline.record_yolo_events,
    ppe_policy.associate_with_persons.
    """
    import cv2
    import numpy as np

    from app.api.v1.detect import _person_report  # private but reused, not duplicated
    from app.api.v1.live_detect import (
        _annotate_anchor_evidence,
        _camera_id_for,
        _findings_person_map,
        _person_in_cooldown,
        _recent_event_exists,
        _temporal_confirmed,
        _upload_evidence_async,
    )
    from app.services.camera_pipeline import record_yolo_events
    from app.services.storage import get_storage

    if body.debug_capture:  # dev diagnostic only (see LiveFrameRequest)
        try:
            Path("tmp_diag").mkdir(exist_ok=True)
            Path("tmp_diag/live_frame_capture.jpg").write_bytes(data)
        except Exception:
            pass
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Frame is not a decodable image")

    t_all = time.perf_counter()
    res = detector_call(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    camera_id = _camera_id_for(body.mine_id, body.session_id)

    # The detector supplies the real person boxes (so the EXISTING
    # evaluate_safety_rules keeps its zone/crowd semantics intact).
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
    infer_ms = float(getattr(res, "inference_ms",
                             getattr(res, "ppe_ms", 0.0)
                             + getattr(res, "anchor_ms", 0.0)
                             + getattr(res, "crop_ms", 0.0)))
    policy_ms = (time.perf_counter() - t_all) * 1000 - infer_ms

    storage = get_storage()
    events_out: list[dict[str, Any]] = []
    alerts_out: list[dict[str, Any]] = []
    recorded_event_ids: list[str] = []

    for i, f in enumerate(findings):
        pidx = pmap[i]
        person = (
            res.persons[pidx]
            if pidx is not None and pidx < len(res.persons) else None
        )
        label = (
            f"person#{person.track_id}"
            if person is not None and person.track_id is not None else None
        )

        if person is not None and person.track_id is not None:
            # Temporal confirmation BEFORE the cooldown is stamped (same
            # ordering as the anchor flow) — see live_detect for rationale.
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

        if f.detected_class is not None:
            subject, top_conf = f.detected_class, (f.confidence or 0.0)
        elif f.rule in {"restricted_zone_person", "crowd_threshold"}:
            subject = "person"
            top_conf = max(
                (d.confidence for d in detections_for_rules
                 if d.class_name.lower() in PERSON_CLASSES),
                default=0.0,
            )
        else:
            best = max(
                (d for d in detections_for_rules
                 if d.class_name.lower() in VEHICLE_CLASSES),
                key=lambda d: d.confidence, default=None,
            )
            subject = best.class_name if best else None
            top_conf = best.confidence if best else 0.0

        detail = f"{f.evidence} [live webcam frame; {strategy_label}]"
        if label:
            detail = f"{f.evidence} ({label}) [live webcam frame; {strategy_label}]"

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

    if recorded_event_ids:
        _upload_evidence_async(
            storage, _annotate_anchor_evidence(ppe_detections, res.persons, data),
            body.mine_id, recorded_event_ids,
        )

    return {
        "source": "live_webcam",
        "detector": detector_name,
        "strategy": strategy_label,
        "experimental": detector_name == "yolo_world",
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
        "annotated_image_url": None,
        "evidence_upload": "async" if recorded_event_ids else None,
        "storage_provider": settings.STORAGE_PROVIDER,
        "timings": {
            "inference_ms": round(infer_ms, 1),
            "policy_ms": round(policy_ms, 1),
            "total_response_ms": round((time.perf_counter() - t_all) * 1000, 1),
            "strategy": strategy_label,
        },
        "captured_by": user.email,
    }


def live_frame_with_world(*, body, db, user, zone, data, effective_conf) -> dict[str, Any]:
    """YOLO-World live frame: the established flow with the World backend."""
    from app.api.v1.live_detect import _camera_id_for
    from app.services.detectors.yolo_world import get_yolo_world_service

    detector = get_yolo_world_service()

    def _call(decoded_img):
        return detector.detect(
            decoded_img, confidence=effective_conf,
            session_key=_camera_id_for(body.mine_id, body.session_id),
        )

    return _live_frame_with_person_boxes(
        body=body, db=db, user=user, zone=zone, data=data,
        effective_conf=effective_conf,
        detector_call=_call,
        detector_name="yolo_world",
        strategy_label="yolo_world",
        model_version=f"yolo_world:{Path(detector.model_path).name}",
    )
