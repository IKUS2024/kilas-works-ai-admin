CREATE TABLE IF NOT EXISTS kilas_audio_saved_voices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, voice_id TEXT NOT NULL, preview_content BLOB,
 operation_key TEXT NOT NULL, consent_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(user_id, voice_id), UNIQUE(user_id, operation_key)
);
