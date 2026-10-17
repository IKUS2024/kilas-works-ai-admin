CREATE TABLE IF NOT EXISTS kilas_workspace_streams (
 id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),
 conversation_id BIGINT NOT NULL REFERENCES kilas_ai_conversations(id),operation_key TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'RUNNING',cancel_requested INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,UNIQUE(user_id,operation_key)
);
CREATE INDEX IF NOT EXISTS idx_workspace_stream_owner ON kilas_workspace_streams(user_id,conversation_id,id);
CREATE TABLE IF NOT EXISTS kilas_workspace_stream_events (
 id BIGSERIAL PRIMARY KEY,stream_id BIGINT NOT NULL REFERENCES kilas_workspace_streams(id),
 payload TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_stream_event ON kilas_workspace_stream_events(stream_id,id);
