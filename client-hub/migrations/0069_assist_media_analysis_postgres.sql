-- Non-authoritative extraction candidates. Never an invoice or payment ledger.
CREATE TABLE IF NOT EXISTS kw_assist_media_analysis (
 business_id BIGINT NOT NULL REFERENCES businesses(id), media_key TEXT NOT NULL REFERENCES inbox_media(id),
 actor_id BIGINT NOT NULL REFERENCES users(id), status TEXT NOT NULL CHECK(status IN ('processing','ready','failed')),
 claim_token TEXT NOT NULL, result_json TEXT, content_hash TEXT, updated_at BIGINT NOT NULL,
 PRIMARY KEY(business_id,media_key)
);
