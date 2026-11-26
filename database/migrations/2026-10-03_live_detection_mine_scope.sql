-- ============================================================================
-- Migration 2026-10-03: Live-detection mine scoping (backend RBAC)
-- ============================================================================
-- Companion to the mine-scoped live-webcam-detection authorization. Adds to
-- users:
--   permitted_mine_ids JSON NOT NULL DEFAULT '[]'
--     Explicit, admin-managed list of mine ids an officer (safety_officer /
--     environmental_officer) may run live detection in. mine_manager scope is
--     derived from mines.manager_id; admin is unrestricted. Empty list = no
--     permitted mines (access is never implicit).
--   * Nullable columns are NOT used: the column is NOT NULL with a JSON
--     default so every existing row (and every future row) has an array.
--   * No existing rows are modified beyond the default; nothing is dropped.
--   * The invitation-code system, MSG91/OTP and all other tables are
--     untouched.
--   * Safe to run multiple times. Apply once in the Supabase SQL Editor.
-- ============================================================================

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS permitted_mine_ids JSON
        NOT NULL DEFAULT '[]'::jsonb;

COMMIT;
