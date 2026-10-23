CREATE TABLE IF NOT EXISTS kilas_chat_request_payloads (
 user_id BIGINT NOT NULL REFERENCES users(id), operation_key TEXT NOT NULL,
 conversation_id BIGINT NOT NULL REFERENCES kilas_ai_conversations(id), fingerprint TEXT NOT NULL,
 PRIMARY KEY(user_id,operation_key)
);
CREATE TABLE IF NOT EXISTS kilas_chat_context_checkpoints (
 user_id BIGINT NOT NULL REFERENCES users(id), conversation_id BIGINT NOT NULL REFERENCES kilas_ai_conversations(id),
 through_id BIGINT NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(user_id,conversation_id)
);
