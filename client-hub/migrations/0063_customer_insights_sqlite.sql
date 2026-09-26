-- Additive per-customer AI insight cache. No existing CRM/chat rows are modified.
CREATE TABLE IF NOT EXISTS kw_core_customer_insights (
    business_id INTEGER NOT NULL,
    customer_id TEXT NOT NULL,
    insight_json TEXT NOT NULL,
    core_message_cursor INTEGER NOT NULL DEFAULT 0,
    demo_message_cursor INTEGER NOT NULL DEFAULT 0,
    analyzed_message_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (business_id, customer_id),
    FOREIGN KEY (business_id, customer_id)
        REFERENCES kw_core_customers(business_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kw_core_customer_insights_updated
    ON kw_core_customer_insights(business_id, updated_at DESC);
