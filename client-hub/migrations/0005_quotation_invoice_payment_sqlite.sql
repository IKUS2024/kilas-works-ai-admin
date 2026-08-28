-- Business Hub V2, Phase C (SQLite dialect) — quotation + checkout + invoice + payment workflow.
-- ADDITIVE ONLY.

CREATE TABLE IF NOT EXISTS quotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quotation_number TEXT NOT NULL UNIQUE,   -- e.g. "QUO-2026-000123"
    business_id INTEGER NOT NULL REFERENCES businesses(id),
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

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE,     -- e.g. "INV-2026-000123"
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    quotation_id INTEGER REFERENCES quotations(id),  -- NULL for a FIXED_PRICE checkout (no quotation needed)
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ISSUED',   -- ISSUED|PAID|CANCELLED
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING',
    -- PAYMENT_PENDING|PROOF_UPLOADED|UNDER_REVIEW|VERIFIED|REJECTED
    proof_file_id INTEGER REFERENCES project_files(id),
    ai_extracted_amount INTEGER,
    ai_extracted_date TEXT,
    ai_extracted_bank TEXT,
    ai_reference TEXT,
    ai_risk_flags_json TEXT,
    ai_match_score REAL,
    duplicate_candidate INTEGER NOT NULL DEFAULT 0,
    admin_notes TEXT,
    verified_by_user_id INTEGER REFERENCES users(id),
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_quotations_business ON quotations(business_id);
CREATE INDEX IF NOT EXISTS idx_quotations_project ON quotations(project_id);
CREATE INDEX IF NOT EXISTS idx_invoices_business ON invoices(business_id);
CREATE INDEX IF NOT EXISTS idx_invoices_project ON invoices(project_id);
CREATE INDEX IF NOT EXISTS idx_payments_business ON payments(business_id);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
