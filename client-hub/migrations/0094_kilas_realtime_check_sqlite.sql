CREATE TABLE IF NOT EXISTS kilas_realtime_checks (
 approval TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), key_digest TEXT NOT NULL,
 campaign TEXT NOT NULL REFERENCES kilas_vo_stt_campaigns(id), source_digest TEXT NOT NULL, model TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('DISPATCHED','UNKNOWN','VERIFIED','BLOCKED')),
 expected_pcm_ms INTEGER NOT NULL CHECK(expected_pcm_ms=5000), before_used BIGINT NOT NULL, before_limit BIGINT NOT NULL, after_used BIGINT, after_limit BIGINT, prepaid_guard INTEGER NOT NULL DEFAULT 1 CHECK(prepaid_guard=1),
 accepted INTEGER NOT NULL DEFAULT 0 CHECK(accepted IN (0,1)), attributed INTEGER NOT NULL DEFAULT 0 CHECK(attributed IN (0,1)),
 window_start_ms BIGINT NOT NULL, wire_end_ms BIGINT, comparison_end_ms BIGINT,
 actual_wire_ms INTEGER, sent_pcm_ms INTEGER CHECK(sent_pcm_ms>=0 AND sent_pcm_ms<=5000), before_overage_kind TEXT NOT NULL, after_overage_kind TEXT,
 result TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT
);
