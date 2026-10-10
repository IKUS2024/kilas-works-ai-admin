CREATE TABLE IF NOT EXISTS kilas_chat_transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    conversation_id INTEGER NOT NULL REFERENCES kilas_ai_conversations(id),
    project_id INTEGER NOT NULL REFERENCES kilas_content_projects(id),
    operation_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PROCESSING','COMPLETED','FAILED','CANCELLED')),
    duration_ms INTEGER NOT NULL CHECK(duration_ms>0 AND duration_ms<=180000),
    text TEXT NOT NULL DEFAULT '',
    usage_json TEXT NOT NULL DEFAULT '{}',
    consent_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id,operation_key)
);
