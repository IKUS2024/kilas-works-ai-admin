-- Owner-scoped Agent conversation; no Finance or Assist rows are touched.
CREATE TABLE IF NOT EXISTS kilas_ai_agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_agent_messages_owner
    ON kilas_ai_agent_messages(user_id,id DESC);
