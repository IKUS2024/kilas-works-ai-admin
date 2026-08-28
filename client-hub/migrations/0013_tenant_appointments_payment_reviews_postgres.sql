-- Business Hub V2, tenant-persistence cycle (Tasks 1/2, PostgreSQL dialect). HONESTY NOTE: same as
-- every *_postgres.sql file in this folder — hand-translated, not executed against a real Postgres
-- instance. ADDITIVE ONLY. See 0013_..._sqlite.sql for the full design rationale (kept in one
-- place rather than duplicated in both dialect files).

CREATE TABLE IF NOT EXISTS tenant_appointments (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,
    customer_name TEXT,
    request_text TEXT,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_appointments_business ON tenant_appointments(business_id);
CREATE INDEX IF NOT EXISTS idx_tenant_appointments_business_phone ON tenant_appointments(business_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_tenant_appointments_status ON tenant_appointments(business_id, status);

CREATE TABLE IF NOT EXISTS tenant_payment_reviews (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,
    customer_name TEXT,
    amount_claimed BIGINT,
    amount_detected BIGINT,
    proof_file_id BIGINT REFERENCES project_files(id),
    status TEXT NOT NULL DEFAULT 'PENDING_OWNER_VERIFICATION',
    owner_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_at TIMESTAMPTZ,
    verified_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_tenant_payment_reviews_business ON tenant_payment_reviews(business_id);
CREATE INDEX IF NOT EXISTS idx_tenant_payment_reviews_business_status ON tenant_payment_reviews(business_id, status);
