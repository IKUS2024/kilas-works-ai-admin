CREATE TABLE IF NOT EXISTS kilas_audio_balances (
 user_id BIGINT PRIMARY KEY REFERENCES users(id), seconds INTEGER NOT NULL DEFAULT 0 CHECK(seconds>=0)
);
CREATE TABLE IF NOT EXISTS kilas_audio_orders (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), invoice_number TEXT NOT NULL UNIQUE,
 pack TEXT NOT NULL CHECK(pack IN ('MINUTE','FIVE','TEN')), seconds INTEGER NOT NULL CHECK(seconds IN (60,300,600)),
 amount_idr INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING' CHECK(status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
 proof_filename TEXT, proof_mime_type TEXT, proof_content BYTEA, verified_by BIGINT REFERENCES users(id), verified_at TEXT, admin_note TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS kilas_audio_orders_owner ON kilas_audio_orders(user_id,id);
CREATE TABLE IF NOT EXISTS kilas_audio_jobs (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), operation_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('translate','voiceover')), title TEXT NOT NULL,
 source_language TEXT NOT NULL, target_language TEXT NOT NULL, voice_id TEXT NOT NULL DEFAULT '', voice_name TEXT NOT NULL DEFAULT '',
 script TEXT, source_ms INTEGER NOT NULL DEFAULT 0, source_content BYTEA,
 estimated_seconds INTEGER NOT NULL CHECK(estimated_seconds>0), reserved_seconds INTEGER NOT NULL CHECK(reserved_seconds>=0),
 actual_ms INTEGER NOT NULL DEFAULT 0, seconds_charged INTEGER NOT NULL DEFAULT 0 CHECK(seconds_charged>=0),
 status TEXT NOT NULL CHECK(status IN ('QUEUED','PROCESSING','COMPLETED','FAILED')),
 provider_id TEXT NOT NULL DEFAULT '', result_content BYTEA, error_code TEXT NOT NULL DEFAULT '', poll_until TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id,operation_key)
);
CREATE INDEX IF NOT EXISTS kilas_audio_jobs_owner ON kilas_audio_jobs(user_id,id);
