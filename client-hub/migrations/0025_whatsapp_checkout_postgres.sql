-- Additive guest access; existing orders, prices and verification remain unchanged.
ALTER TABLE quotations ALTER COLUMN business_id DROP NOT NULL;

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
