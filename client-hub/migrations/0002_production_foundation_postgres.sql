-- Kilas Works Client Hub — Production Foundation cycle, PostgreSQL dialect.
-- HONESTY NOTE: like 0001_init_postgres.sql, this file has NOT been executed against a real
-- Postgres instance (no network access to install/run Postgres in this sandbox) — it is a careful
-- hand-translation of 0002_production_foundation_sqlite.sql. Run the Client Hub test suite once
-- against a real Postgres instance before trusting this in production.
-- ADDITIVE ONLY. No table drops, no column drops.

CREATE TABLE IF NOT EXISTS tenant_configs (
    business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
    config_version INTEGER NOT NULL DEFAULT 1,
    config_json JSONB NOT NULL,
    provisioned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_whatsapp_config (
    business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
    connection_status TEXT NOT NULL DEFAULT 'NOT_CONNECTED',
    phone_number_id TEXT,
    waba_id TEXT,
    credentials_reference TEXT,
    connected_at TIMESTAMPTZ,
    validated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tenant_configs_version ON tenant_configs(config_version);
CREATE INDEX IF NOT EXISTS idx_whatsapp_config_status ON tenant_whatsapp_config(connection_status);
CREATE INDEX IF NOT EXISTS idx_whatsapp_config_phone_number_id ON tenant_whatsapp_config(phone_number_id);
CREATE INDEX IF NOT EXISTS idx_businesses_package ON businesses(package);
CREATE INDEX IF NOT EXISTS idx_users_email_lookup ON users(email);
CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_business ON onboarding_sessions(business_id);
CREATE INDEX IF NOT EXISTS idx_business_memberships_business ON business_memberships(business_id);

-- NOTE on config_json: stored as JSONB here (queryable/indexable in real Postgres) vs TEXT in the
-- SQLite dialect (SQLite has no native JSON type in this Python build). repo.py's
-- save_tenant_config()/get_tenant_config_row() always round-trip through json.dumps/json.loads in
-- Python either way, so this type difference is transparent to every caller.
