-- Kilas customer relationship stages (SQLite). ADDITIVE ONLY.
-- Existing Phase 3 customer records are backfilled as CUSTOMER to preserve historical semantics.
-- New inbound contacts are explicitly created as LEAD by application code after this migration.

CREATE TABLE IF NOT EXISTS kw_core_customer_stages (
    business_id INTEGER NOT NULL,
    customer_id TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'LEAD' CHECK(stage IN ('LEAD','CUSTOMER')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (business_id, customer_id),
    FOREIGN KEY (business_id, customer_id)
        REFERENCES kw_core_customers(business_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kw_core_customer_stages_stage
    ON kw_core_customer_stages(business_id, stage, updated_at DESC);

INSERT OR IGNORE INTO kw_core_customer_stages(business_id, customer_id, stage, created_at, updated_at)
SELECT business_id, id, 'CUSTOMER', created_at, updated_at
FROM kw_core_customers;
