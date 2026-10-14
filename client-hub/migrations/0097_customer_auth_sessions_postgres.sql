-- Authentication metadata only. No tenant, Finance or provider data is changed.
CREATE TABLE IF NOT EXISTS customer_auth_sessions (
 token_hash TEXT PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 role TEXT NOT NULL, password_stamp TEXT NOT NULL,
 account_generation BIGINT NOT NULL,
 created_at BIGINT NOT NULL, revoked_at BIGINT
);
CREATE INDEX IF NOT EXISTS customer_auth_sessions_user ON customer_auth_sessions(user_id);
CREATE TABLE IF NOT EXISTS customer_auth_account_state (
 user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)),
 generation BIGINT NOT NULL DEFAULT 0
);
