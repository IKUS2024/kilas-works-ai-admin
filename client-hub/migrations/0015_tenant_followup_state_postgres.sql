-- Business Hub V2, Gap-fix Area F (PostgreSQL dialect). HONESTY NOTE: same as every other
-- *_postgres.sql file in this folder — hand-translated, not executed against a real Postgres
-- instance in this sandbox (no network access). ADDITIVE ONLY. See the _sqlite.sql sibling file
-- for the full design rationale (kept in one place rather than duplicated in both dialect files).
CREATE TABLE IF NOT EXISTS tenant_followup_state (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,
    last_customer_msg_at TIMESTAMPTZ,
    last_followup_at TIMESTAMPTZ,
    followup_count INTEGER NOT NULL DEFAULT 0,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (business_id, customer_phone)
);

CREATE INDEX IF NOT EXISTS idx_tenant_followup_state_business ON tenant_followup_state(business_id);
CREATE INDEX IF NOT EXISTS idx_tenant_followup_state_business_phone ON tenant_followup_state(business_id, customer_phone);
