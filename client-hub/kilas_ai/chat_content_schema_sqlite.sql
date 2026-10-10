CREATE TABLE IF NOT EXISTS kilas_chat_demo_recordings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 conversation_id INTEGER NOT NULL REFERENCES kilas_ai_conversations(id), label TEXT NOT NULL,
 fixture TEXT NOT NULL, transcript_version INTEGER NOT NULL DEFAULT 1,
 operation_key TEXT NOT NULL, UNIQUE(user_id,operation_key)
);
CREATE TABLE IF NOT EXISTS kilas_chat_demo_transcripts (
 recording_id INTEGER NOT NULL REFERENCES kilas_chat_demo_recordings(id),
 version INTEGER NOT NULL, content TEXT NOT NULL, operation_key TEXT NOT NULL,
 PRIMARY KEY(recording_id,version), UNIQUE(recording_id,operation_key)
);
CREATE TABLE IF NOT EXISTS kilas_chat_demo_projects (
 user_id INTEGER NOT NULL REFERENCES users(id), conversation_id INTEGER NOT NULL REFERENCES kilas_ai_conversations(id),
 project_id INTEGER NOT NULL REFERENCES kilas_content_projects(id), PRIMARY KEY(user_id,conversation_id)
);
CREATE TABLE IF NOT EXISTS kilas_chat_demo_actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 conversation_id INTEGER NOT NULL REFERENCES kilas_ai_conversations(id),
 recording_id INTEGER NOT NULL REFERENCES kilas_chat_demo_recordings(id), transcript_version INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('translate','voice','project_script')),
 language TEXT NOT NULL, source_action_id INTEGER REFERENCES kilas_chat_demo_actions(id),
 status TEXT NOT NULL DEFAULT 'COMPLETED' CHECK(status IN ('COMPLETED','CANCELLED')),
 output_text TEXT NOT NULL, project_id INTEGER, project_script_version INTEGER,
 operation_key TEXT NOT NULL, payload_hash TEXT NOT NULL, UNIQUE(user_id,operation_key)
);
