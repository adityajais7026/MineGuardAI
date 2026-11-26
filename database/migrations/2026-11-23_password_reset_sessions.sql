-- Administrator password reset + session revocation (additive, no data loss).
--
-- Apply ONCE to an existing database before/with the deployment that ships
-- this feature. Fresh databases created from database/schema.sql already
-- contain both columns.
--
-- Both columns are nullable-free with safe defaults, so existing rows keep
-- working and nobody is logged out by the migration itself:
--   must_change_password = FALSE -> no existing account is forced to change
--   token_version        = 0     -> tokens minted before the deploy carry no
--                                   `tv` claim and are treated as 0

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;

-- ---------------------------------------------------------------------------
-- Audit ledger immutability (fixes a genuine chain-integrity bug).
--
-- audit_events.actor_id used to be a FK to users with ON DELETE SET NULL, and
-- audit_events.mine_id a FK to mines with the same rule. Deleting a user or a
-- mine therefore rewrote already-hashed rows, and verify_chain() correctly
-- reported the chain as broken afterwards. Both columns become plain stored
-- identifiers: deletions no longer touch the ledger and historical actor
-- attribution is preserved.
--
-- Repeatable and safe: constraint names are the PostgreSQL defaults, and the
-- block is skipped when the table does not exist yet (fresh installs create it
-- from the SQLAlchemy models, which already declare the columns without FKs).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF to_regclass('public.audit_events') IS NOT NULL THEN
        ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_actor_id_fkey;
        ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_mine_id_fkey;
        CREATE INDEX IF NOT EXISTS ix_audit_events_actor_id ON audit_events (actor_id);
    END IF;
END $$;

-- Rollback (only if the features are removed from the code first):
-- ALTER TABLE users DROP COLUMN IF EXISTS must_change_password;
-- ALTER TABLE users DROP COLUMN IF EXISTS token_version;
