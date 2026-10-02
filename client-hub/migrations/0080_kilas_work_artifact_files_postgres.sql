-- Additive binary extension; existing artifact/job ownership is authoritative.
CREATE TABLE IF NOT EXISTS kilas_agent_artifact_files (
 artifact_id BIGINT PRIMARY KEY REFERENCES kilas_agent_artifacts(id) ON DELETE CASCADE,
 content BYTEA NOT NULL, byte_size BIGINT NOT NULL CHECK(byte_size > 0 AND byte_size <= 8388608)
);
