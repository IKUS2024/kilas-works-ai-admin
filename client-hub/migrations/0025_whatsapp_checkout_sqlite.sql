-- SQLite requires a lossless table rebuild to relax business_id; preserve all columns/IDs.
PRAGMA foreign_keys=OFF;
CREATE TABLE IF NOT EXISTS quotations_guest_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_number TEXT NOT NULL UNIQUE,   -- e.g. "QUO-2026-000123"
    business_id INTEGER REFERENCES businesses(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    scope TEXT,
    deliverables TEXT,
    quantity INTEGER,
    final_price INTEGER NOT NULL,            -- always set explicitly by a KILAS_ADMIN — never inferred
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT',    -- DRAFT|SENT|VIEWED|APPROVED|REJECTED|EXPIRED
    created_by_user_id INTEGER REFERENCES users(id),
    updated_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    viewed_at TEXT,
    responded_at TEXT
);

INSERT INTO quotations_guest_new SELECT * FROM quotations;
DROP TABLE quotations;
ALTER TABLE quotations_guest_new RENAME TO quotations;
CREATE INDEX IF NOT EXISTS idx_quotations_business ON quotations(business_id);
CREATE INDEX IF NOT EXISTS idx_quotations_project ON quotations(project_id);
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS wa_checkout_customers (phone_hash TEXT PRIMARY KEY, active_session_id TEXT);
CREATE TABLE IF NOT EXISTS wa_checkout_sessions (
    session_id TEXT PRIMARY KEY,
    phone_hash TEXT NOT NULL REFERENCES wa_checkout_customers(phone_hash),
    customer_phone TEXT NOT NULL,
    customer_name TEXT,
    catalog_key TEXT NOT NULL,
    project_id BIGINT NOT NULL UNIQUE REFERENCES projects(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at BIGINT NOT NULL,
    last_message_hash TEXT,
    pending_field TEXT,
    UNIQUE(phone_hash, catalog_key)
);
CREATE INDEX IF NOT EXISTS idx_wa_checkout_phone ON wa_checkout_sessions(phone_hash);
