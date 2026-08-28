-- Business Hub V2, Phase B (SQLite dialect) — service catalog + custom project/request model.
-- ADDITIVE ONLY.

CREATE TABLE IF NOT EXISTS service_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_key TEXT NOT NULL UNIQUE,       -- stable key, e.g. "ai_admin_basic" — see pricing_config.py
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    pricing_mode TEXT NOT NULL,             -- FIXED_PRICE | STARTING_FROM | CUSTOM_QUOTE
    price_amount INTEGER,                   -- smallest currency unit (whole IDR), NULL for CUSTOM_QUOTE
    price_unit TEXT,                        -- e.g. "per bulan", "one time" — NULL for CUSTOM_QUOTE
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Custom project / service requests. "projects" here also covers a FIXED_PRICE order once a
-- customer checks out (project_type mirrors service category) — one table for both, since the
-- master spec explicitly asked to avoid an overcomplicated separate cart/order model when
-- project-by-project tracking already covers it (Section 10/18).
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    project_type TEXT NOT NULL,             -- PHOTO|VIDEO|WEBSITE|APPLICATION|TALENT|CONTENT|ADS|EVENT|OTHER
    catalog_key TEXT,                       -- links to service_catalog.catalog_key for FIXED_PRICE items, NULL for pure custom
    pricing_mode TEXT NOT NULL,             -- FIXED_PRICE | CUSTOM_QUOTE (copied at creation time, catalog price can change later without rewriting history)
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    -- REQUESTED -> WAITING_FOR_QUOTE -> QUOTED -> APPROVED -> PAYMENT_PENDING -> PAID ->
    -- IN_PROGRESS -> WAITING_FOR_CLIENT -> REVISION -> COMPLETED -> CANCELLED
    requirements_json TEXT,                 -- structured brief fields (quantity, platform, location, etc.)
    budget_min INTEGER,
    budget_max INTEGER,
    final_price INTEGER,                    -- NULL until Kilas admin sets it via a quotation (never invented by the system)
    created_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    project_id INTEGER REFERENCES projects(id),
    kind TEXT NOT NULL,                     -- BRIEF | REFERENCE | PAYMENT_PROOF | TALENT_PHOTO
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BLOB NOT NULL,
    uploaded_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_projects_business ON projects(business_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_project_files_project ON project_files(project_id);
CREATE INDEX IF NOT EXISTS idx_service_catalog_active ON service_catalog(is_active);
