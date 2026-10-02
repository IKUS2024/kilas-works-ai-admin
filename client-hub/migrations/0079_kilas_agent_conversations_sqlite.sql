CREATE TABLE kilas_ai_conversations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 title TEXT NOT NULL DEFAULT 'Chat baru', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, archived_at TEXT
);
CREATE INDEX kilas_agent_conversations_owner ON kilas_ai_conversations(user_id,updated_at,id);
ALTER TABLE kilas_ai_agent_messages ADD COLUMN conversation_id INTEGER REFERENCES kilas_ai_conversations(id);
INSERT INTO kilas_ai_conversations(user_id,title)
 SELECT DISTINCT user_id,'Percakapan sebelumnya' FROM kilas_ai_agent_messages;
UPDATE kilas_ai_agent_messages SET conversation_id=(SELECT id FROM kilas_ai_conversations c WHERE c.user_id=kilas_ai_agent_messages.user_id);
CREATE INDEX kilas_agent_messages_conversation ON kilas_ai_agent_messages(user_id,conversation_id,id);
ALTER TABLE kilas_agent_jobs ADD COLUMN origin_conversation_id INTEGER REFERENCES kilas_ai_conversations(id);
ALTER TABLE kilas_agent_jobs ADD COLUMN schedule_json TEXT NOT NULL DEFAULT '{}';
CREATE INDEX kilas_agent_jobs_conversation ON kilas_agent_jobs(user_id,origin_conversation_id,id);
CREATE TABLE kilas_agent_chat_requests (
 user_id INTEGER NOT NULL REFERENCES users(id), conversation_id INTEGER NOT NULL REFERENCES kilas_ai_conversations(id),
 operation_key TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(user_id,operation_key)
);
