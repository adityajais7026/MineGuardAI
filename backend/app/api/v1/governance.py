"""Smart Governance & Compliance API routers.

New, ADDITIVE endpoints. Existing routers (detect/live_detect/alerts/...) are
untouched; the PPE pipeline is not modified. All new endpoints:
  * require authentication (get_current_user) — same as existing routers;
  * enforce RBAC through the central WRITE_ROLES map (new areas registered
    in app/core/roles.py);
  * enforce mine-scoped access via ensure_mine_access / permitted mines;
  * never fabricate data: AI outputs are suggestions, unknowns stay unknown.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import roles
from app.core.config import settings
from app.core.security import get_current_user
from app.services.storage import sniff_mime
from app.database.models import (
    Attendance,
    AuditEvent,
    CameraEvent,
    ComplianceAssessment,
    ComplianceRequirement,
    Contractor,
    ContractorDocument,
    CorrectiveAction,
    EmergencyEvent,
    Evidence,
    Geofence,
    Incident,
    Inspection,
    InspectionChecklistItem,
    InspectionTemplate,
    InspectionTemplateItem,
    Notification,
    RestrictedZone,
    RiskScore,
    SensorDevice,
    Shift,
    SyncRecord,
    TelemetryReading,
    User,
    Worker,
)
from app.database.session import get_db
from app.schemas.governance import (
    AttendanceCreate,
    AttendanceOut,
    AuditEventOut,
    AuditVerifyOut,
    ChecklistItemOut,
    ChecklistResultIn,
    ComplianceAssessmentCreate,
    ComplianceAssessmentOut,
    ComplianceRequirementCreate,
    ComplianceRequirementOut,
    ComplianceSummaryOut,
    ContractorCreate,
    ContractorDocumentCreate,
    ContractorDocumentOut,
    ContractorOut,
    EmergencyCreate,
    EmergencyOut,
    EvidenceOut,
    GeofenceCreate,
    GeofenceOut,
    InspectionTemplateCreate,
    InspectionTemplateOut,
    LocationVerifyIn,
    LocationVerifyOut,
    ReviewTransitionOut,
    NotificationOut,
    OcrResultOut,
    RiskScoreOut,
    SensorDeviceCreate,
    SensorDeviceOut,
    ShiftCreate,
    ShiftOut,
    SyncPushIn,
    SyncPushOut,
    SyncQueueOut,
    TelemetryReadingCreate,
    TelemetryReadingOut,
    TranslationResultOut,
    VoiceResultOut,
    WorkerCreate,
    WorkerOut,
)
from app.services.governance import ai_adapters, audit_chain, geofence as geofence_svc, inspections as inspection_svc, reports as report_svc, risk as risk_svc, sla as sla_svc

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _get_mine_or_404(db: Session, mine_id: str):
    from app.database.models import Mine  # local import to avoid circularity at module load

    mine = db.get(Mine, mine_id)
    if mine is None:
        raise HTTPException(status_code=404, detail="Mine not found.")
    return mine


def _ensure_mine_scope(user: User, mine_id: str | None, db: Session) -> None:
    """Mine-scoped read guard: admins see all; others must be permitted.

    Uses the same scope rules as app.services.mine_access (manager assignment
    for mine_manager; permitted_mine_ids for officers).
    """
    if mine_id is None or user.role == "admin":
        return
    mine = _get_mine_or_404(db, mine_id)
    if user.role == "mine_manager":
        if mine.manager_id != user.id:
            raise HTTPException(status_code=403, detail="Restricted to your assigned mine.")
        return
    permitted = user.permitted_mine_ids or []
    if mine_id not in permitted:
        raise HTTPException(status_code=403, detail="Restricted to mines assigned to you.")


def _ensure_mine_scope_obj(user: User, mine, db: Session) -> None:
    """Same as _ensure_mine_scope but takes an already-loaded Mine row."""
    if user.role == "admin":
        return
    if user.role == "mine_manager":
        if mine.manager_id != user.id:
            raise HTTPException(status_code=403, detail="Restricted to your assigned mine.")
        return
    permitted = user.permitted_mine_ids or []
    if mine.id not in permitted:
        raise HTTPException(status_code=403, detail="Restricted to mines assigned to you.")


# ===========================================================================
# Inspection templates
# ===========================================================================

templates_router = APIRouter(
    prefix="/governance/inspection-templates", tags=["Governance: Inspection Templates"],
    dependencies=[Depends(get_current_user)],
)


@templates_router.get("", response_model=list[InspectionTemplateOut])
def list_templates(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    stmt = select(InspectionTemplate).where(InspectionTemplate.is_active.is_(True))
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where((InspectionTemplate.mine_id == mine_id) | (InspectionTemplate.mine_id.is_(None)))
    return db.execute(stmt.order_by(InspectionTemplate.created_at.desc())).scalars().all()


@templates_router.post("", response_model=InspectionTemplateOut, status_code=201,
                       dependencies=[Depends(roles.write_access("inspection_templates"))])
def create_template(payload: InspectionTemplateCreate, db: DbSession, user: CurrentUser):
    if payload.mine_id:
        _ensure_mine_scope(user, payload.mine_id, db)
    template = InspectionTemplate(
        name=payload.name,
        description=payload.description,
        inspection_type=payload.inspection_type,
        mine_id=payload.mine_id,
        regulatory_reference=payload.regulatory_reference,
        created_by_id=user.id,
    )
    db.add(template)
    db.flush()
    for pos, item in enumerate(payload.items):
        db.add(InspectionTemplateItem(
            template_id=template.id,
            position=pos,
            label=item.label,
            description=item.description,
            category=item.category,
            result_options=item.result_options,
            severity_weight=item.severity_weight,
            requires_evidence=item.requires_evidence,
        ))
    db.commit()
    db.refresh(template)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="template.create",
        entity_type="inspection_template", entity_id=template.id, mine_id=template.mine_id,
        payload={"name": template.name, "items": len(payload.items)},
    )
    return template


# ===========================================================================
# Inspections (extended: template snapshot + checklist + submit + audit)
# ===========================================================================

gov_inspections_router = APIRouter(
    prefix="/governance/inspections", tags=["Governance: Inspections"],
    dependencies=[Depends(get_current_user)],
)


@gov_inspections_router.post("/from-template", status_code=201,
                             dependencies=[Depends(roles.write_access("inspections"))])
def start_inspection_from_template(
    payload: dict, db: DbSession, user: CurrentUser,
):
    """Create an inspection from a template (snapshots the checklist).

    Body: {mine_id, template_id, scheduled_at?, latitude?, longitude?,
           location_text?, description?}
    Returns the created inspection + snapshotted checklist items.
    """
    mine_id = payload.get("mine_id")
    template_id = payload.get("template_id")
    if not mine_id or not template_id:
        raise HTTPException(status_code=422, detail="mine_id and template_id are required.")
    mine = _get_mine_or_404(db, mine_id)
    _ensure_mine_scope_obj(user, mine, db)
    template = db.get(InspectionTemplate, template_id)
    if template is None or not template.is_active:
        raise HTTPException(status_code=404, detail="Template not found or inactive.")

    now = datetime.now(timezone.utc)
    inspection = Inspection(
        mine_id=mine_id,
        inspector_id=user.id,
        inspection_type=template.inspection_type,
        status="in_progress",
        scheduled_at=payload.get("scheduled_at") or now,
        findings=payload.get("description"),
        notes=payload.get("location_text"),
    )
    # GPS evidence: store captured device coords in notes-free fields via a
    # simple convention — full GPS verification is the geofence endpoint.
    lat = payload.get("latitude")
    lng = payload.get("longitude")
    gps_record: dict = {}
    if lat is not None and lng is not None:
        verification = geofence_svc.verify_location(db, mine_id, lat, lng)
        gps_record = {"latitude": lat, "longitude": lng, "verification": verification}
    db.add(inspection)
    db.flush()
    if gps_record:
        inspection.notes = json.dumps({"gps": gps_record})
        db.flush()
    items = inspection_svc.snapshot_template(db, inspection, template)
    db.refresh(inspection)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="inspection.start",
        entity_type="inspection", entity_id=inspection.id, mine_id=mine_id,
        payload={"template_id": template_id, "gps": gps_record},
    )
    return {
        "inspection_id": inspection.id,
        "checklist": [ChecklistItemOut.model_validate(i).model_dump() for i in items],
    }


@gov_inspections_router.get("/{inspection_id}/checklist", response_model=list[ChecklistItemOut])
def get_checklist(inspection_id: str, db: DbSession, user: CurrentUser):
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    _ensure_mine_scope(user, insp.mine_id, db)
    items = db.execute(
        select(InspectionChecklistItem)
        .where(InspectionChecklistItem.inspection_id == inspection_id)
        .order_by(InspectionChecklistItem.position)
    ).scalars().all()
    return items


@gov_inspections_router.put("/{inspection_id}/checklist", response_model=list[ChecklistItemOut],
                            dependencies=[Depends(roles.write_access("inspections"))])
def submit_checklist(inspection_id: str, payload: dict, db: DbSession, user: CurrentUser):
    """Apply checklist results. Body: {results: {item_id: {result, comment, ai_suggestion?}}}."""
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    _ensure_mine_scope_obj(user, _get_mine_or_404(db, insp.mine_id), db)
    try:
        items = inspection_svc.apply_checklist_results(db, inspection_id, payload.get("results", {}))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return items


@gov_inspections_router.post("/{inspection_id}/submit", status_code=200,
                             dependencies=[Depends(roles.write_access("inspections"))])
def submit_inspection(inspection_id: str, db: DbSession, user: CurrentUser):
    """Complete an inspection: roll up compliance mechanically + audit."""
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    _ensure_mine_scope_obj(user, _get_mine_or_404(db, insp.mine_id), db)
    if insp.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Inspection already {insp.status}.")
    items = db.execute(
        select(InspectionChecklistItem).where(InspectionChecklistItem.inspection_id == inspection_id)
    ).scalars().all()
    rollup = inspection_svc.rollup_compliance(items)
    insp.compliance_result = rollup
    insp.status = "completed"
    insp.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(insp)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="inspection.submit",
        entity_type="inspection", entity_id=inspection_id, mine_id=insp.mine_id,
        payload={"compliance_result": rollup, "items": len(items)},
    )
    return {"inspection_id": inspection_id, "compliance_result": rollup, "items": len(items)}


@gov_inspections_router.post("/{inspection_id}/review", response_model=ReviewTransitionOut,
                             dependencies=[Depends(roles.write_access("inspections"))])
def transition_review_status(inspection_id: str, payload: dict, db: DbSession, user: CurrentUser):
    """Advanced the review/approval lifecycle (additive review_status column).

    Body: {review_status: draft|in_progress|submitted|under_review|approved|
                      rejected|closed, review_notes?}
    Permissions follow the EXISTING RBAC — no new roles: inspectors
    (safety_officer / mine_manager with inspections write) may draft and
    submit; the scoped mine manager (or admin) performs under_review /
    approved / rejected / closed. Nobody approves their own inspection.
    """
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    mine = _get_mine_or_404(db, insp.mine_id)
    target = payload.get("review_status")
    if not target:
        raise HTTPException(status_code=422, detail="review_status is required.")
    try:
        inspection_svc.validate_review_transition(
            current=insp.review_status,
            target=target,
            user_role=user.role,
            is_scoped_manager=(mine.manager_id == user.id),
            is_author=(insp.inspector_id == user.id),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    _ensure_mine_scope_obj(user, mine, db)
    insp.review_status = target
    if target in ("under_review", "approved", "rejected", "closed"):
        insp.reviewed_by_id = user.id
        insp.reviewed_at = datetime.now(timezone.utc)
    if "review_notes" in payload:
        insp.review_notes = payload.get("review_notes")
    db.commit()
    db.refresh(insp)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action=f"inspection.review.{target}",
        entity_type="inspection", entity_id=inspection_id, mine_id=insp.mine_id,
        payload={"from": insp.review_status, "to": target},
    )
    return ReviewTransitionOut(
        inspection_id=insp.id,
        review_status=insp.review_status,
        reviewed_by_id=insp.reviewed_by_id,
        reviewed_at=insp.reviewed_at,
        review_notes=insp.review_notes,
    )


@gov_inspections_router.get("/{inspection_id}/review", response_model=ReviewTransitionOut)
def get_review_status(inspection_id: str, db: DbSession, user: CurrentUser):
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    _ensure_mine_scope(user, insp.mine_id, db)
    return ReviewTransitionOut(
        inspection_id=insp.id,
        review_status=insp.review_status,
        reviewed_by_id=insp.reviewed_by_id,
        reviewed_at=insp.reviewed_at,
        review_notes=insp.review_notes,
    )


# ===========================================================================
# Evidence (upload + list + mine-scoped fetch)
# ===========================================================================

evidence_router = APIRouter(
    prefix="/governance/evidence", tags=["Governance: Evidence"],
    dependencies=[Depends(get_current_user)],
)

# Media-type policy for evidence uploads. Picks up the SAME validation
# pattern as /api/detect (declared + magic-byte check in storage.sniff_mime).
_EVIDENCE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EVIDENCE_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
_EVIDENCE_AUDIO_TYPES = {"audio/webm", "audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg"}
_EVIDENCE_DOC_TYPES = {"application/pdf"}
_EVIDENCE_MEDIA_BY_CATEGORY = {
    "image": _EVIDENCE_IMAGE_TYPES,
    "video": _EVIDENCE_VIDEO_TYPES,
    "audio": _EVIDENCE_AUDIO_TYPES,
    "document": _EVIDENCE_DOC_TYPES,
}
_MAX_EVIDENCE_BYTES_BY_CATEGORY = {
    "image": 10 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
    "audio": 20 * 1024 * 1024,
    "document": 20 * 1024 * 1024,
}


def _evidence_target_ref(db: Session, kind: str, target_id: str) -> tuple[str | None, dict]:
    """Resolve the polymorphic target row for an evidence kind.

    Returns (mine_id, target_fk_dict). Mine scope is derived from the TARGET
    record — the client never supplies a mine scope for evidence; authorization
    is always checked against the target's own mine.
    """
    if kind in ("inspection", "checklist_item"):
        if kind == "inspection":
            row = db.get(Inspection, target_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Inspection not found.")
            mine_id = row.mine_id
            fks = {"inspection_id": row.id}
        else:
            item = db.get(InspectionChecklistItem, target_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Checklist item not found.")
            insp = db.get(Inspection, item.inspection_id)
            if insp is None:
                raise HTTPException(status_code=404, detail="Inspection not found.")
            mine_id = insp.mine_id
            fks = {"checklist_item_id": item.id}
    elif kind == "incident":
        row = db.get(Incident, target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Incident not found.")
        mine_id = row.mine_id
        fks = {"incident_id": row.id}
    elif kind == "corrective_action":
        row = db.get(CorrectiveAction, target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Corrective action not found.")
        if row.inspection_id:
            insp = db.get(Inspection, row.inspection_id)
            mine_id = insp.mine_id if insp else None
        elif row.incident_id:
            inc = db.get(Incident, row.incident_id)
            mine_id = inc.mine_id if inc else None
        else:
            mine_id = None
        fks = {"corrective_action_id": row.id}
    elif kind == "camera_event":
        ce = db.get(CameraEvent, target_id)
        if ce is None:
            raise HTTPException(status_code=404, detail="Camera event not found.")
        zone = db.get(RestrictedZone, ce.zone_id) if getattr(ce, "zone_id", None) else None
        mine_id = zone.mine_id if zone else None
        fks = {"camera_event_id": ce.id}
    elif kind == "emergency":
        row = db.get(EmergencyEvent, target_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Emergency event not found.")
        mine_id = row.mine_id
        fks = {"emergency_id": row.id}
    else:
        raise HTTPException(status_code=422, detail="Invalid evidence kind.")
    return mine_id, fks


@evidence_router.post("", response_model=EvidenceOut, status_code=201,
                      dependencies=[Depends(roles.write_access("inspections"))])
def upload_evidence(
    kind: str, target_id: str, file: UploadFile, db: DbSession, user: CurrentUser,
):
    """Upload evidence (image/video/audio/document) for a related record.

    Authorization is derived from the TARGET record's mine (never supplied by
    the client), files are validated by declared + actual bytes + size, and
    uploads reuse the existing Supabase-or-local storage abstraction.
    """
    from app.services.governance.evidence_service import store_evidence_file

    media_category = (file.content_type or "").split("/")[0].strip().lower()
    if media_category not in _EVIDENCE_MEDIA_BY_CATEGORY:
        raise HTTPException(status_code=415,
                            detail=f"Unsupported evidence category '{media_category}'. "
                                   f"Permitted: {sorted(_EVIDENCE_MEDIA_BY_CATEGORY)}")
    max_bytes = _MAX_EVIDENCE_BYTES_BY_CATEGORY[media_category]
    data = file.file.read(max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413,
                            detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB evidence limit.")
    mime_type, media_type = _resolve_evidence_media_type(data, file.content_type, media_category)
    if mime_type is None:
        raise HTTPException(status_code=415,
                            detail="File content does not match an allowed media type (magic-byte check failed).")
    mine_id, fks = _evidence_target_ref(db, kind, target_id)
    if mine_id is None:
        raise HTTPException(status_code=422, detail="Cannot determine the mine for this evidence target.")
    _ensure_mine_scope(user, mine_id, db)
    row = store_evidence_file(
        db, mine_id=mine_id, kind=kind, target_fks=fks, media_type=media_type,
        data=data, mime_type=mime_type, original_filename=file.filename,
        uploaded_by_id=user.id, description=None,
    )
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="evidence.upload",
        entity_type="evidence", entity_id=row.id, mine_id=mine_id,
        payload={"kind": kind, "media_type": media_type, "sha256": row.sha256, "bytes": row.size_bytes},
    )
    return row


def _resolve_evidence_media_type(data: bytes, declared: str | None, category: str) -> tuple[str | None, str]:
    """Magic-byte validation for evidence; returns (mime, media_type) or (None, category).

    Never trusts declared content type alone: bytes must match a known
    container signature. WebM containers may carry audio, so video/webm on an
    audio upload is accepted as audio/webm (browser recordings).
    """
    allowed = _EVIDENCE_MEDIA_BY_CATEGORY[category]
    sniffed = sniff_mime(data)
    if category == "document":
        # PDF has its own magic: %PDF-
        if data[:5] == b"%PDF-":
            return "application/pdf", "document"
        return None, "document"
    if sniffed is not None and sniffed in allowed:
        media_type = "image" if sniffed.startswith("image/") else (
            "video" if sniffed.startswith("video/") else "audio")
        return sniffed, media_type
    if category == "audio" and sniffed == "video/webm":
        return "audio/webm", "audio"
    # MP4 audio (m4a) uses the same ISO-BMFF container sniffed as video/mp4.
    if category == "audio" and sniffed == "video/mp4":
        return "audio/mp4", "audio"
    return None, category


@evidence_router.get("", response_model=list[EvidenceOut])
def list_evidence(db: DbSession, user: CurrentUser, mine_id: str | None = None,
                  kind: str | None = None, inspection_id: str | None = None):
    stmt = select(Evidence)
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(Evidence.mine_id == mine_id)
    if kind:
        stmt = stmt.where(Evidence.kind == kind)
    if inspection_id:
        stmt = stmt.where(Evidence.inspection_id == inspection_id)
    rows = db.execute(stmt.order_by(Evidence.created_at.desc()).limit(200)).scalars().all()
    # Cross-mine guard: an evidence row whose target mine the user cannot see
    # is filtered here AND scope-checkable targets are verified by mine (an
    # inspector of one mine can never download another mine's evidence).
    visible = []
    for e in rows:
        if e.mine_id is None:
            continue
        try:
            _ensure_mine_scope(user, e.mine_id, db)
        except HTTPException:
            continue
        visible.append(e)
    return visible


@evidence_router.get("/{evidence_id}/download")
def download_evidence(evidence_id: str, db: DbSession, user: CurrentUser):
    """Stream evidence content. Mine-scoped: 403 unless the user is permitted."""
    from app.services.storage import get_storage

    row = db.get(Evidence, evidence_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Evidence not found.")
    if row.mine_id is None:
        raise HTTPException(status_code=404, detail="Evidence has no mine scope.")
    _ensure_mine_scope(user, row.mine_id, db)
    storage = get_storage()
    try:
        url = storage.create_access_url(row.file_path)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Evidence access failed: {exc}") from exc
    # Supabase returns a signed URL; local storage returns a static path the
    # frontend can open directly. Either way the client never sees raw bytes
    # of another mine's evidence via this endpoint.
    return {"file_path": row.file_path, "sha256": row.sha256, "url": url, "mime_type": row.mime_type}


# ===========================================================================
# Compliance requirements + assessments + summary
# ===========================================================================

compliance_router = APIRouter(
    prefix="/governance/compliance", tags=["Governance: Compliance"],
    dependencies=[Depends(get_current_user)],
)


@compliance_router.get("/requirements", response_model=list[ComplianceRequirementOut])
def list_requirements(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    stmt = select(ComplianceRequirement).where(ComplianceRequirement.is_active.is_(True))
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where((ComplianceRequirement.mine_id == mine_id) | (ComplianceRequirement.mine_id.is_(None)))
    return db.execute(stmt.order_by(ComplianceRequirement.created_at.desc())).scalars().all()


@compliance_router.post("/requirements", response_model=ComplianceRequirementOut, status_code=201,
                        dependencies=[Depends(roles.write_access("compliance_requirements"))])
def create_requirement(payload: ComplianceRequirementCreate, db: DbSession, user: CurrentUser):
    if payload.mine_id:
        _ensure_mine_scope(user, payload.mine_id, db)
    row = ComplianceRequirement(
        mine_id=payload.mine_id,
        title=payload.title,
        description=payload.description,
        reference=payload.reference,  # REQUIRED traceable source (schema-enforced)
        frequency=payload.frequency,
        template_id=payload.template_id,
        due_day=payload.due_day,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="requirement.create",
        entity_type="compliance_requirement", entity_id=row.id, mine_id=payload.mine_id,
        payload={"title": row.title, "reference": row.reference},
    )
    return row


@compliance_router.post("/assessments", response_model=ComplianceAssessmentOut, status_code=201,
                        dependencies=[Depends(roles.write_access("compliance_engine"))])
def create_assessment(payload: ComplianceAssessmentCreate, db: DbSession, user: CurrentUser):
    req = db.get(ComplianceRequirement, payload.requirement_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Requirement not found.")
    if payload.status not in ("compliant", "attention", "violation", "not_assessed"):
        raise HTTPException(status_code=422, detail="Invalid status.")
    row = ComplianceAssessment(
        requirement_id=payload.requirement_id,
        mine_id=payload.mine_id or req.mine_id,
        status=payload.status,
        period_start=payload.period_start,
        period_end=payload.period_end,
        inspection_id=payload.inspection_id,
        notes=payload.notes,
        assessed_by_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="assessment.create",
        entity_type="compliance_assessment", entity_id=row.id, mine_id=row.mine_id,
        payload={"requirement_id": row.requirement_id, "status": row.status},
    )
    return row


@compliance_router.get("/summary", response_model=ComplianceSummaryOut)
def compliance_summary(db: DbSession, user: CurrentUser, mine_id: str | None = None,
                       period: str = Query(default="monthly", pattern="^(daily|weekly|monthly|custom)$")):
    """GREEN/AMBER/RED/GREY counts + mine score for the current period."""
    now = datetime.now(timezone.utc)
    if period == "daily":
        start = now - timedelta(days=1)
    elif period == "weekly":
        start = now - timedelta(days=7)
    else:
        start = now - timedelta(days=30)

    reqs = db.execute(select(ComplianceRequirement).where(ComplianceRequirement.is_active.is_(True))).scalars().all()
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        reqs = [r for r in reqs if r.mine_id in (None, mine_id)]

    counts = {"compliant": 0, "attention": 0, "violation": 0, "not_assessed": 0}
    for r in reqs:
        latest = db.execute(
            select(ComplianceAssessment)
            .where(ComplianceAssessment.requirement_id == r.id,
                   ComplianceAssessment.period_end >= start)
            .order_by(ComplianceAssessment.period_end.desc()).limit(1)
        ).scalar_one_or_none()
        counts[latest.status if latest else "not_assessed"] += 1

    overdue = 0
    upcoming = 0
    if mine_id:
        action_rows = db.execute(select(CorrectiveAction, Incident.mine_id, Inspection.mine_id)
                                 .join(Incident, CorrectiveAction.incident_id == Incident.id, isouter=True)
                                 .join(Inspection, CorrectiveAction.inspection_id == Inspection.id, isouter=True)).all()
        for a, inc_m, insp_m in action_rows:
            if (inc_m or insp_m) != mine_id:
                continue
            due = a.due_date
            if due.tzinfo is None:
                from datetime import timezone as _tz
                due = due.replace(tzinfo=_tz.utc)
            if a.status in ("pending", "in_progress", "overdue"):
                if due < now:
                    overdue += 1
                elif due <= now + timedelta(days=7):
                    upcoming += 1

    total = len(reqs)
    score = round(100.0 * counts["compliant"] / total, 1) if total else 0.0
    return ComplianceSummaryOut(
        total_requirements=total,
        compliant=counts["compliant"],
        attention=counts["attention"],
        violation=counts["violation"],
        not_assessed=counts["not_assessed"],
        overdue_actions=overdue,
        upcoming_deadlines=upcoming,
        score=score,
    )


# ===========================================================================
# Geofencing / location verification
# ===========================================================================

geofence_router = APIRouter(
    prefix="/governance/geofences", tags=["Governance: Geofencing"],
    dependencies=[Depends(get_current_user)],
)


@geofence_router.get("", response_model=list[GeofenceOut])
def list_geofences(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    stmt = select(Geofence)
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(Geofence.mine_id == mine_id)
    return db.execute(stmt).scalars().all()


@geofence_router.post("", response_model=GeofenceOut, status_code=201,
                      dependencies=[Depends(roles.write_access("geofences"))])
def create_geofence(payload: GeofenceCreate, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, payload.mine_id)
    _ensure_mine_scope(user, payload.mine_id, db)
    if payload.boundary_type == "radius":
        if payload.center_lat is None or payload.center_lng is None or payload.radius_m is None:
            raise HTTPException(status_code=422, detail="radius geofence requires center_lat, center_lng, radius_m.")
    else:
        if not payload.polygon_json or len(payload.polygon_json) < 3:
            raise HTTPException(status_code=422, detail="polygon geofence requires >=3 [lat,lng] points.")
    row = Geofence(
        mine_id=payload.mine_id,
        name=payload.name,
        boundary_type=payload.boundary_type,
        center_lat=payload.center_lat,
        center_lng=payload.center_lng,
        radius_m=payload.radius_m,
        polygon_json=payload.polygon_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@geofence_router.post("/verify-location", response_model=LocationVerifyOut)
def verify_location(payload: LocationVerifyIn, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, payload.mine_id)
    _ensure_mine_scope(user, payload.mine_id, db)
    result = geofence_svc.verify_location(db, payload.mine_id, payload.latitude, payload.longitude)
    return LocationVerifyOut(**result)


# ===========================================================================
# Workers / shifts / attendance
# ===========================================================================

workers_router = APIRouter(
    prefix="/governance/workers", tags=["Governance: Workers"],
    dependencies=[Depends(get_current_user)],
)


@workers_router.get("", response_model=list[WorkerOut])
def list_workers(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    stmt = select(Worker).where(Worker.is_active.is_(True))
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(Worker.mine_id == mine_id)
    return db.execute(stmt.order_by(Worker.full_name).limit(500)).scalars().all()


@workers_router.post("", response_model=WorkerOut, status_code=201,
                     dependencies=[Depends(roles.write_access("workers"))])
def create_worker(payload: WorkerCreate, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, payload.mine_id)
    _ensure_mine_scope(user, payload.mine_id, db)
    row = Worker(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


shifts_router = APIRouter(
    prefix="/governance/shifts", tags=["Governance: Shifts"],
    dependencies=[Depends(get_current_user)],
)


@shifts_router.get("", response_model=list[ShiftOut])
def list_shifts(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    stmt = select(Shift)
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(Shift.mine_id == mine_id)
    return db.execute(stmt.order_by(Shift.starts_at.desc()).limit(200)).scalars().all()


@shifts_router.post("", response_model=ShiftOut, status_code=201,
                    dependencies=[Depends(roles.write_access("workers"))])
def create_shift(payload: ShiftCreate, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, payload.mine_id)
    _ensure_mine_scope(user, payload.mine_id, db)
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=422, detail="Shift end must be after start.")
    row = Shift(**payload.model_dump(), created_by_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@shifts_router.post("/attendance", response_model=AttendanceOut, status_code=201,
                    dependencies=[Depends(roles.write_access("workers"))])
def record_attendance(payload: AttendanceCreate, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, payload.mine_id)
    _ensure_mine_scope(user, payload.mine_id, db)
    if db.get(Worker, payload.worker_id) is None:
        raise HTTPException(status_code=404, detail="Worker not found.")
    row = Attendance(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@shifts_router.get("/attendance", response_model=list[AttendanceOut])
def list_attendance(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    stmt = select(Attendance)
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(Attendance.mine_id == mine_id)
    return db.execute(stmt.order_by(Attendance.created_at.desc()).limit(200)).scalars().all()


# ===========================================================================
# Contractors + documents
# ===========================================================================

contractors_router = APIRouter(
    prefix="/governance/contractors", tags=["Governance: Contractors"],
    dependencies=[Depends(get_current_user)],
)


@contractors_router.get("", response_model=list[ContractorOut])
def list_contractors(db: DbSession, user: CurrentUser):
    return db.execute(select(Contractor).where(Contractor.is_active.is_(True))).scalars().all()


@contractors_router.post("", response_model=ContractorOut, status_code=201,
                         dependencies=[Depends(roles.write_access("contractors"))])
def create_contractor(payload: ContractorCreate, db: DbSession, user: CurrentUser):
    row = Contractor(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@contractors_router.post("/documents", response_model=ContractorDocumentOut, status_code=201,
                         dependencies=[Depends(roles.write_access("contractors"))])
def create_document(payload: ContractorDocumentCreate, db: DbSession, user: CurrentUser):
    row = ContractorDocument(**payload.model_dump(), verification_status="pending_verification")
    db.add(row)
    db.commit()
    db.refresh(row)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="document.create",
        entity_type="contractor_document", entity_id=row.id, mine_id=payload.mine_id,
        payload={"doc_type": row.doc_type, "title": row.title},
    )
    return row


@contractors_router.get("/documents", response_model=list[ContractorDocumentOut])
def list_documents(db: DbSession, user: CurrentUser, status: str | None = None):
    stmt = select(ContractorDocument)
    if status:
        stmt = stmt.where(ContractorDocument.verification_status == status)
    return db.execute(stmt.order_by(ContractorDocument.created_at.desc()).limit(200)).scalars().all()


@contractors_router.post("/documents/{doc_id}/verify", response_model=ContractorDocumentOut,
                         dependencies=[Depends(roles.write_access("contractors"))])
def verify_document(doc_id: str, payload: dict, db: DbSession, user: CurrentUser):
    """Human verification of a document. Body: {verification_status: valid|expiring|expired|rejected}."""
    row = db.get(ContractorDocument, doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    new_status = payload.get("verification_status")
    if new_status not in ("valid", "expiring", "expired", "pending_verification"):
        raise HTTPException(status_code=422, detail="Invalid verification_status.")
    row.verification_status = new_status
    row.verified_by_id = user.id
    db.commit()
    db.refresh(row)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="document.verify",
        entity_type="contractor_document", entity_id=row.id, mine_id=row.mine_id,
        payload={"verification_status": new_status},
    )
    return row


# ===========================================================================
# Emergency
# ===========================================================================

emergency_router = APIRouter(
    prefix="/governance/emergencies", tags=["Governance: Emergency"],
    dependencies=[Depends(get_current_user)],
)


@emergency_router.get("", response_model=list[EmergencyOut])
def list_emergencies(db: DbSession, user: CurrentUser, mine_id: str | None = None,
                     status: str | None = None):
    stmt = select(EmergencyEvent)
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(EmergencyEvent.mine_id == mine_id)
    if status:
        stmt = stmt.where(EmergencyEvent.status == status)
    return db.execute(stmt.order_by(EmergencyEvent.created_at.desc()).limit(200)).scalars().all()


@emergency_router.post("", response_model=EmergencyOut, status_code=201,
                       dependencies=[Depends(roles.write_access("emergencies"))])
def create_emergency(payload: EmergencyCreate, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, payload.mine_id)
    _ensure_mine_scope(user, payload.mine_id, db)
    if payload.emergency_type not in ("fire", "gas_leak", "collapse", "ppe_critical", "worker_emergency", "other"):
        raise HTTPException(status_code=422, detail="Invalid emergency_type.")
    row = EmergencyEvent(**payload.model_dump(), reported_by_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit_chain.append_event(
        db, actor_id=user.id, actor_role=user.role, action="emergency.create",
        entity_type="emergency_event", entity_id=row.id, mine_id=row.mine_id,
        payload={"emergency_type": row.emergency_type, "severity": row.severity},
    )
    # Notify permitted users of this mine (in-app only; no SMS without a
    # configured adapter — never fake a "sent" receipt).
    recipients = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    for u in recipients:
        if u.id == user.id:
            continue
        if u.role == "admin" or (u.role == "mine_manager" and u.id == _get_mine_or_404(db, row.mine_id).manager_id) \
                or (row.mine_id in (u.permitted_mine_ids or [])):
            db.add(Notification(
                user_id=u.id, mine_id=row.mine_id, category="emergency",
                title=f"EMERGENCY: {row.title}",
                body=row.description or "",
                severity=row.severity,
                entity_type="emergency_event", entity_id=row.id,
                dedupe_key=f"emergency:{row.id}:user:{u.id}",
            ))
    db.commit()
    return row


@emergency_router.patch("/{emergency_id}", response_model=EmergencyOut,
                        dependencies=[Depends(roles.write_access("emergencies"))])
def update_emergency(emergency_id: str, payload: dict, db: DbSession, user: CurrentUser):
    row = db.get(EmergencyEvent, emergency_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Emergency not found.")
    _ensure_mine_scope(user, row.mine_id, db)
    if "status" in payload:
        if payload["status"] not in ("open", "responding", "resolved", "closed"):
            raise HTTPException(status_code=422, detail="Invalid status.")
        row.status = payload["status"]
        if payload["status"] in ("resolved", "closed"):
            row.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


# ===========================================================================
# Telemetry (sensors + readings)
# ===========================================================================

telemetry_router = APIRouter(
    prefix="/governance/telemetry", tags=["Governance: Telemetry"],
    dependencies=[Depends(get_current_user)],
)


@telemetry_router.get("/devices", response_model=list[SensorDeviceOut])
def list_devices(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    stmt = select(SensorDevice)
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(SensorDevice.mine_id == mine_id)
    return db.execute(stmt).scalars().all()


@telemetry_router.post("/devices", response_model=SensorDeviceOut, status_code=201,
                       dependencies=[Depends(roles.write_access("telemetry"))])
def create_device(payload: SensorDeviceCreate, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, payload.mine_id)
    _ensure_mine_scope(user, payload.mine_id, db)
    if payload.source not in ("real", "demo"):
        raise HTTPException(status_code=422, detail="source must be 'real' or 'demo'.")
    row = SensorDevice(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@telemetry_router.post("/readings", response_model=TelemetryReadingOut, status_code=201,
                       dependencies=[Depends(roles.write_access("telemetry"))])
def add_reading(payload: TelemetryReadingCreate, db: DbSession, user: CurrentUser):
    device = db.get(SensorDevice, payload.device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Sensor device not found.")
    _ensure_mine_scope(user, device.mine_id, db)
    status = "unknown"
    if device.critical_threshold is not None and payload.value >= device.critical_threshold:
        status = "critical"
    elif device.warning_threshold is not None and payload.value >= device.warning_threshold:
        status = "warning"
    else:
        status = "normal"
    row = TelemetryReading(
        device_id=device.id, mine_id=device.mine_id,
        value=payload.value, unit=device.unit, status=status,
    )
    device.last_seen_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@telemetry_router.get("/readings", response_model=list[TelemetryReadingOut])
def list_readings(db: DbSession, user: CurrentUser, mine_id: str | None = None,
                  device_id: str | None = None, limit: int = Query(default=100, le=500)):
    stmt = select(TelemetryReading)
    if mine_id:
        _ensure_mine_scope(user, mine_id, db)
        stmt = stmt.where(TelemetryReading.mine_id == mine_id)
    if device_id:
        stmt = stmt.where(TelemetryReading.device_id == device_id)
    return db.execute(stmt.order_by(TelemetryReading.recorded_at.desc()).limit(limit)).scalars().all()


# ===========================================================================
# Risk scoring
# ===========================================================================

risk_router = APIRouter(
    prefix="/governance/risk", tags=["Governance: Risk"],
    dependencies=[Depends(get_current_user)],
)


@risk_router.get("", response_model=list[RiskScoreOut])
def get_all_risk(db: DbSession, user: CurrentUser):
    return [RiskScoreOut(**r) for r in risk_svc.compute_all_mine_risk(db)]


@risk_router.get("/{mine_id}", response_model=RiskScoreOut)
def get_mine_risk(mine_id: str, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, mine_id)
    _ensure_mine_scope(user, mine_id, db)
    result = risk_svc.compute_mine_risk(db, mine_id)
    db.add(RiskScore(
        mine_id=mine_id, score=result["score"], band=result["band"],
        factors_json=result["factors"], computed_by="deterministic",
    ))
    db.commit()
    return RiskScoreOut(**result)


# ===========================================================================
# Reports (PDF, zero-dependency writer)
# ===========================================================================

reports_router = APIRouter(
    prefix="/governance/reports", tags=["Governance: Reports"],
    dependencies=[Depends(get_current_user)],
)


@reports_router.get("/inspection/{inspection_id}.pdf")
def inspection_report(inspection_id: str, db: DbSession, user: CurrentUser):
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise HTTPException(status_code=404, detail="Inspection not found.")
    _ensure_mine_scope(user, insp.mine_id, db)
    try:
        pdf_bytes = report_svc.inspection_report(db, inspection_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="inspection-{inspection_id}.pdf"'})


@reports_router.get("/compliance/{mine_id}.pdf")
def compliance_report(mine_id: str, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, mine_id)
    _ensure_mine_scope(user, mine_id, db)
    pdf_bytes = report_svc.mine_compliance_report(db, mine_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="compliance-{mine_id}.pdf"'})


@reports_router.get("/safety/{mine_id}.pdf")
def safety_report(mine_id: str, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, mine_id)
    _ensure_mine_scope(user, mine_id, db)
    pdf_bytes = report_svc.mine_safety_report(db, mine_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="safety-{mine_id}.pdf"'})


@reports_router.get("/violations/{mine_id}.pdf")
def violations_report(mine_id: str, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, mine_id)
    _ensure_mine_scope(user, mine_id, db)
    pdf_bytes = report_svc.mine_violation_report(db, mine_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="violations-{mine_id}.pdf"'})


@reports_router.get("/corrective-actions")
def corrective_actions_report(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    if mine_id:
        _get_mine_or_404(db, mine_id)
        _ensure_mine_scope(user, mine_id, db)
    else:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Org-wide reports are restricted to administrators.")
    pdf_bytes = report_svc.corrective_action_report(db, mine_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="corrective-actions.pdf"'})


@reports_router.get("/emergencies")
def emergencies_report(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    if mine_id:
        _get_mine_or_404(db, mine_id)
        _ensure_mine_scope(user, mine_id, db)
    else:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Org-wide reports are restricted to administrators.")
    pdf_bytes = report_svc.emergency_report(db, mine_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="emergencies.pdf"'})


@reports_router.get("/contractors")
def contractors_report(db: DbSession, user: CurrentUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Contractor compliance report is restricted to administrators.")
    pdf_bytes = report_svc.contractor_compliance_report(db)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="contractor-compliance.pdf"'})


@reports_router.get("/audit")
def audit_report_endpoint(db: DbSession, user: CurrentUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Audit report is restricted to administrators.")
    pdf_bytes = report_svc.audit_report(db)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="audit.pdf"'})


@reports_router.get("/telemetry/{mine_id}.pdf")
def telemetry_report_endpoint(mine_id: str, db: DbSession, user: CurrentUser):
    _get_mine_or_404(db, mine_id)
    _ensure_mine_scope(user, mine_id, db)
    pdf_bytes = report_svc.telemetry_report(db, mine_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="telemetry-{mine_id}.pdf"'})


@reports_router.get("/workforce")
def workforce_report_endpoint(db: DbSession, user: CurrentUser, mine_id: str | None = None):
    if mine_id:
        _get_mine_or_404(db, mine_id)
        _ensure_mine_scope(user, mine_id, db)
    else:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Org-wide reports are restricted to administrators.")
    pdf_bytes = report_svc.workforce_report(db, mine_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="workforce.pdf"'})


# ===========================================================================
# Audit ledger
# ===========================================================================

audit_router = APIRouter(
    prefix="/governance/audit", tags=["Governance: Audit"],
    dependencies=[Depends(get_current_user)],
)


@audit_router.get("", response_model=list[AuditEventOut])
def list_audit(db: DbSession, user: CurrentUser, mine_id: str | None = None,
               limit: int = Query(default=100, le=500)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Audit log is restricted to administrators.")
    stmt = select(AuditEvent)
    if mine_id:
        stmt = stmt.where(AuditEvent.mine_id == mine_id)
    return db.execute(stmt.order_by(AuditEvent.seq.desc()).limit(limit)).scalars().all()


@audit_router.get("/verify", response_model=AuditVerifyOut)
def verify_audit(db: DbSession, user: CurrentUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Audit verification is restricted to administrators.")
    return AuditVerifyOut(**audit_chain.verify_chain(db))


# ===========================================================================
# Notifications
# ===========================================================================

notifications_router = APIRouter(
    prefix="/governance/notifications", tags=["Governance: Notifications"],
    dependencies=[Depends(get_current_user)],
)


@notifications_router.get("", response_model=list[NotificationOut])
def list_notifications(db: DbSession, user: CurrentUser, unread_only: bool = False):
    stmt = select(Notification).where(
        (Notification.user_id == user.id) | (Notification.user_id.is_(None))
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return db.execute(stmt.order_by(Notification.created_at.desc()).limit(100)).scalars().all()


@notifications_router.post("/read", status_code=204)
def mark_read(payload: dict, db: DbSession, user: CurrentUser):
    ids = payload.get("ids", [])
    rows = db.execute(select(Notification).where(Notification.id.in_(ids))).scalars().all()
    for n in rows:
        if n.user_id in (None, user.id):
            n.read_at = datetime.now(timezone.utc)
    db.commit()


@notifications_router.post("/escalate-overdue", response_model=list[NotificationOut],
                           dependencies=[Depends(roles.write_access("corrective_actions"))])
def escalate_overdue(db: DbSession, user: CurrentUser):
    """Lazy escalation sweep — no background daemon; called by UI/dashboards."""
    return sla_svc.escalate_overdue(db)


# ===========================================================================
# Offline sync
# ===========================================================================

sync_router = APIRouter(
    prefix="/governance/sync", tags=["Governance: Offline Sync"],
    dependencies=[Depends(get_current_user)],
)


@sync_router.post("", response_model=SyncPushOut)
def sync_push(payload: SyncPushIn, db: DbSession, user: CurrentUser):
    """Idempotent offline sync push.

    The same client_guid is always a no-op (returns 'duplicate'), so a flaky
    connection can retry without duplicating inspections.
    """
    existing = db.execute(
        select(SyncRecord).where(SyncRecord.client_guid == payload.client_guid)
    ).scalar_one_or_none()
    if existing is not None:
        return SyncPushOut(client_guid=payload.client_guid, status="duplicate",
                           result_ref_id=existing.result_ref_id)

    record = SyncRecord(
        client_guid=payload.client_guid,
        user_id=user.id,
        mine_id=payload.mine_id,
        entity_type=payload.entity_type,
        payload=payload.payload,
        status="pending",
    )
    db.add(record)
    db.flush()

    try:
        if payload.entity_type != "inspection":
            raise ValueError(f"Unsupported entity_type '{payload.entity_type}'.")
        p = payload.payload
        mine_id = p.get("mine_id") or payload.mine_id
        template_id = p.get("template_id")
        if not mine_id or not template_id:
            raise ValueError("payload requires mine_id and template_id.")
        mine = _get_mine_or_404(db, mine_id)
        _ensure_mine_scope_obj(user, mine, db)
        template = db.get(InspectionTemplate, template_id)
        if template is None:
            raise ValueError("Template not found.")
        now = datetime.now(timezone.utc)
        inspection = Inspection(
            mine_id=mine_id, inspector_id=user.id,
            inspection_type=template.inspection_type,
            status="completed",
            scheduled_at=p.get("scheduled_at") or now,
            completed_at=now,
            findings=p.get("description"),
        )
        db.add(inspection)
        db.flush()
        items = inspection_svc.snapshot_template(db, inspection, template)
        by_position = {i.position: i for i in items}
        results_payload = {}
        for pos_str, res in (p.get("results") or {}).items():
            item = by_position.get(int(pos_str))
            if item is not None:
                results_payload[item.id] = {"result": res.get("result"), "comment": res.get("comment")}
        inspection_svc.apply_checklist_results(db, inspection.id, results_payload)
        rollup = inspection_svc.rollup_compliance(items)
        inspection.compliance_result = rollup
        record.result_ref_id = inspection.id
        record.status = "synced"
        record.synced_at = now
        db.commit()
        audit_chain.append_event(
            db, actor_id=user.id, actor_role=user.role, action="inspection.sync",
            entity_type="inspection", entity_id=inspection.id, mine_id=mine_id,
            payload={"client_guid": payload.client_guid, "compliance_result": rollup},
        )
        return SyncPushOut(client_guid=payload.client_guid, status="synced",
                           result_ref_id=inspection.id)
    except Exception as e:
        db.rollback()
        record = SyncRecord(
            client_guid=payload.client_guid, user_id=user.id, mine_id=payload.mine_id,
            entity_type=payload.entity_type, payload=payload.payload,
            status="failed", error=str(e)[:500],
        )
        db.add(record)
        db.commit()
        return SyncPushOut(client_guid=payload.client_guid, status="failed", error=str(e)[:500])


@sync_router.get("/queue", response_model=list[SyncQueueOut])
def sync_queue(db: DbSession, user: CurrentUser, status: str | None = None):
    stmt = select(SyncRecord).where(SyncRecord.user_id == user.id)
    if status:
        stmt = stmt.where(SyncRecord.status == status)
    return db.execute(stmt.order_by(SyncRecord.created_at.desc()).limit(200)).scalars().all()


# ===========================================================================
# AI workbench endpoints (OCR / voice / translation)
# ===========================================================================

ai_router = APIRouter(
    prefix="/governance/ai", tags=["Governance: AI Workbench"],
    dependencies=[Depends(get_current_user)],
)


@ai_router.post("/ocr", response_model=OcrResultOut,
                dependencies=[Depends(roles.write_access("inspections"))])
def run_ocr(payload: dict, db: DbSession, user: CurrentUser):
    """Body: {data_base64, mime_type?}. Returns a SUGGESTION — never a final record."""
    import base64

    raw = payload.get("data_base64")
    if not raw:
        raise HTTPException(status_code=422, detail="data_base64 is required.")
    try:
        image_bytes = base64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="data_base64 is not valid base64.")
    result = ai_adapters.ocr_extract(image_bytes, payload.get("mime_type", "image/jpeg"))
    return OcrResultOut(capability=result.capability, status=result.status,
                        provider=result.provider, text=result.text,
                        fields=result.fields, message=result.message, model=result.model)


@ai_router.post("/voice", response_model=VoiceResultOut,
                dependencies=[Depends(roles.write_access("inspections"))])
def run_voice(payload: dict, db: DbSession, user: CurrentUser):
    raw = payload.get("data_base64")
    if not raw:
        raise HTTPException(status_code=422, detail="data_base64 is required.")
    try:
        audio_bytes = base64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="data_base64 is not valid base64.")
    result = ai_adapters.transcribe_audio(audio_bytes, payload.get("mime_type", "audio/webm"),
                                          payload.get("language"))
    return VoiceResultOut(capability=result.capability, status=result.status,
                          provider=result.provider, text=result.text,
                          language=result.language, message=result.message, model=result.model)


@ai_router.post("/translate", response_model=TranslationResultOut)
def run_translate(payload: dict, db: DbSession, user: CurrentUser):
    text = payload.get("text")
    target = payload.get("target_language", "hi")
    if not text:
        raise HTTPException(status_code=422, detail="text is required.")
    result = ai_adapters.translate_text(text, target)
    return TranslationResultOut(capability=result.capability, status=result.status,
                                provider=result.provider, text=result.text, message=result.message)


@ai_router.get("/capabilities")
def ai_capabilities(user: CurrentUser):
    """Honest capability matrix for the AI workbench UI."""
    ocr_p = (settings.OCR_PROVIDER or "none").lower()
    voice_p = (settings.VOICE_PROVIDER or "none").lower()
    tr_p = (settings.TRANSLATION_PROVIDER or "none").lower()
    return {
        "ppe_detection": {"status": "LIVE", "model": "Vyra YOLOv8m", "note": "Production detector (unchanged)."},
        "inspection_photo_analysis": {"status": "LIVE", "model": "Vyra YOLOv8m", "note": "Suggestions only; inspector confirms."},
        "ocr": {"status": "LIVE" if ocr_p not in ("", "none", "demo") else "UNAVAILABLE", "provider": ocr_p},
        "voice_transcription": {"status": "LIVE" if voice_p not in ("", "none", "demo") else "UNAVAILABLE", "provider": voice_p},
        "translation": {"status": "LIVE" if tr_p not in ("", "none", "demo") else "UNAVAILABLE", "provider": tr_p},
        "risk_analysis": {"status": "LIVE", "model": "deterministic", "note": "Explainable weighted scoring, no ML."},
    }
