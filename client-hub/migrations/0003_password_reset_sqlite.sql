-- Kilas Works Client Hub — Business Hub V2, Phase A: password reset tokens (SQLite dialect).
-- ADDITIVE ONLY. No table/column drops, nothing from 0001/0002 touched.
--
-- SECURITY DESIGN: we NEVER store the raw reset token — only a SHA-256 hash of it (token_hash).
-- The raw token only ever exists in the URL we hand to the user once. If this table ever leaked
-- (DB dump, backup, etc.), the hashes alone are useless for resetting anyone's password — same
-- principle as password_hash on `users`, applied to the reset token itself.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    used_at TEXT,                 -- NULL until consumed; single-use enforced by checking this
    requested_ip TEXT
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires ON password_reset_tokens(expires_at);
