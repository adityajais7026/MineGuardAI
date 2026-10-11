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
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
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
    # Mines this user is permitted to operate in — backend mine-scoping for
    # live webcam detection (safety_officer / environmental_officer are
    # scoped by this list; mine_manager by mines.manager_id instead; admin is
    # unrestricted). JSON array of mine ids; empty list = no permitted mines.
    permitted_mine_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
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
    """Admin-issued invitation — the ONLY way to create a new account.

    Minted by an existing administrator for one of the four roles. Every
    invitation carries:
      * `code`            — the human-usable invitation code, stored here so
        the inviting admin can keep copying it from the management list until
        the invitation is used, expired or deleted (requirement: the code must
        NOT become hidden after creation).
      * `code_hash`       — bcrypt hash of the code (verification credential).
      * `bound_email`     — the email the invitation is strictly tied to; a
        registration with any other email is rejected server-side.
      * `role`            — the account's role, decided ONLY by the invitation.

    Single-use (consumed atomically with account creation), expiring
    (INVITATION_EXPIRY_HOURS), soft-deletable (`deleted_at` immediately
    invalidates the code) and regenerable (new code, same email/role, old
    code invalidated). Registration additionally requires MSG91 mobile OTP
    via the existing register-purpose flow — no second OTP system.

    Legacy columns kept for schema stability: `token_hash` (old link
    invitations, flow removed) and `bound_mobile`.
    """

    __tablename__ = "role_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    role: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # admin|environmental_officer|mine_manager|safety_officer
    # The invitation code itself, stored so the creator can keep copying it
    # from the management UI until the invitation is used/expired/deleted.
    code: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # bcrypt hash of the code — the verification credential.
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Legacy link-invitation hash (flow removed); NULL for code invitations.
    token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Display name of the invited person (shown in the management list and
    # used as the account's full_name on registration).
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invited_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional: bind the invitation to one email or mobile.
    bound_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    bound_mobile: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    used_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft delete: set when the creator deletes the invitation; the code stops
    # working immediately and the row stays for audit (status "Deleted").
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin','mine_manager','safety_officer','environmental_officer')",
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
    # ADDITIVE lifecycle column for the review/approval workflow (independent
    # of legacy `status` so existing flows keep working unchanged):
    # draft | in_progress | submitted | under_review | approved | rejected | closed
    review_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    mine = relationship("Mine", back_populates="inspections")
    inspector = relationship("User", foreign_keys=[inspector_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
    corrective_actions = relationship("CorrectiveAction", back_populates="inspection")

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','in_progress','completed','cancelled')",
            name="ck_inspections_status",
        ),
        CheckConstraint(
            "review_status IS NULL OR review_status IN "
            "('draft','in_progress','submitted','under_review','approved','rejected','closed')",
            name="ck_inspections_review_status",
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


# ==========================================================================
# Smart Governance & Compliance platform additions (governance upgrade).
#
# Design rules for this block:
#   * ADDITIVE ONLY — no existing table or column is altered; every model is
#     a new table so SQLite (dev) and PostgreSQL (Supabase/Render) both work
#     via the ordinary create_all path.
#   * Enum-like values are strings validated at the Pydantic layer, matching
#     the existing convention above.
#   * AI-produced values (OCR fields, transcriptions, PPE suggestions) are
#     always stored as SUGGESTIONS with the model name/confidence recorded;
#     a human confirmation flag decides what becomes an official record.
# ==========================================================================


class InspectionTemplate(Base):
    """Reusable inspection checklist template (configurable, not hard-coded)."""

    __tablename__ = "inspection_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspection_type: Mapped[str] = mapped_column(String(50), nullable=False, default="safety")
    mine_id: Mapped[str | None] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL -> template available to all mines
    # Optional configured regulatory reference (e.g. "CMR 2017 reg 123").
    # Never filled by the application automatically — an admin must set it.
    regulatory_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    items = relationship(
        "InspectionTemplateItem", back_populates="template", cascade="all, delete-orphan",
        order_by="InspectionTemplateItem.position",
    )


class InspectionTemplateItem(Base):
    """One checklist line inside a template.

    result_options constrains what an inspector may answer (pass/fail/na/unknown
    by default). severity weights are used by the deterministic risk scorer.
    """

    __tablename__ = "inspection_template_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("inspection_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. "ppe", "electrical", "ventilation", "fire", "gas", "machinery", "general"
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    # Comma-separated subset of pass|fail|na|unknown the inspector may answer.
    result_options: Mapped[str] = mapped_column(String(200), nullable=False, default="pass,fail,na,unknown")
    # Weight used by the deterministic risk score for a 'fail' answer (0-10).
    severity_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    requires_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Allowed values for a free-text/selection answer (optional).
    options_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    template = relationship("InspectionTemplate", back_populates="items")


class InspectionChecklistItem(Base):
    """A template item SNAPSHOT copied onto a concrete inspection.

    Snapshotted at inspection creation so later template edits never rewrite
    the record of what was actually asked at inspection time.
    """

    __tablename__ = "inspection_checklist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("inspection_template_items.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    result_options: Mapped[str] = mapped_column(String(200), nullable=False, default="pass,fail,na,unknown")
    severity_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # pass | fail | na | unknown (unknown = no evidence, never a violation)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AI suggestion (from inspection photo analysis) — suggestion only.
    ai_suggestion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_confirmed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (
        CheckConstraint("result IS NULL OR result IN ('pass','fail','na','unknown')", name="ck_checklist_result"),
        CheckConstraint("ai_suggestion IS NULL OR ai_suggestion IN ('pass','fail','na','unknown')", name="ck_checklist_ai_suggestion"),
    )


class Evidence(Base):
    """Polymorphic evidence record (image/video/audio/document).

    `kind` selects the related record: inspection | checklist_item | incident |
    corrective_action | camera_event | emergency. Exactly one of the matching
    foreign keys must be set (validated in the service layer).
    """

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str | None] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    inspection_id: Mapped[str | None] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), nullable=True, index=True)
    checklist_item_id: Mapped[str | None] = mapped_column(ForeignKey("inspection_checklist_items.id", ondelete="CASCADE"), nullable=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True)
    corrective_action_id: Mapped[str | None] = mapped_column(ForeignKey("corrective_actions.id", ondelete="CASCADE"), nullable=True, index=True)
    camera_event_id: Mapped[str | None] = mapped_column(ForeignKey("camera_events.id", ondelete="CASCADE"), nullable=True)
    emergency_id: Mapped[str | None] = mapped_column(ForeignKey("emergency_events.id", ondelete="CASCADE"), nullable=True)
    # image | video | audio | document
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, default="image")
    # Path from the storage backend (Supabase or local).
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("media_type IN ('image','video','audio','document')", name="ck_evidence_media_type"),
    )


