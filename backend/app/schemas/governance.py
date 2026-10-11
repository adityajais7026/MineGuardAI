"""Governance API schemas (Pydantic v2), following existing schema conventions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import PaginatedResponse

# ---------------------------------------------------------------------------
# Inspection templates
# ---------------------------------------------------------------------------


class TemplateItemIn(BaseModel):
    label: str = Field(min_length=1, max_length=500)
    description: str | None = None
    category: str = "general"
    result_options: str = "pass,fail,na,unknown"
    severity_weight: int = Field(default=5, ge=0, le=10)
    requires_evidence: bool = False


class InspectionTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    inspection_type: str = "safety"
    mine_id: str | None = None
    regulatory_reference: str | None = None
    items: list[TemplateItemIn] = Field(default_factory=list)


class InspectionTemplateItemOut(BaseModel):
    id: str
    position: int
    label: str
    description: str | None = None
    category: str
    result_options: str
    severity_weight: int
    requires_evidence: bool

    model_config = {"from_attributes": True}


class InspectionTemplateOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    inspection_type: str
    mine_id: str | None = None
    regulatory_reference: str | None = None
    is_active: bool
    created_at: datetime
    items: list[InspectionTemplateItemOut] = []

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Checklist items
# ---------------------------------------------------------------------------


class ChecklistItemOut(BaseModel):
    id: str
    inspection_id: str
    position: int
    label: str
    category: str
    result_options: str
    severity_weight: int
    result: str | None = None
    comment: str | None = None
    ai_suggestion: str | None = None
    ai_confidence: float | None = None
    ai_model: str | None = None

    model_config = {"from_attributes": True}


class ChecklistResultIn(BaseModel):
    result: str | None = None
    comment: str | None = None
    ai_suggestion: str | None = None
    ai_confidence: float | None = None
    ai_model: str | None = None


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class EvidenceOut(BaseModel):
    id: str
    mine_id: str | None = None
    kind: str
    inspection_id: str | None = None
    checklist_item_id: str | None = None
    incident_id: str | None = None
    corrective_action_id: str | None = None
    camera_event_id: str | None = None
    emergency_id: str | None = None
    media_type: str
    file_path: str
    original_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    description: str | None = None
    uploaded_by_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Inspection review / approval lifecycle
# ---------------------------------------------------------------------------


class ReviewTransitionOut(BaseModel):
    inspection_id: str
    review_status: str
    reviewed_by_id: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


class ComplianceRequirementCreate(BaseModel):
    mine_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    reference: str = Field(min_length=1, max_length=500)
    frequency: str = "monthly"
    template_id: str | None = None
    due_day: int | None = Field(default=None, ge=1, le=31)


class ComplianceRequirementOut(BaseModel):
    id: str
    mine_id: str | None = None
    title: str
    description: str | None = None
    reference: str
    frequency: str
    template_id: str | None = None
    due_day: int | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ComplianceAssessmentCreate(BaseModel):
    requirement_id: str
    mine_id: str | None = None
    status: str
    period_start: datetime
    period_end: datetime
    inspection_id: str | None = None
    notes: str | None = None


class ComplianceAssessmentOut(BaseModel):
    id: str
    requirement_id: str
    mine_id: str | None = None
    status: str
    period_start: datetime
    period_end: datetime
    inspection_id: str | None = None
    notes: str | None = None
    assessed_by_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ComplianceSummaryOut(BaseModel):
    """GREEN/AMBER/RED/GREY roll-up for a mine over a period."""

    total_requirements: int
    compliant: int
    attention: int
    violation: int
    not_assessed: int
    overdue_actions: int
    upcoming_deadlines: int
    score: float


# ---------------------------------------------------------------------------
# Geofencing
# ---------------------------------------------------------------------------


class GeofenceCreate(BaseModel):
    mine_id: str
    name: str = Field(min_length=1, max_length=255)
    boundary_type: str = "radius"
    center_lat: float | None = Field(default=None, ge=-90, le=90)
    center_lng: float | None = Field(default=None, ge=-180, le=180)
    radius_m: float | None = Field(default=None, gt=0)
    polygon_json: list[list[float]] | None = None


class GeofenceOut(BaseModel):
    id: str
    mine_id: str
    name: str
    boundary_type: str
    center_lat: float | None = None
    center_lng: float | None = None
    radius_m: float | None = None
    polygon_json: list | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class LocationVerifyIn(BaseModel):
    mine_id: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class LocationVerifyOut(BaseModel):
    status: str
    message: str | None = None
    geofence_id: str | None = None


# ---------------------------------------------------------------------------
# Workers / shifts / attendance / contractors / documents
# ---------------------------------------------------------------------------


class ContractorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None


class ContractorOut(BaseModel):
    id: str
    name: str
    contact_person: str | None = None
    phone: str | None = None
    email: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkerCreate(BaseModel):
    mine_id: str
    contractor_id: str | None = None
    employee_code: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=255)
    role: str | None = None
    phone: str | None = None


class WorkerOut(BaseModel):
    id: str
    mine_id: str
    contractor_id: str | None = None
    employee_code: str
    full_name: str
    role: str | None = None
    phone: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class ShiftCreate(BaseModel):
    mine_id: str
    name: str
    starts_at: datetime
    ends_at: datetime


class ShiftOut(BaseModel):
    id: str
    mine_id: str
    name: str
    starts_at: datetime
    ends_at: datetime

    model_config = {"from_attributes": True}


class AttendanceCreate(BaseModel):
    worker_id: str
    mine_id: str
    shift_id: str | None = None
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    verification: str = "manual"
    check_in_lat: float | None = None
    check_in_lng: float | None = None


class AttendanceOut(BaseModel):
    id: str
    shift_id: str | None = None
    worker_id: str
    mine_id: str
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    verification: str
    check_in_lat: float | None = None
    check_in_lng: float | None = None

    model_config = {"from_attributes": True}


class ContractorDocumentCreate(BaseModel):
    contractor_id: str | None = None
    worker_id: str | None = None
    mine_id: str | None = None
    doc_type: str
    title: str
    document_ref: str
    issued_on: datetime | None = None
    expires_on: datetime | None = None
    notes: str | None = None


class ContractorDocumentOut(BaseModel):
    id: str
    contractor_id: str | None = None
    worker_id: str | None = None
    mine_id: str | None = None
    doc_type: str
    title: str
    document_ref: str
    issued_on: datetime | None = None
    expires_on: datetime | None = None
    verification_status: str
    notes: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Emergency
# ---------------------------------------------------------------------------


class EmergencyCreate(BaseModel):
    mine_id: str
    emergency_type: str
    severity: str = "critical"
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_text: str | None = None


class EmergencyOut(BaseModel):
    id: str
    mine_id: str
    emergency_type: str
    severity: str
    status: str
    title: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_text: str | None = None
    reported_by_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


class SensorDeviceCreate(BaseModel):
    mine_id: str
    device_code: str
    parameter: str
    unit: str
    source: str = "demo"
    location_text: str | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None


class SensorDeviceOut(BaseModel):
    id: str
    mine_id: str
    device_code: str
    parameter: str
    unit: str
    source: str
    location_text: str | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    is_active: bool
    last_seen_at: datetime | None = None

    model_config = {"from_attributes": True}


class TelemetryReadingCreate(BaseModel):
    device_id: str
    value: float
    unit: str | None = None


class TelemetryReadingOut(BaseModel):
    id: str
    device_id: str
    mine_id: str
    value: float
    unit: str
    status: str
    recorded_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------


class RiskFactorOut(BaseModel):
    factor: str
    points: float
    detail: str


class RiskScoreOut(BaseModel):
    mine_id: str
    score: float
    band: str
    factors: list[RiskFactorOut]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditEventOut(BaseModel):
    id: str
    seq: int
    actor_id: str | None = None
    actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    mine_id: str | None = None
    payload_json: dict | None = None
    prev_hash: str | None = None
    event_hash: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditVerifyOut(BaseModel):
    valid: bool
    entries: int
    broken_at_seq: int | None = None
    reason: str | None = None
    head_hash: str | None = None


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationOut(BaseModel):
    id: str
    user_id: str | None = None
    mine_id: str | None = None
    category: str
    title: str
    body: str | None = None
    severity: str
    entity_type: str | None = None
    entity_id: str | None = None
    read_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Sync (offline-first)
# ---------------------------------------------------------------------------


class SyncPushIn(BaseModel):
    client_guid: str = Field(min_length=8, max_length=64)
    mine_id: str | None = None
    entity_type: str = "inspection"
    payload: dict


class SyncPushOut(BaseModel):
    client_guid: str
    status: str  # synced | duplicate | failed
    result_ref_id: str | None = None
    error: str | None = None


class SyncQueueOut(BaseModel):
    id: str
    client_guid: str
    mine_id: str | None = None
    entity_type: str
    status: str
    result_ref_id: str | None = None
    error: str | None = None
    synced_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# AI adapters (OCR / voice / translation)
# ---------------------------------------------------------------------------


class OcrResultOut(BaseModel):
    capability: str = "ocr"
    status: str
    provider: str
    text: str | None = None
    fields: dict = {}
    message: str | None = None
    model: str | None = None


class VoiceResultOut(BaseModel):
    capability: str = "voice"
    status: str
    provider: str
    text: str | None = None
    language: str | None = None
    message: str | None = None
    model: str | None = None


class TranslationResultOut(BaseModel):
    capability: str = "translation"
    status: str
    provider: str
    text: str | None = None
    message: str | None = None
