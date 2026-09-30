"""
SQLAlchemy ORM models for MineGuardAI.

Ten core tables plus users, with foreign keys, indexes, timestamps and
check constraints. Mirrors `database/schema.sql` (Supabase DDL).

NOTE: enum-like columns are stored as strings (validated at the Pydantic
layer) so the same models run on SQLite (dev) and PostgreSQL (Supabase).
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Users & auth
# --------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Roles: admin | mine_manager | safety_officer | environmental_officer
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="safety_officer")
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # When Supabase Auth is used, this links the row to auth.users.id.
    supabase_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    # Verified mobile number (E.164 without '+', e.g. 919999999999).
    # Required for MSG91 SMS OTP login; nullable so pre-existing rows stay valid.
    mobile: Mapped[str | None] = mapped_column(String(15), unique=True, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','mine_manager','safety_officer','environmental_officer')",
            name="ck_users_role",
        ),
    )


class OtpChallenge(Base):
    """Server-side OTP challenge for the MSG91 OTP Widget.

    MSG91's widget generates and validates the code with its default SMS
    configuration; we store only the opaque provider request id that the
    send call returns (never a code). `purpose` separates registration and
    login flows. Rows are consumed on success; expired rows are ignored and
    cleaned up opportunistically.
    """

    __tablename__ = "otp_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Registration challenges keyed by mobile; login challenges by user id.
    subject: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # register|login
    mobile: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    # Which OTP backend produced this challenge (future-proofing).
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="msg91_widget")
    # Opaque request id returned by MSG91's widget send call. Verified later
    # via /api/v5/widget/verifyOtp. No code is ever stored locally.
    provider_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts_left: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    attempts_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Rate-limiting window for sends ( resend cooldown + hourly cap ).
    first_requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the registration token minted from this challenge was used to
    # create the account (single-use guarantee for the registration flow).
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when MSG91 rejects the send or the cooldown/cap is hit (for support).
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("purpose IN ('register','login')", name="ck_otp_purpose"),
        Index("ix_otp_subject_purpose", "subject", "purpose"),
    )


class RoleInvitation(Base):
    """Admin-issued invitation for privileged roles (approval mechanism).

    Minted by an existing administrator for 'admin' or 'environmental_officer'
    (Government Officer) signups. Single-use, expiring, and consumed at
    registration. Codes are stored bcrypt-hashed.
    """

    __tablename__ = "role_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    role: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # admin|environmental_officer
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    invited_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional: bind the invitation to one email or mobile.
    bound_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    bound_mobile: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    used_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','environmental_officer')",
            name="ck_role_invitations_role",
        ),
    )


# --------------------------------------------------------------------------
# Mines
# --------------------------------------------------------------------------
class Mine(Base):
    __tablename__ = "mines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    # Types: open_cast | underground | mixed
    mine_type: Mapped[str] = mapped_column(String(20), nullable=False, default="open_cast")
    # Operating status: operational | maintenance | suspended | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="operational", index=True)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    manager_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    manager = relationship("User", foreign_keys=[manager_id])
    readings = relationship("EnvironmentalReading", back_populates="mine", cascade="all, delete-orphan")
    camera_events = relationship("CameraEvent", back_populates="mine", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="mine", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="mine", cascade="all, delete-orphan")
    inspections = relationship("Inspection", back_populates="mine", cascade="all, delete-orphan")
    zones = relationship("RestrictedZone", back_populates="mine", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("mine_type IN ('open_cast','underground','mixed')", name="ck_mines_type"),
        CheckConstraint("status IN ('operational','maintenance','suspended','closed')", name="ck_mines_status"),
    )


# --------------------------------------------------------------------------
# Compliance rules
# --------------------------------------------------------------------------
class ComplianceRule(Base):
    __tablename__ = "compliance_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Parameter this rule evaluates (pm2_5, pm10, noise, temperature, ...).
    parameter: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operator: Mapped[str] = mapped_column(String(10), nullable=False, default=">")
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    # Severity assigned to alerts raised by this rule.
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    mine_id: Mapped[str | None] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL -> applies to all mines
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("operator IN ('>','>=','<','<=')", name="ck_rules_operator"),
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_rules_severity"),
    )


# --------------------------------------------------------------------------
# Environmental readings
# --------------------------------------------------------------------------
class EnvironmentalReading(Base):
    __tablename__ = "environmental_readings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("compliance_rules.id", ondelete="SET NULL"), nullable=True
    )  # rule that adjudicated the reading (for traceability)
    parameter: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # status: normal | violation
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", index=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="simulated")  # simulated|sensor|external
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    mine = relationship("Mine", back_populates="readings")
    rule = relationship("ComplianceRule")

    __table_args__ = (
        CheckConstraint("status IN ('normal','violation')", name="ck_readings_status"),
        Index("ix_readings_mine_param_time", "mine_id", "parameter", "recorded_at"),
    )


# --------------------------------------------------------------------------
# Restricted zones
# --------------------------------------------------------------------------
class RestrictedZone(Base):
    __tablename__ = "restricted_zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    mine = relationship("Mine", back_populates="zones")
    camera_events = relationship("CameraEvent", back_populates="zone")


# --------------------------------------------------------------------------
# Camera / AI events
# --------------------------------------------------------------------------
class CameraEvent(Base):
    __tablename__ = "camera_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    zone_id: Mapped[str | None] = mapped_column(
        ForeignKey("restricted_zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    camera_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # Event types: person_without_helmet | person_without_vest |
    # restricted_zone_entry | vehicle_in_restricted_area | fire_smoke |
    # unsafe_crowding | other
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    detected_object: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zone_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # Severity: low | medium | high | critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    # Status: new | investigating | resolved
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    # Detection source: simulated | yolo  (never mislabel simulated as AI)
    detection_source: Mapped[str] = mapped_column(String(20), nullable=False, default="simulated")
    model_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    image_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Media-processing metadata (added in the YOLO-enhancement phase; nullable
    # so all pre-existing rows remain valid without migration).
    frame_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_media_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    mine = relationship("Mine", back_populates="camera_events")
    zone = relationship("RestrictedZone", back_populates="camera_events")

    __table_args__ = (
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_cam_severity"),
        CheckConstraint("status IN ('new','investigating','resolved')", name="ck_cam_status"),
        CheckConstraint("detection_source IN ('simulated','yolo','opencv')", name="ck_cam_source"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_cam_confidence"),
    )


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    # Types: environmental | safety | equipment | compliance
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # low|medium|high|critical
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="system")  # compliance_engine|camera_pipeline|manual|...
    # Status: new | acknowledged | investigating | resolved
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    # Optional traceability to the originating record.
    source_reading_id: Mapped[str | None] = mapped_column(
        ForeignKey("environmental_readings.id", ondelete="SET NULL"), nullable=True
    )
    source_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("camera_events.id", ondelete="SET NULL"), nullable=True
    )
    assigned_to_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    mine = relationship("Mine", back_populates="alerts")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])

    __table_args__ = (
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_alerts_severity"),
        CheckConstraint("status IN ('new','acknowledged','investigating','resolved')", name="ck_alerts_status"),
        Index("ix_alerts_mine_status_severity", "mine_id", "status", "severity"),
    )


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------
class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    reported_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Categories: fall_of_ground | machinery | vehicle | gas | fire | electrical | other
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")  # low|medium|high|critical
    # Statuses: open | investigating | action_required | resolved | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    mine = relationship("Mine", back_populates="incidents")
    reported_by = relationship("User", foreign_keys=[reported_by_id])
    corrective_actions = relationship("CorrectiveAction", back_populates="incident")

    __table_args__ = (
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_incidents_severity"),
        CheckConstraint(
            "status IN ('open','investigating','action_required','resolved','closed')",
            name="ck_incidents_status",
        ),
    )


# --------------------------------------------------------------------------
# Inspections
# --------------------------------------------------------------------------
class Inspection(Base):
    __tablename__ = "inspections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    inspector_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    inspection_type: Mapped[str] = mapped_column(String(50), nullable=False, default="safety")  # safety|environmental|equipment|compliance
    # Statuses: scheduled | in_progress | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled", index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Compliance result: compliant | non_compliant | partial | pending
    compliance_result: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    mine = relationship("Mine", back_populates="inspections")
    inspector = relationship("User", foreign_keys=[inspector_id])
    corrective_actions = relationship("CorrectiveAction", back_populates="inspection")

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','in_progress','completed','cancelled')",
            name="ck_inspections_status",
        ),
        CheckConstraint(
            "compliance_result IN ('compliant','non_compliant','partial','pending')",
            name="ck_inspections_result",
        ),
    )


# --------------------------------------------------------------------------
# Corrective actions
# --------------------------------------------------------------------------
class CorrectiveAction(Base):
    __tablename__ = "corrective_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    inspection_id: Mapped[str | None] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Priority: low | medium | high | critical
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    # Statuses: pending | in_progress | completed | overdue (overdue derived/updated)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    incident = relationship("Incident", back_populates="corrective_actions")
    inspection = relationship("Inspection", back_populates="corrective_actions")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])

    __table_args__ = (
        CheckConstraint("priority IN ('low','medium','high','critical')", name="ck_actions_priority"),
        CheckConstraint("status IN ('pending','in_progress','completed','overdue')", name="ck_actions_status"),
        CheckConstraint(
            "incident_id IS NOT NULL OR inspection_id IS NOT NULL",
            name="ck_actions_has_source",
        ),
    )
