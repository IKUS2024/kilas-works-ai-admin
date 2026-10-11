CREATE TABLE IF NOT EXISTS kilas_live_translator_sessions (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), language_a TEXT NOT NULL, language_b TEXT NOT NULL,
 voice_alias TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ACTIVE','ENDED')), created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS kilas_live_translator_owner ON kilas_live_translator_sessions(user_id,status);
CREATE TABLE IF NOT EXISTS kilas_live_translator_turns (
 operation_key TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES kilas_live_translator_sessions(id),
 status TEXT NOT NULL CHECK(status IN ('PROCESSING','COMPLETED','FAILED','CANCELLED')), created_at TEXT NOT NULL,
 error_code TEXT, audio_job_id INTEGER REFERENCES kilas_audio_jobs(id)
);
