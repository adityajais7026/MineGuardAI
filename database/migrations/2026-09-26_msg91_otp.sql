-- ============================================================================
-- Migration 2026-09-26: MSG91 SMS OTP support (additive, idempotent)
-- ============================================================================
-- Adds:
--   1. users.mobile            VARCHAR(15) NULL UNIQUE  (verified OTP mobile)
--   2. otp_challenges          server-side OTP Widget verification state
--   3. role_invitations        admin-issued invitations for privileged roles
--
-- No existing rows are modified and no existing columns/tables are dropped.
-- Safe to run multiple times. Existing deployments: run this once in the
-- Supabase SQL Editor (or psql) — nothing else is required.
-- ============================================================================

BEGIN;

-- 1) users.mobile ------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS mobile VARCHAR(15);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_mobile ON users (mobile);

-- 2) otp_challenges ----------------------------------------------------------
-- NOTE (schema-drift healing): environments that applied the earlier draft of
-- this migration created otp_challenges with the legacy code_hash-era shape
-- (no provider/provider_ref columns). CREATE TABLE IF NOT EXISTS silently
-- no-ops against that pre-existing table, so the widget-era columns are also
-- (re-)added idempotently here. No-op on a fresh/correct table.
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

-- Heal legacy otp_challenges tables missing the widget-era columns.
ALTER TABLE otp_challenges
    ADD COLUMN IF NOT EXISTS provider     VARCHAR(30) NOT NULL DEFAULT 'msg91_widget',
    ADD COLUMN IF NOT EXISTS provider_ref VARCHAR(255);

-- The widget-era design stores NO code at rest (MSG91 holds it), so the
-- legacy draft-era NOT NULL on code_hash must also be relaxed.
ALTER TABLE otp_challenges ALTER COLUMN code_hash DROP NOT NULL;

CREATE INDEX IF NOT EXISTS ix_otp_challenges_subject ON otp_challenges (subject);
CREATE INDEX IF NOT EXISTS ix_otp_challenges_purpose ON otp_challenges (purpose);
CREATE INDEX IF NOT EXISTS ix_otp_challenges_mobile ON otp_challenges (mobile);
CREATE INDEX IF NOT EXISTS ix_otp_challenges_expires_at ON otp_challenges (expires_at);
CREATE INDEX IF NOT EXISTS ix_otp_subject_purpose ON otp_challenges (subject, purpose);

-- 3) role_invitations --------------------------------------------------------
CREATE TABLE IF NOT EXISTS role_invitations (
    id             VARCHAR(36)  PRIMARY KEY,
    role           VARCHAR(40)  NOT NULL,
    code_hash      VARCHAR(255) NOT NULL,
    invited_by_id  VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
    used_by_id     VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
    note           VARCHAR(255),
    bound_email    VARCHAR(255),
    bound_mobile   VARCHAR(15),
    is_used        BOOLEAN      NOT NULL DEFAULT FALSE,
    used_at        TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ  NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_role_invitations_role CHECK (role IN ('admin', 'environmental_officer'))
);

CREATE INDEX IF NOT EXISTS ix_role_invitations_role ON role_invitations (role);
CREATE INDEX IF NOT EXISTS ix_role_invitations_is_used ON role_invitations (is_used);
CREATE INDEX IF NOT EXISTS ix_role_invitations_bound_email ON role_invitations (bound_email);
CREATE INDEX IF NOT EXISTS ix_role_invitations_bound_mobile ON role_invitations (bound_mobile);

-- RLS: keep new tables locked down like the rest of the schema ---------------
ALTER TABLE otp_challenges   ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_invitations ENABLE ROW LEVEL SECURITY;

COMMIT;
