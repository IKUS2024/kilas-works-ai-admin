CREATE TABLE IF NOT EXISTS kilas_ai_conversations (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
 title TEXT NOT NULL DEFAULT 'Chat baru', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), archived_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS kilas_agent_conversations_owner ON kilas_ai_conversations(user_id,updated_at,id);
ALTER TABLE kilas_ai_agent_messages ADD COLUMN IF NOT EXISTS conversation_id BIGINT REFERENCES kilas_ai_conversations(id);
INSERT INTO kilas_ai_conversations(user_id,title)
 SELECT DISTINCT user_id,'Percakapan sebelumnya' FROM kilas_ai_agent_messages m WHERE conversation_id IS NULL
 AND NOT EXISTS (SELECT 1 FROM kilas_ai_conversations c WHERE c.user_id=m.user_id AND c.title='Percakapan sebelumnya');
UPDATE kilas_ai_agent_messages m SET conversation_id=(SELECT MIN(c.id) FROM kilas_ai_conversations c WHERE c.user_id=m.user_id AND c.title='Percakapan sebelumnya') WHERE conversation_id IS NULL;
CREATE INDEX IF NOT EXISTS kilas_agent_messages_conversation ON kilas_ai_agent_messages(user_id,conversation_id,id);
ALTER TABLE kilas_agent_jobs ADD COLUMN IF NOT EXISTS origin_conversation_id BIGINT REFERENCES kilas_ai_conversations(id);
ALTER TABLE kilas_agent_jobs ADD COLUMN IF NOT EXISTS schedule_json TEXT NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS kilas_agent_jobs_conversation ON kilas_agent_jobs(user_id,origin_conversation_id,id);
CREATE TABLE IF NOT EXISTS kilas_agent_chat_requests (
 user_id BIGINT NOT NULL REFERENCES users(id), conversation_id BIGINT NOT NULL REFERENCES kilas_ai_conversations(id),
 operation_key TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(user_id,operation_key)
);
