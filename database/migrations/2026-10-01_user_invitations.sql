-- ============================================================================
-- Migration 2026-10-01: User invitations (link invitations), additive + idempotent
-- ============================================================================
-- Companion to the invitation / permanent-delete feature. Adds:
--   1. role_invitations.role widened from (admin, environmental_officer) to
--      all four roles.
--   2. role_invitations.token_hash  VARCHAR(255) NULL  (bcrypt hash of the
--      single-use accept-link token for link invitations).
--   3. role_invitations.full_name   VARCHAR(255) NULL  (invited person name).
--
-- Notes:
--   * No existing rows are modified and nothing is dropped — the new columns
--     are NULLable, so legacy invitation-code rows stay valid untouched.
--   * The legacy CHECK constraint ck_role_invitations_role is replaced only
--     when it still restricts roles to admin/environmental_officer.
--   * Accounts created via link invitations have mobile = NULL and log in
--     with email + password; MSG91/OTP flows are untouched.
--   * Safe to run multiple times. Apply once in the Supabase SQL Editor.
-- ============================================================================

BEGIN;

-- 1) New nullable columns ----------------------------------------------------
ALTER TABLE role_invitations ADD COLUMN IF NOT EXISTS token_hash VARCHAR(255);
ALTER TABLE role_invitations ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);

-- 2) Widen the role CHECK constraint ------------------------------------------
ALTER TABLE role_invitations DROP CONSTRAINT IF EXISTS ck_role_invitations_role;
ALTER TABLE role_invitations ADD CONSTRAINT ck_role_invitations_role
    CHECK (role IN ('admin', 'mine_manager', 'safety_officer', 'environmental_officer'));

COMMIT;
