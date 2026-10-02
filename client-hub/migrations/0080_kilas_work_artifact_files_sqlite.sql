-- Work artifacts cannot depend on deletable Chat threads. Keep bytes outside TEXT metadata.
CREATE TABLE IF NOT EXISTS kilas_agent_artifact_files (
 artifact_id INTEGER PRIMARY KEY REFERENCES kilas_agent_artifacts(id) ON DELETE CASCADE,
 content BLOB NOT NULL, byte_size INTEGER NOT NULL CHECK(byte_size > 0 AND byte_size <= 8388608)
);