class ComplianceRequirement(Base):
    """Configurable compliance requirement (GREEN/AMBER/RED/GREY model).

    MUST carry an explicit reference/source string — the application never
    claims a requirement is a legal one unless an admin configured the source.
    """

    __tablename__ = "compliance_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str | None] = mapped_column(
        ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL -> all mines
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Configured source/reference, e.g. "DGMS circular 2024-07" or internal SOP.
    # REQUIRED: compliance status without a traceable source is not shown as
    # regulatory truth by the UI.
    reference: Mapped[str] = mapped_column(String(500), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")  # daily|weekly|monthly|quarterly|custom
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("inspection_templates.id", ondelete="SET NULL"), nullable=True
    )
    # due anchor day (day of month/week) used to compute next_deadline.
    due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("frequency IN ('daily','weekly','monthly','quarterly','custom')", name="ck_comp_req_frequency"),
    )


class ComplianceAssessment(Base):
    """Assessed status for a requirement over a reporting period."""

    __tablename__ = "compliance_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("compliance_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mine_id: Mapped[str | None] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True)
    # compliant | attention | violation | not_assessed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_assessed")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inspection_id: Mapped[str | None] = mapped_column(ForeignKey("inspections.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('compliant','attention','violation','not_assessed')",
            name="ck_comp_assess_status",
        ),
    )


class Geofence(Base):
    """Mine site boundary: circular (lat/lon/radius_m) or polygon (lat/lng list)."""

    __tablename__ = "geofences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    boundary_type: Mapped[str] = mapped_column(String(20), nullable=False, default="radius")  # radius|polygon
    center_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Polygon as [[lat,lng], ...] — validated at the schema layer.
    polygon_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("boundary_type IN ('radius','polygon')", name="ck_geofence_type"),
    )


class EmergencyEvent(Base):
    """Emergency event (fire, gas leak, collapse, critical PPE, worker, other)."""

    __tablename__ = "emergency_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    # fire | gas_leak | collapse | ppe_critical | worker_emergency | other
    emergency_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="critical")  # low|medium|high|critical
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)  # open|responding|resolved|closed
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reported_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_emergency_severity"),
        CheckConstraint("status IN ('open','responding','resolved','closed')", name="ck_emergency_status"),
    )


