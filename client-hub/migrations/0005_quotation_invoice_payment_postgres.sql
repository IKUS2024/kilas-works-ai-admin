-- Business Hub V2, Phase C (PostgreSQL dialect). HONESTY NOTE: same as every *_postgres.sql file in
-- this folder — hand-translated, not executed against a real Postgres instance. ADDITIVE ONLY.

CREATE TABLE IF NOT EXISTS quotations (
    id BIGSERIAL PRIMARY KEY,
    quotation_number TEXT NOT NULL UNIQUE,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    project_id BIGINT NOT NULL REFERENCES projects(id),
    scope TEXT,
    deliverables TEXT,
    quantity INTEGER,
    final_price BIGINT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_by_user_id BIGINT REFERENCES users(id),
    updated_by_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    viewed_at TIMESTAMPTZ,
    responded_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS invoices (
    id BIGSERIAL PRIMARY KEY,
    invoice_number TEXT NOT NULL UNIQUE,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    project_id BIGINT NOT NULL REFERENCES projects(id),
    quotation_id BIGINT REFERENCES quotations(id),
    amount BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ISSUED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    invoice_id BIGINT NOT NULL REFERENCES invoices(id),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING',
    proof_file_id BIGINT REFERENCES project_files(id),
    ai_extracted_amount BIGINT,
    ai_extracted_date TEXT,
    ai_extracted_bank TEXT,
    ai_reference TEXT,
    ai_risk_flags_json JSONB,
    ai_match_score REAL,
    duplicate_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    admin_notes TEXT,
    verified_by_user_id BIGINT REFERENCES users(id),
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quotations_business ON quotations(business_id);
CREATE INDEX IF NOT EXISTS idx_quotations_project ON quotations(project_id);
CREATE INDEX IF NOT EXISTS idx_invoices_business ON invoices(business_id);
CREATE INDEX IF NOT EXISTS idx_invoices_project ON invoices(project_id);
CREATE INDEX IF NOT EXISTS idx_payments_business ON payments(business_id);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
