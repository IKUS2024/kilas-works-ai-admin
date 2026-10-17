CREATE TABLE IF NOT EXISTS kilas_ai_image_model_selections (
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 surface TEXT NOT NULL CHECK(surface IN ('thread','conversation')),
 conversation_id BIGINT NOT NULL,
 model TEXT NOT NULL,
 PRIMARY KEY(user_id,surface,conversation_id)
);
