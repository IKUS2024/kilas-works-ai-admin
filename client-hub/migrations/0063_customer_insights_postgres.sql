-- Customer Insight structured memory. Additive and tenant-scoped.
CREATE TABLE IF NOT EXISTS kw_core_customer_insights (
    business_id INTEGER NOT NULL,
    customer_id TEXT NOT NULL,
    summary TEXT,
    known_name TEXT,
    business_name TEXT,
    location TEXT,
    needs TEXT,
    budget TEXT,
    intent TEXT,
    important_questions TEXT NOT NULL DEFAULT '[]',
    buying_signals TEXT NOT NULL DEFAULT '[]',
    unknowns TEXT NOT NULL DEFAULT '[]',
    follow_up TEXT,
    source_message_count INTEGER NOT NULL DEFAULT 0,
    source_last_at BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'STALE' CHECK(status IN ('STALE','READY','FAILED')),
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (business_id, customer_id),
    FOREIGN KEY (business_id, customer_id)
      REFERENCES kw_core_customers(business_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_kw_core_customer_insights_status
  ON kw_core_customer_insights(business_id,status,updated_at DESC);