class Worker(Base):
    """Mine worker / employee record."""

    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    contractor_id: Mapped[str | None] = mapped_column(
        ForeignKey("contractors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. driller, helper, supervisor
    phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    contractor = relationship("Contractor", back_populates="workers", foreign_keys=[contractor_id])


class Contractor(Base):
    """Contractor firm working at a mine."""

    __tablename__ = "contractors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    workers = relationship("Worker", back_populates="contractor", foreign_keys="Worker.contractor_id")


class ContractorDocument(Base):
    """Certificate / authorization document for a worker, contractor or equipment.

    Verification status is ONLY what an authorized human has recorded — the
    application never claims cryptographic authenticity of an uploaded scan.
    """

    __tablename__ = "contractor_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contractor_id: Mapped[str | None] = mapped_column(ForeignKey("contractors.id", ondelete="CASCADE"), nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), nullable=True, index=True)
    mine_id: Mapped[str | None] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True)
    doc_type: Mapped[str] = mapped_column(String(80), nullable=False)  # training_certificate | authorization | equipment_certificate | other
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_ref: Mapped[str] = mapped_column(String(500), nullable=False)  # storage path
    issued_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # valid | expiring | expired | pending_verification (computed lazily + stored)
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_verification")
    verified_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class Shift(Base):
    """A scheduled shift instance for a mine."""

    __tablename__ = "shifts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "A shift"
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Attendance(Base):
    """Worker check-in/out for a shift.

    verification = manual | qr | geofence | biometric (biometric is an optional
    integration; no raw biometric data is ever stored by MineGuardAI).
    """

    __tablename__ = "attendance"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    shift_id: Mapped[str | None] = mapped_column(ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True, index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    check_in_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("verification IN ('manual','qr','geofence','biometric')", name="ck_attendance_verification"),
    )


class SensorDevice(Base):
    """Registered environmental sensor (real or clearly-labeled demo device)."""

    __tablename__ = "sensor_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    device_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    # methane | co | co2 | oxygen | temperature | humidity | other
    parameter: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    # real | demo — demo devices are labeled DEMO everywhere in the UI.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="demo")
    location_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    warning_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("source IN ('real','demo')", name="ck_sensor_source"),
    )


class TelemetryReading(Base):
    """One telemetry sample from a sensor device."""

    __tablename__ = "telemetry_readings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(ForeignKey("sensor_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    # normal | warning | critical | unknown
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("status IN ('normal','warning','critical','unknown')", name="ck_telemetry_status"),
    )


class AuditEvent(Base):
    """Tamper-evident audit log entry with SHA-256 hash chaining.

    event_hash = sha256(prev_hash + canonical_json(entry_fields)).
    Verification recomputes the chain in order; any mutation of a past row
    breaks every subsequent hash. This is a hash chain, NOT a blockchain —
    the UI says 'tamper-evident audit log', never 'blockchain'.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. inspection.submit, action.complete
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    mine_id: Mapped[str | None] = mapped_column(ForeignKey("mines.id", ondelete="SET NULL"), nullable=True, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class RiskScore(Base):
    """Deterministic, explainable mine risk score snapshot."""

    __tablename__ = "risk_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mine_id: Mapped[str] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0..100
    # low | medium | high | critical (derived from score bands, stored for filter)
    band: Mapped[str] = mapped_column(String(20), nullable=False)
    # Explainability: each contributor with points and why, e.g.
    # [{"factor": "overdue_actions", "points": 18, "detail": "3 overdue"}, ...]
    factors_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    computed_by: Mapped[str] = mapped_column(String(20), nullable=False, default="deterministic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("band IN ('low','medium','high','critical')", name="ck_risk_band"),
    )


class SyncRecord(Base):
    """Offline-first sync ledger: idempotency + conflict tracking.

    client_guid is the offline client's UUID for the record; the unique
    constraint makes replayed sync pushes no-ops (idempotent). payload holds
    the serialized inspection (checklist results, GPS, notes) exactly as the
    client produced it. status: pending | synced | failed.
    """

    __tablename__ = "sync_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_guid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    mine_id: Mapped[str | None] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, default="inspection")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Notification(Base):
    """In-app notification (centralized notification center)."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    mine_id: Mapped[str | None] = mapped_column(ForeignKey("mines.id", ondelete="CASCADE"), nullable=True, index=True)
    # ppe_violation | critical_hazard | overdue_action | emergency |
    # compliance_deadline | certificate_expiry | inspection_reminder | sensor_alert
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Dedupe key so repeated events don't spam (e.g. action:<id>:overdue:level1).
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

