-- Additive mirror of the SQLite contract. No financial/data migration.
CREATE TABLE IF NOT EXISTS kw_assist_demo_sessions (
 id TEXT PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 actor_id BIGINT NOT NULL REFERENCES users(id),
 token_hash TEXT NOT NULL UNIQUE,
 created_at BIGINT NOT NULL,
 expires_at BIGINT NOT NULL,
 sender_phone TEXT,
 active BOOLEAN NOT NULL DEFAULT TRUE,
 UNIQUE(business_id,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS assist_demo_active_business ON kw_assist_demo_sessions(business_id) WHERE active=TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS assist_demo_active_sender ON kw_assist_demo_sessions(sender_phone) WHERE active=TRUE AND sender_phone IS NOT NULL;
CREATE TABLE IF NOT EXISTS kw_assist_demo_events (
 provider_id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL,
 business_id BIGINT NOT NULL,
 payload_hash TEXT NOT NULL,
 inbound_message_id BIGINT,
 reply_message_id BIGINT,
 reply_text TEXT,
 explanation_json TEXT,
 status TEXT NOT NULL DEFAULT 'received',
 created_at BIGINT NOT NULL,
 updated_at BIGINT NOT NULL,
 FOREIGN KEY(business_id,session_id) REFERENCES kw_assist_demo_sessions(business_id,id)
);
