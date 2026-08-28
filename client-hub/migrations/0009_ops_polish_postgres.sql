-- Business Hub V2, Final Operations Polish (PostgreSQL dialect). ADDITIVE ONLY.
-- See 0009_ops_polish_sqlite.sql for the full rationale.

CREATE TABLE IF NOT EXISTS platform_assets (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BYTEA NOT NULL,
    uploaded_by_user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE talents ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 0;
ALTER TABLE talents ADD COLUMN IF NOT EXISTS availability_note TEXT;
ALTER TABLE talents ADD COLUMN IF NOT EXISTS profile_image_asset_id BIGINT REFERENCES platform_assets(id);

ALTER TABLE service_catalog ADD COLUMN IF NOT EXISTS cta_text TEXT;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES projects(id);

CREATE INDEX IF NOT EXISTS idx_audit_log_project ON audit_log(project_id);
