"""
Camera event pipeline (Phase 10).

Detection (simulated or YOLO) -> camera_events row -> safety alert.

Rules:
  * Restricted-zone events (restricted_zone_entry, vehicle_in_restricted_area)
    and fire_smoke always raise alerts.
  * Other event types raise alerts when severity is high/critical.
  * Duplicate suppression: one unresolved alert per camera+event_type within
    the cooldown window.
  * Alerts carry source_event_id traceability and source="camera_pipeline";
    the description always labels the detection source honestly.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.detector import get_detector
from app.core.config import settings
from app.database.models import Alert, CameraEvent, Mine, RestrictedZone

ALERT_RAISING_EVENTS = {"restricted_zone_entry", "vehicle_in_restricted_area", "fire_smoke"}
HIGH_SEVERITY = {"high", "critical"}
DUPLICATE_WINDOW_MINUTES = 60


def _should_alert(event: CameraEvent) -> bool:
    return event.event_type in ALERT_RAISING_EVENTS or event.severity in HIGH_SEVERITY


def _find_open_duplicate(db: Session, camera_id: str, event_type: str) -> Alert | None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
    return db.scalar(
        select(Alert).where(
            Alert.source == "camera_pipeline",
            Alert.status != "resolved",
            Alert.created_at >= cutoff,
            Alert.source_event_id.in_(
                select(CameraEvent.id).where(
                    CameraEvent.camera_id == camera_id,
                    CameraEvent.event_type == event_type,
                )
            ),
        )
    )


def process_detection(
    db: Session,
    *,
    mine_id: str,
    camera_id: str,
    zone_id: str | None = None,
    detection=None,  # app.ai.detector.Detection; generated when None
) -> tuple[CameraEvent, Alert | None]:
    """Store one detection and raise an alert when warranted. Returns (event, alert)."""
    from app.ai.detector import Detection  # local import avoids cycles in tooling

    if detection is None:
        detection = get_detector().detect(camera_id)

    mine = db.get(Mine, mine_id)
    if mine is None:
        raise ValueError(f"Unknown mine '{mine_id}'")

    zone: RestrictedZone | None = None
    if zone_id is not None:
        zone = db.get(RestrictedZone, zone_id)
        if zone is None or zone.mine_id != mine_id:
            raise ValueError("zone_id does not belong to the given mine")

    event = CameraEvent(
        mine_id=mine_id,
        zone_id=zone_id,
        camera_id=camera_id,
        event_type=detection.event_type,
        detected_object=detection.detected_object,
        zone_label=zone.name if zone else None,
        confidence=detection.confidence,
        severity=detection.severity,
        status="new",
        detection_source=detection.detection_source,
        model_version=detection.model_version,
        image_ref=detection.image_ref,
    )
    db.add(event)
    db.flush()  # need event.id before creating the alert

    alert: Alert | None = None
    if _should_alert(event) and _find_open_duplicate(db, camera_id, event.event_type) is None:
        source_label = (
            "simulated detection" if detection.detection_source == "simulated"
            else f"{detection.detection_source} detection"
        )
        alert = Alert(
            mine_id=mine_id,
            alert_type="safety",
            title=f"{event.event_type.replace('_', ' ').title()} — {zone.name if zone else camera_id}",
            description=(
                f"Camera {camera_id} raised a {source_label} "
                f"(confidence {event.confidence:.2f}, model {detection.model_version or 'n/a'}). "
                "Data is simulated unless detection_source is 'yolo'."
            ),
            severity=event.severity,
            source="camera_pipeline",
            status="new",
            source_event_id=event.id,
        )
        db.add(alert)

    db.commit()
    db.refresh(event)
    if alert is not None:
        db.refresh(alert)
    return event, alert


def generate_simulated_event(
    db: Session,
    *,
    mine_id: str,
    camera_id: str | None = None,
    zone_id: str | None = None,
) -> tuple[CameraEvent, Alert | None]:
    """Convenience wrapper used by the demo endpoint: simulate one event."""
    if camera_id is None:
        zone: RestrictedZone | None = None
        if zone_id is not None:
            zone = db.get(RestrictedZone, zone_id)
            if zone is None or zone.mine_id != mine_id:
                raise ValueError("zone_id does not belong to the given mine")
        camera_id = zone.camera_id if zone and zone.camera_id else f"CAM-{mine_id[:6].upper()}-SIM"
    return process_detection(db, mine_id=mine_id, camera_id=camera_id, zone_id=zone_id)
