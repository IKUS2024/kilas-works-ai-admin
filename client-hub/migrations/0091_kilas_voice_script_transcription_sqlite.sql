CREATE TABLE IF NOT EXISTS kilas_vo_stt_campaigns (
 id TEXT PRIMARY KEY, global_micro INTEGER NOT NULL CHECK(global_micro>0), account_micro INTEGER NOT NULL CHECK(account_micro>0),
 expires_at TEXT NOT NULL, price_version TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1))
);
CREATE TABLE IF NOT EXISTS kilas_vo_stt_operations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), operation_key TEXT NOT NULL,
 campaign TEXT NOT NULL REFERENCES kilas_vo_stt_campaigns(id), fingerprint TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RESERVED','DISPATCHED','COMPLETED','FAILED','CANCELLED','UNKNOWN')),
 charge_micro INTEGER NOT NULL CHECK(charge_micro>=0), duration_ms INTEGER NOT NULL CHECK(duration_ms>=0 AND duration_ms<=600000),
 lease_digest TEXT NOT NULL, actual_estimate_micro INTEGER, input_tokens INTEGER, output_tokens INTEGER,
 created_at TEXT NOT NULL, dispatched_at TEXT, finished_at TEXT, UNIQUE(user_id,operation_key)
);
CREATE INDEX IF NOT EXISTS kilas_vo_stt_campaign_usage ON kilas_vo_stt_operations(campaign,user_id,created_at);
