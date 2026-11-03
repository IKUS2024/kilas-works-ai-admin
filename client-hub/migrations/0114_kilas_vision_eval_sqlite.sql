CREATE TABLE IF NOT EXISTS kilas_ai_vision_eval_claims (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 batch TEXT NOT NULL,
 sequence INTEGER NOT NULL CHECK(sequence BETWEEN 1 AND 8),
 thread_id INTEGER NOT NULL,
 message_id INTEGER NOT NULL,
 config_fingerprint TEXT NOT NULL,
 PRIMARY KEY(batch,sequence),
 UNIQUE(user_id,thread_id),
 UNIQUE(user_id,message_id)
);
