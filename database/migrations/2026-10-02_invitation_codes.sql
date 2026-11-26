-- ============================================================================
-- Migration 2026-10-02: Invitation-code-only registration (single system)
-- ============================================================================
-- Companion to the invitation-code registration rework. Adds to role_invitations:
--   1. code        VARCHAR(255) NULL — the human-usable invitation code,
--      stored so the inviting admin can keep copying it from the management
--      list until the invitation is used, expired or deleted. Validation is
--      still done against the bcrypt `code_hash` (unchanged), never plaintext.
--   2. deleted_at  TIMESTAMPTZ NULL — soft delete by the creator; a deleted
--      code is invalid immediately and shows status "Deleted" in the list.
--   3. Index on `code` for direct lookup during registration validation.
--
-- Notes:
--   * No existing rows are modified and nothing is dropped — both columns are
--     NULLable. Existing invitation rows keep working through their hashes.
--   * Registration (all roles) now REQUIRES a valid, unused, unexpired,
--     non-deleted invitation code whose bound email matches exactly; the
--     account's role always comes from the invitation. No schema change is
--     needed for that — it is enforced by the API layer.
--   * The old link-accept endpoints were removed; legacy link rows (token_hash)
--     are simply inert and can be deleted or regenerated from the admin UI.
--   * Safe to run multiple times. Apply once in the Supabase SQL Editor.
-- ============================================================================

BEGIN;

-- 1) New nullable columns ----------------------------------------------------
ALTER TABLE role_invitations ADD COLUMN IF NOT EXISTS code VARCHAR(255);
ALTER TABLE role_invitations ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- 2) Code lookup index -------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_role_invitations_code ON role_invitations (code);

COMMIT;
