CREATE TABLE IF NOT EXISTS kilas_ai_chat_model_selections (
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 surface TEXT NOT NULL CHECK(surface IN ('thread','conversation')),
 conversation_id BIGINT NOT NULL,
 model TEXT NOT NULL,
 PRIMARY KEY(user_id,surface,conversation_id)
);
CREATE TABLE IF NOT EXISTS kilas_ai_chat_model_results (
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 surface TEXT NOT NULL CHECK(surface IN ('thread','conversation')),
 message_id BIGINT NOT NULL,
 requested_model TEXT NOT NULL,
 returned_model TEXT NOT NULL,
 provider TEXT NOT NULL,
 PRIMARY KEY(user_id,surface,message_id)
);
