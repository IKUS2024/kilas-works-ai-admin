CREATE TABLE IF NOT EXISTS kilas_thread_request_payloads (
 user_id BIGINT NOT NULL REFERENCES users(id), operation_key TEXT NOT NULL,
 thread_id BIGINT NOT NULL REFERENCES kilas_ai_threads(id) ON DELETE CASCADE, fingerprint TEXT NOT NULL,
 PRIMARY KEY(user_id,operation_key)
);
CREATE TABLE IF NOT EXISTS kilas_thread_context_checkpoints (
 user_id BIGINT NOT NULL REFERENCES users(id), thread_id BIGINT NOT NULL REFERENCES kilas_ai_threads(id) ON DELETE CASCADE,
 through_id BIGINT NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(user_id,thread_id)
);
