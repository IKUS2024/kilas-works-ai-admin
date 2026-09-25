-- Additive WEB channel only. Apply explicitly, never replay the legacy migration chain.
CREATE TABLE IF NOT EXISTS kw_web_channels (
 business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
 slug TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS kw_web_conversations (
 id TEXT PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES kw_web_channels(business_id),
 visitor_hash TEXT NOT NULL, expires_at BIGINT NOT NULL,
 mode TEXT NOT NULL DEFAULT 'AI_ACTIVE' CHECK(mode IN ('AI_ACTIVE','HUMAN_TAKEOVER')),
 version INTEGER NOT NULL DEFAULT 0, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL,
 UNIQUE(business_id,id), UNIQUE(business_id,visitor_hash)
);
CREATE INDEX IF NOT EXISTS kw_web_inbox ON kw_web_conversations(business_id,updated_at);
CREATE TABLE IF NOT EXISTS kw_web_events (
 business_id INTEGER NOT NULL, conversation_id TEXT NOT NULL, event_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('processing','done','failed')),
 claim_token TEXT NOT NULL, lease_until BIGINT NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
 version INTEGER NOT NULL, error TEXT,
 PRIMARY KEY(business_id,conversation_id,event_id),
 FOREIGN KEY(business_id,conversation_id) REFERENCES kw_web_conversations(business_id,id)
);
CREATE TABLE IF NOT EXISTS kw_web_messages (
 id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL, conversation_id TEXT NOT NULL,
 event_id TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant','human')),
 content TEXT NOT NULL, created_at BIGINT NOT NULL,
 UNIQUE(business_id,conversation_id,event_id,role),
 FOREIGN KEY(business_id,conversation_id) REFERENCES kw_web_conversations(business_id,id)
);
CREATE INDEX IF NOT EXISTS kw_web_thread ON kw_web_messages(business_id,conversation_id,id);
CREATE TABLE IF NOT EXISTS kw_web_limits (
 scope TEXT NOT NULL, bucket BIGINT NOT NULL, count INTEGER NOT NULL,
 PRIMARY KEY(scope,bucket)
);
