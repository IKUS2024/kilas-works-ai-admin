-- Only authenticated owner training creates reusable media. Inbox files are separate.
CREATE UNIQUE INDEX IF NOT EXISTS business_files_owned ON business_files(id,business_id);
CREATE TABLE IF NOT EXISTS kw_assist_business_media (
 file_id BIGINT PRIMARY KEY, business_id BIGINT NOT NULL REFERENCES businesses(id),
 summary TEXT NOT NULL, knowledge TEXT NOT NULL, usage_instruction TEXT NOT NULL,
 approved_send INTEGER NOT NULL CHECK(approved_send IN (0,1)), version TEXT NOT NULL,
 actor_id BIGINT NOT NULL REFERENCES users(id),
 FOREIGN KEY(file_id,business_id) REFERENCES business_files(id,business_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS kw_assist_business_media_business ON kw_assist_business_media(business_id,file_id);
CREATE TABLE IF NOT EXISTS kw_assist_business_media_sends (
 business_id BIGINT NOT NULL REFERENCES businesses(id), event_key TEXT NOT NULL,
 scope_id TEXT NOT NULL, file_id BIGINT NOT NULL, version TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','attempting','accepted','suppressed','unknown')),
 provider_id TEXT, created_at BIGINT NOT NULL,
 PRIMARY KEY(business_id,event_key)
);
