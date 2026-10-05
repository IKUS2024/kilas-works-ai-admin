CREATE TABLE IF NOT EXISTS kilas_audio_personal_voices (
 user_id INTEGER PRIMARY KEY REFERENCES users(id),
 voice_id TEXT NOT NULL DEFAULT '', operation_key TEXT NOT NULL DEFAULT '',
 claim_token TEXT NOT NULL DEFAULT '', claim_until TEXT NOT NULL DEFAULT '',
 consent_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ''
);
