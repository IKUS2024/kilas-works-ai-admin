-- Account-owned connector state. Existing Assist and Finance tables remain authoritative.
CREATE TABLE IF NOT EXISTS kilas_ai_connections (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 business_id BIGINT REFERENCES businesses(id),
 provider TEXT NOT NULL CHECK(provider IN ('GOOGLE')),
 external_account_id TEXT NOT NULL DEFAULT '', display_identity TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('DISCONNECTED','CONNECTING','CONNECTED','REAUTH_REQUIRED','ERROR','DISABLED')),
 scopes_json TEXT NOT NULL DEFAULT '[]', permission_json TEXT NOT NULL DEFAULT '{}',
 credential_enc TEXT, token_expires_at TIMESTAMPTZ, last_success_at TIMESTAMPTZ, last_error TEXT,
 created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
 UNIQUE(user_id,provider)
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_connections_owner ON kilas_ai_connections(user_id,status);
CREATE TABLE IF NOT EXISTS kilas_ai_oauth_states (
 state_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 provider TEXT NOT NULL CHECK(provider='GOOGLE'), scopes_json TEXT NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_oauth_owner ON kilas_ai_oauth_states(user_id,expires_at);
CREATE TABLE IF NOT EXISTS kilas_ai_action_approvals (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 business_id BIGINT REFERENCES businesses(id), connection_id BIGINT REFERENCES kilas_ai_connections(id),
 tool TEXT NOT NULL, target TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PENDING','CLAIMED','SUCCEEDED','FAILED','UNKNOWN','CANCELLED','EXPIRED')),
 idempotency_key TEXT NOT NULL UNIQUE, provider_result_id TEXT, error_code TEXT,
 expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_approvals_owner ON kilas_ai_action_approvals(user_id,status,id DESC);
CREATE TABLE IF NOT EXISTS kilas_ai_action_audit (
 id BIGSERIAL PRIMARY KEY,
 approval_id BIGINT NOT NULL REFERENCES kilas_ai_action_approvals(id),
 user_id BIGINT NOT NULL REFERENCES users(id), event TEXT NOT NULL,
 detail_code TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL
);
