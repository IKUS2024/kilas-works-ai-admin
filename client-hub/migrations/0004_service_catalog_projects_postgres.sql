-- Business Hub V2, Phase B (PostgreSQL dialect) — service catalog + custom project/request model.
-- HONESTY NOTE: hand-translated, not executed against a real Postgres instance from this sandbox
-- (same caveat as every other *_postgres.sql migration in this folder). ADDITIVE ONLY.
-- BOOLEAN columns use real BOOLEAN + parameterized True/False, per the lesson learned in the
-- Postgres Validation cycle — never a literal 1/0.

CREATE TABLE IF NOT EXISTS service_catalog (
    id BIGSERIAL PRIMARY KEY,
    catalog_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    pricing_mode TEXT NOT NULL,
    price_amount BIGINT,
    price_unit TEXT,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    project_type TEXT NOT NULL,
    catalog_key TEXT,
    pricing_mode TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    requirements_json JSONB,
    budget_min BIGINT,
    budget_max BIGINT,
    final_price BIGINT,
    created_by_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_files (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    project_id BIGINT REFERENCES projects(id),
    kind TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    content BYTEA NOT NULL,
    uploaded_by_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_business ON projects(business_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_project_files_project ON project_files(project_id);
CREATE INDEX IF NOT EXISTS idx_service_catalog_active ON service_catalog(is_active);
