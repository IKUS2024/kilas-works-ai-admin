CREATE TABLE IF NOT EXISTS kilas_content_projects (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    brief TEXT NOT NULL DEFAULT '',
    script_version INTEGER NOT NULL DEFAULT 0 CHECK(script_version>=0),
    operation_key TEXT NOT NULL,
    UNIQUE(user_id,operation_key)
);
CREATE TABLE IF NOT EXISTS kilas_content_scripts (
    project_id BIGINT NOT NULL REFERENCES kilas_content_projects(id),
    version INTEGER NOT NULL CHECK(version>0),
    content TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('manual','video')),
    source_id BIGINT,
    source_version INTEGER,
    operation_key TEXT NOT NULL,
    PRIMARY KEY(project_id,version),
    UNIQUE(project_id,operation_key)
);
CREATE TABLE IF NOT EXISTS kilas_content_links (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES kilas_content_projects(id),
    kind TEXT NOT NULL CHECK(kind IN ('video','audio','conversation','thread')),
    target_id BIGINT NOT NULL,
    target_version INTEGER NOT NULL DEFAULT 0,
    script_version INTEGER NOT NULL DEFAULT 0 CHECK(script_version>=0),
    UNIQUE(project_id,kind,target_id,target_version,script_version)
);
