CREATE TABLE IF NOT EXISTS kilas_chat_request_payloads (
 user_id INTEGER NOT NULL REFERENCES users(id), operation_key TEXT NOT NULL,
 conversation_id INTEGER NOT NULL REFERENCES kilas_ai_conversations(id), fingerprint TEXT NOT NULL,
 PRIMARY KEY(user_id,operation_key)
);
CREATE TABLE IF NOT EXISTS kilas_chat_context_checkpoints (
 user_id INTEGER NOT NULL REFERENCES users(id), conversation_id INTEGER NOT NULL REFERENCES kilas_ai_conversations(id),
 through_id INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(user_id,conversation_id)
);
