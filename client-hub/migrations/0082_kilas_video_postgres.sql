CREATE TABLE IF NOT EXISTS kilas_video_projects (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
 title TEXT NOT NULL, idea TEXT NOT NULL, options_json TEXT NOT NULL DEFAULT '{}',
 spec_json TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 0,
 operation_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'EMPTY',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
 UNIQUE(user_id, operation_key)
);
CREATE INDEX IF NOT EXISTS kilas_video_owner_history ON kilas_video_projects(user_id,updated_at,id);
CREATE TABLE IF NOT EXISTS kilas_video_revisions (
 project_id BIGINT NOT NULL REFERENCES kilas_video_projects(id), version INTEGER NOT NULL,
 instruction TEXT NOT NULL, spec_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(project_id,version)
);
CREATE TABLE IF NOT EXISTS kilas_video_references (
 id BIGSERIAL PRIMARY KEY, project_id BIGINT NOT NULL REFERENCES kilas_video_projects(id),
 filename TEXT NOT NULL, mime_type TEXT NOT NULL, byte_size INTEGER NOT NULL, content BYTEA NOT NULL
);
