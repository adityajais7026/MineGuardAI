-- ============================================================================
-- MineGuardAI — Supabase PostgreSQL schema
-- ============================================================================
-- Target: Supabase PostgreSQL (production database).
-- This DDL mirrors backend/app/database/models.py (SQLAlchemy ORM) 1:1:
--   * same tables, columns, nullability and defaults
--   * same foreign keys and ON DELETE behaviour
--   * same CHECK constraint names and value sets
--   * same indexes
--
-- Run in the Supabase SQL Editor, or: psql "$DATABASE_URL" -f database/schema.sql
-- Simulated data lives in database/seed.sql and is clearly labelled.
--
-- EXISTING DEPLOYMENTS: camera_events gained three nullable columns
-- (frame_number, video_timestamp, source_media_ref). Add them with:
--   ALTER TABLE camera_events ADD COLUMN IF NOT EXISTS frame_number INTEGER;
--   ALTER TABLE camera_events ADD COLUMN IF NOT EXISTS video_timestamp DOUBLE PRECISION;
--   ALTER TABLE camera_events ADD COLUMN IF NOT EXISTS source_media_ref VARCHAR(500);
--
-- EXISTING DEPLOYMENTS (MSG91 SMS OTP phase): users gained a nullable `mobile`
-- column and two new tables (otp_challenges, role_invitations). Apply with:
--   database/migrations/2026-09-26_msg91_otp.sql  (idempotent)
--
-- EXISTING DEPLOYMENTS (user-invitations phase): role_invitations gained two
-- nullable columns (token_hash, full_name) and a widened role CHECK. Apply with:
--   database/migrations/2026-10-01_user_invitations.sql  (idempotent)
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- users  (local-auth credential store; supabase_user_id links to Supabase Auth)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                VARCHAR(36)  PRIMARY KEY,
    email             VARCHAR(255) NOT NULL,
    full_name         VARCHAR(255) NOT NULL,
    role              VARCHAR(40)  NOT NULL DEFAULT 'safety_officer',
    hashed_password   VARCHAR(255),
    supabase_user_id  VARCHAR(64),
    mobile            VARCHAR(15),
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_users_role
        CHECK (role IN ('admin', 'mine_manager', 'safety_officer', 'environmental_officer'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_supabase_user_id ON users (supabase_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_mobile ON users (mobile);

-- ----------------------------------------------------------------------------
-- otp_challenges  (MSG91 OTP Widget verification state; provider request ids)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS otp_challenges (
    id                  VARCHAR(36)  PRIMARY KEY,
    subject             VARCHAR(36)  NOT NULL,
    purpose             VARCHAR(20)  NOT NULL,
    mobile              VARCHAR(15)  NOT NULL,
    provider            VARCHAR(30)  NOT NULL DEFAULT 'msg91_widget',
    provider_ref        VARCHAR(255),
    attempts_left       INTEGER      NOT NULL DEFAULT 5,
    attempts_used       INTEGER      NOT NULL DEFAULT 0,
    request_count       INTEGER      NOT NULL DEFAULT 1,
    first_requested_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_sent_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ  NOT NULL,
    consumed_at         TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    last_error          VARCHAR(255),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_otp_purpose CHECK (purpose IN ('register', 'login'))
);
CREATE INDEX IF NOT EXISTS ix_otp_challenges_subject ON otp_challenges (subject);
CREATE INDEX IF NOT EXISTS ix_otp_challenges_purpose ON otp_challenges (purpose);
CREATE INDEX IF NOT EXISTS ix_otp_challenges_mobile ON otp_challenges (mobile);
CREATE INDEX IF NOT EXISTS ix_otp_challenges_expires_at ON otp_challenges (expires_at);
CREATE INDEX IF NOT EXISTS ix_otp_subject_purpose ON otp_challenges (subject, purpose);

-- ----------------------------------------------------------------------------
-- role_invitations  (admin-issued single-use invitations for privileged roles)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS role_invitations (
    id             VARCHAR(36)  PRIMARY KEY,
    role           VARCHAR(40)  NOT NULL,
    code_hash      VARCHAR(255) NOT NULL,
    token_hash     VARCHAR(255),
    full_name      VARCHAR(255),
    invited_by_id  VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
    note           VARCHAR(255),
    bound_email    VARCHAR(255),
    bound_mobile   VARCHAR(15),
    is_used        BOOLEAN      NOT NULL DEFAULT FALSE,
    used_by_id     VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
    used_at        TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ  NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_role_invitations_role CHECK (role IN ('admin', 'mine_manager', 'safety_officer', 'environmental_officer'))
);
CREATE INDEX IF NOT EXISTS ix_role_invitations_role ON role_invitations (role);
CREATE INDEX IF NOT EXISTS ix_role_invitations_is_used ON role_invitations (is_used);
CREATE INDEX IF NOT EXISTS ix_role_invitations_bound_email ON role_invitations (bound_email);
CREATE INDEX IF NOT EXISTS ix_role_invitations_bound_mobile ON role_invitations (bound_mobile);

-- ----------------------------------------------------------------------------
-- mines
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mines (
    id          VARCHAR(36)  PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    code        VARCHAR(20)  NOT NULL,
    mine_type   VARCHAR(20)  NOT NULL DEFAULT 'open_cast',
    status      VARCHAR(20)  NOT NULL DEFAULT 'operational',
    location    VARCHAR(255) NOT NULL,
    latitude    DOUBLE PRECISION,
    longitude   DOUBLE PRECISION,
    manager_id  VARCHAR(36),
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_mines_type   CHECK (mine_type IN ('open_cast', 'underground', 'mixed')),
    CONSTRAINT ck_mines_status CHECK (status IN ('operational', 'maintenance', 'suspended', 'closed')),
    CONSTRAINT fk_mines_manager FOREIGN KEY (manager_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_mines_code ON mines (code);
CREATE INDEX IF NOT EXISTS ix_mines_name ON mines (name);
CREATE INDEX IF NOT EXISTS ix_mines_status ON mines (status);
CREATE INDEX IF NOT EXISTS ix_mines_manager_id ON mines (manager_id);

-- ----------------------------------------------------------------------------
-- compliance_rules  (mine_id NULL -> applies to all mines)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compliance_rules (
    id          VARCHAR(36)  PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    parameter   VARCHAR(50)  NOT NULL,
    operator    VARCHAR(10)  NOT NULL DEFAULT '>',
    threshold   DOUBLE PRECISION NOT NULL,
    unit        VARCHAR(20)  NOT NULL,
    severity    VARCHAR(20)  NOT NULL DEFAULT 'medium',
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    mine_id     VARCHAR(36),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_rules_operator CHECK (operator IN ('>', '>=', '<', '<=')),
    CONSTRAINT ck_rules_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT fk_rules_mine FOREIGN KEY (mine_id) REFERENCES mines (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_compliance_rules_parameter ON compliance_rules (parameter);
CREATE INDEX IF NOT EXISTS ix_compliance_rules_mine_id ON compliance_rules (mine_id);
CREATE INDEX IF NOT EXISTS ix_compliance_rules_is_active ON compliance_rules (is_active);

-- ----------------------------------------------------------------------------
-- environmental_readings
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS environmental_readings (
    id          VARCHAR(36)  PRIMARY KEY,
    mine_id     VARCHAR(36)  NOT NULL,
    rule_id     VARCHAR(36),
    parameter   VARCHAR(50)  NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    unit        VARCHAR(20)  NOT NULL,
    threshold   DOUBLE PRECISION NOT NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'normal',
    source      VARCHAR(30)  NOT NULL DEFAULT 'simulated',
    recorded_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_readings_status CHECK (status IN ('normal', 'violation')),
    CONSTRAINT fk_readings_mine FOREIGN KEY (mine_id) REFERENCES mines (id) ON DELETE CASCADE,
    CONSTRAINT fk_readings_rule FOREIGN KEY (rule_id) REFERENCES compliance_rules (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_environmental_readings_mine_id ON environmental_readings (mine_id);
CREATE INDEX IF NOT EXISTS ix_environmental_readings_parameter ON environmental_readings (parameter);
CREATE INDEX IF NOT EXISTS ix_environmental_readings_status ON environmental_readings (status);
CREATE INDEX IF NOT EXISTS ix_environmental_readings_recorded_at ON environmental_readings (recorded_at);
-- Composite index powering trend queries (mine + parameter over time)
CREATE INDEX IF NOT EXISTS ix_readings_mine_param_time
    ON environmental_readings (mine_id, parameter, recorded_at);

-- ----------------------------------------------------------------------------
-- restricted_zones
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS restricted_zones (
    id          VARCHAR(36)  PRIMARY KEY,
    mine_id     VARCHAR(36)  NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    camera_id   VARCHAR(60),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT fk_zones_mine FOREIGN KEY (mine_id) REFERENCES mines (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_restricted_zones_mine_id ON restricted_zones (mine_id);
CREATE INDEX IF NOT EXISTS ix_restricted_zones_camera_id ON restricted_zones (camera_id);

-- ----------------------------------------------------------------------------
-- camera_events  (detection_source marks simulated vs real YOLO/OpenCV output)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camera_events (
    id               VARCHAR(36)  PRIMARY KEY,
    mine_id          VARCHAR(36)  NOT NULL,
    zone_id          VARCHAR(36),
    camera_id        VARCHAR(60)  NOT NULL,
    event_type       VARCHAR(50)  NOT NULL,
    detected_object  VARCHAR(120),
    zone_label       VARCHAR(255),
    confidence       DOUBLE PRECISION NOT NULL,
    severity         VARCHAR(20)  NOT NULL DEFAULT 'medium',
    status           VARCHAR(20)  NOT NULL DEFAULT 'new',
    detection_source VARCHAR(20)  NOT NULL DEFAULT 'simulated',
    model_version    VARCHAR(60),
    image_ref        VARCHAR(500),
    video_ref        VARCHAR(500),
    -- YOLO media metadata (added additively; nullable -> no migration needed)
    frame_number     INTEGER,
    video_timestamp  DOUBLE PRECISION,
    source_media_ref VARCHAR(500),
    occurred_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_cam_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_cam_status   CHECK (status IN ('new', 'investigating', 'resolved')),
    CONSTRAINT ck_cam_source   CHECK (detection_source IN ('simulated', 'yolo', 'opencv')),
    CONSTRAINT ck_cam_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT fk_cam_mine FOREIGN KEY (mine_id) REFERENCES mines (id) ON DELETE CASCADE,
    CONSTRAINT fk_cam_zone FOREIGN KEY (zone_id) REFERENCES restricted_zones (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_camera_events_mine_id ON camera_events (mine_id);
CREATE INDEX IF NOT EXISTS ix_camera_events_zone_id ON camera_events (zone_id);
CREATE INDEX IF NOT EXISTS ix_camera_events_camera_id ON camera_events (camera_id);
CREATE INDEX IF NOT EXISTS ix_camera_events_event_type ON camera_events (event_type);
CREATE INDEX IF NOT EXISTS ix_camera_events_status ON camera_events (status);
CREATE INDEX IF NOT EXISTS ix_camera_events_occurred_at ON camera_events (occurred_at);

-- ----------------------------------------------------------------------------
-- alerts
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id                VARCHAR(36)  PRIMARY KEY,
    mine_id           VARCHAR(36)  NOT NULL,
    alert_type        VARCHAR(30)  NOT NULL,
    title             VARCHAR(255) NOT NULL,
    description       TEXT,
    severity          VARCHAR(20)  NOT NULL,
    source            VARCHAR(60)  NOT NULL DEFAULT 'system',
    status            VARCHAR(20)  NOT NULL DEFAULT 'new',
    source_reading_id VARCHAR(36),
    source_event_id   VARCHAR(36),
    assigned_to_id    VARCHAR(36),
    acknowledged_at   TIMESTAMPTZ,
    resolved_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_alerts_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_alerts_status   CHECK (status IN ('new', 'acknowledged', 'investigating', 'resolved')),
    CONSTRAINT fk_alerts_mine FOREIGN KEY (mine_id) REFERENCES mines (id) ON DELETE CASCADE,
    CONSTRAINT fk_alerts_reading FOREIGN KEY (source_reading_id) REFERENCES environmental_readings (id) ON DELETE SET NULL,
    CONSTRAINT fk_alerts_event FOREIGN KEY (source_event_id) REFERENCES camera_events (id) ON DELETE SET NULL,
    CONSTRAINT fk_alerts_assignee FOREIGN KEY (assigned_to_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_alerts_mine_id ON alerts (mine_id);
CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts (status);
CREATE INDEX IF NOT EXISTS ix_alerts_severity ON alerts (severity);
CREATE INDEX IF NOT EXISTS ix_alerts_alert_type ON alerts (alert_type);
CREATE INDEX IF NOT EXISTS ix_alerts_assigned_to_id ON alerts (assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_alerts_created_at ON alerts (created_at);
-- Composite index powering the dashboard's open-alert queries
CREATE INDEX IF NOT EXISTS ix_alerts_mine_status_severity ON alerts (mine_id, status, severity);

-- ----------------------------------------------------------------------------
-- incidents
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id             VARCHAR(36)  PRIMARY KEY,
    mine_id        VARCHAR(36)  NOT NULL,
    reported_by_id VARCHAR(36),
    title          VARCHAR(255) NOT NULL,
    description    TEXT,
    category       VARCHAR(40)  NOT NULL DEFAULT 'other',
    severity       VARCHAR(20)  NOT NULL DEFAULT 'medium',
    status         VARCHAR(20)  NOT NULL DEFAULT 'open',
    evidence_ref   VARCHAR(500),
    occurred_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_incidents_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_incidents_status
        CHECK (status IN ('open', 'investigating', 'action_required', 'resolved', 'closed')),
    CONSTRAINT fk_incidents_mine FOREIGN KEY (mine_id) REFERENCES mines (id) ON DELETE CASCADE,
    CONSTRAINT fk_incidents_reporter FOREIGN KEY (reported_by_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_incidents_mine_id ON incidents (mine_id);
CREATE INDEX IF NOT EXISTS ix_incidents_status ON incidents (status);

-- ----------------------------------------------------------------------------
-- inspections
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inspections (
    id                VARCHAR(36)  PRIMARY KEY,
    mine_id           VARCHAR(36)  NOT NULL,
    inspector_id      VARCHAR(36),
    inspection_type   VARCHAR(50)  NOT NULL DEFAULT 'safety',
    status            VARCHAR(20)  NOT NULL DEFAULT 'scheduled',
    scheduled_at      TIMESTAMPTZ  NOT NULL,
    completed_at      TIMESTAMPTZ,
    compliance_result VARCHAR(20)  NOT NULL DEFAULT 'pending',
    findings          TEXT,
    notes             TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_inspections_status
        CHECK (status IN ('scheduled', 'in_progress', 'completed', 'cancelled')),
    CONSTRAINT ck_inspections_result
        CHECK (compliance_result IN ('compliant', 'non_compliant', 'partial', 'pending')),
    CONSTRAINT fk_inspections_mine FOREIGN KEY (mine_id) REFERENCES mines (id) ON DELETE CASCADE,
    CONSTRAINT fk_inspections_inspector FOREIGN KEY (inspector_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_inspections_mine_id ON inspections (mine_id);
CREATE INDEX IF NOT EXISTS ix_inspections_status ON inspections (status);

-- ----------------------------------------------------------------------------
-- corrective_actions  (must reference an incident or an inspection)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corrective_actions (
    id              VARCHAR(36)  PRIMARY KEY,
    incident_id     VARCHAR(36),
    inspection_id   VARCHAR(36),
    description     TEXT         NOT NULL,
    assigned_to_id  VARCHAR(36),
    priority        VARCHAR(20)  NOT NULL DEFAULT 'medium',
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    due_date        TIMESTAMPTZ  NOT NULL,
    completion_date TIMESTAMPTZ,
    remarks         TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_actions_priority CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_actions_status   CHECK (status IN ('pending', 'in_progress', 'completed', 'overdue')),
    CONSTRAINT ck_actions_has_source CHECK (incident_id IS NOT NULL OR inspection_id IS NOT NULL),
    CONSTRAINT fk_actions_incident FOREIGN KEY (incident_id) REFERENCES incidents (id) ON DELETE CASCADE,
    CONSTRAINT fk_actions_inspection FOREIGN KEY (inspection_id) REFERENCES inspections (id) ON DELETE CASCADE,
    CONSTRAINT fk_actions_assignee FOREIGN KEY (assigned_to_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_corrective_actions_incident_id ON corrective_actions (incident_id);
CREATE INDEX IF NOT EXISTS ix_corrective_actions_inspection_id ON corrective_actions (inspection_id);
CREATE INDEX IF NOT EXISTS ix_corrective_actions_assigned_to_id ON corrective_actions (assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_corrective_actions_status ON corrective_actions (status);

COMMIT;

-- ============================================================================
-- Row Level Security
-- ============================================================================
-- The backend connects with the service role / direct Postgres connection and
-- enforces role-based access in application code, so table access is NOT
-- exposed via anon/authenticated Supabase API roles. These statements keep the
-- tables locked down at the database level for defence in depth.
-- ============================================================================
ALTER TABLE users                ENABLE ROW LEVEL SECURITY;
ALTER TABLE otp_challenges       ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_invitations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE mines                ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_rules     ENABLE ROW LEVEL SECURITY;
ALTER TABLE environmental_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE restricted_zones     ENABLE ROW LEVEL SECURITY;
ALTER TABLE camera_events        ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts               ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents            ENABLE ROW LEVEL SECURITY;
ALTER TABLE inspections          ENABLE ROW LEVEL SECURITY;
ALTER TABLE corrective_actions   ENABLE ROW LEVEL SECURITY;

-- No permissive policies are created for anon/authenticated on purpose:
-- all access flows through the backend (service role bypasses RLS).
