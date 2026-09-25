-- Kilas V2 Phase 3 — durable Customers / CRM foundation (SQLite). ADDITIVE ONLY.
-- Requires Phase 2 public web chat schema 0055. Never stores raw WEB visitor tokens.

CREATE TABLE IF NOT EXISTS kw_core_customers (
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    notes TEXT,
    source_channel TEXT NOT NULL DEFAULT 'WEB',
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    last_activity_at BIGINT NOT NULL,
    PRIMARY KEY (business_id, id)
);

CREATE INDEX IF NOT EXISTS idx_kw_core_customers_activity
    ON kw_core_customers(business_id, last_activity_at DESC);

CREATE TABLE IF NOT EXISTS kw_core_customer_identities (
    business_id INTEGER NOT NULL,
    customer_id TEXT NOT NULL,
    identity_type TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
    created_at BIGINT NOT NULL,
    PRIMARY KEY (business_id, identity_type, identity_hash),
    FOREIGN KEY (business_id, customer_id)
        REFERENCES kw_core_customers(business_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kw_core_customer_identity_customer
    ON kw_core_customer_identities(business_id, customer_id);

CREATE TABLE IF NOT EXISTS kw_web_customer_links (
    business_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY (business_id, conversation_id),
    FOREIGN KEY (business_id, conversation_id)
        REFERENCES kw_web_conversations(business_id, id) ON DELETE CASCADE,
    FOREIGN KEY (business_id, customer_id)
        REFERENCES kw_core_customers(business_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kw_web_customer_links_customer
    ON kw_web_customer_links(business_id, customer_id);
