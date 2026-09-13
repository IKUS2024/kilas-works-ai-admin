CREATE TABLE IF NOT EXISTS business_knowledge_revisions (
 id BIGSERIAL PRIMARY KEY,
 business_id INTEGER NOT NULL REFERENCES businesses(id),
 snapshot_json TEXT NOT NULL,
 editor_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS business_knowledge_revisions_scope_idx ON business_knowledge_revisions (business_id, id);
