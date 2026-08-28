-- Kilas Works Client Hub — Business Hub V2, Phase A: password reset tokens (PostgreSQL dialect).
-- HONESTY NOTE: like every other *_postgres.sql migration in this folder, this has been carefully
-- hand-translated from the SQLite dialect but not executed against a real Postgres instance from
-- this sandbox (no network access to Render Postgres from here). Same BOOLEAN/placeholder lessons
-- from the Postgres Validation cycle apply — this table has no boolean columns, so that specific
-- class of bug does not apply here, but the general "test against real Postgres before trusting
-- fully" caveat still does.
-- ADDITIVE ONLY. No table/column drops.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    requested_ip TEXT
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires ON password_reset_tokens(expires_at);
