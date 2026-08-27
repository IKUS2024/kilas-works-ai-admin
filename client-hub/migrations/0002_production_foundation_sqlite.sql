-- Kilas Works Client Hub — Production Foundation cycle (Phase 1/2 of "NEXT PHASE" request).
-- ADDITIVE ONLY. No table drops, no column drops, nothing from 0001 is touched. Runs after
-- 0001_init_sqlite.sql on every app boot (see db.py's MIGRATIONS list) — safe to re-run.

-- Phase 2: materialized, versioned production tenant configuration. This is DISTINCT from
-- ai_settings.normalized_config_json (Claude's raw normalization output) — this table holds the
-- ASSEMBLED config (profile + services + faqs + features + whatsapp status) that
-- tenant_config_service.py serves to the future bot integration. Built/updated exclusively by
-- provisioning.py's provision_tenant(), never written directly by routes.
CREATE TABLE IF NOT EXISTS tenant_configs (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    config_version INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL,
    provisioned_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Phase 2: WhatsApp connection state, kept separate from `businesses` so the "secret reference"
-- design is contained to one clearly-named table. `credentials_reference` is NEVER the actual
-- WhatsApp access token — it is a pointer to where the real secret lives (e.g. an environment
-- variable name like "WHATSAPP_TOKEN__TENANT_7", or a secret-manager key), resolved server-side
-- only by the bot runtime at send-time. This table is additive alongside the existing
-- businesses.whatsapp_connected/whatsapp_phone_number_id/trusted_owner_phone columns from 0001
-- (kept for backward compatibility with V1 code and tests) — see the final report for the
-- consolidation plan.
CREATE TABLE IF NOT EXISTS tenant_whatsapp_config (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    connection_status TEXT NOT NULL DEFAULT 'NOT_CONNECTED', -- NOT_CONNECTED | PENDING_VALIDATION | CONNECTED
    phone_number_id TEXT,
    waba_id TEXT,
    credentials_reference TEXT,   -- pointer to the secret, NEVER the secret itself
    connected_at TEXT,
    validated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tenant_configs_version ON tenant_configs(config_version);
CREATE INDEX IF NOT EXISTS idx_whatsapp_config_status ON tenant_whatsapp_config(connection_status);
CREATE INDEX IF NOT EXISTS idx_whatsapp_config_phone_number_id ON tenant_whatsapp_config(phone_number_id);
CREATE INDEX IF NOT EXISTS idx_businesses_package ON businesses(package);
CREATE INDEX IF NOT EXISTS idx_users_email_lookup ON users(email);
CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_business ON onboarding_sessions(business_id);
CREATE INDEX IF NOT EXISTS idx_business_memberships_business ON business_memberships(business_id);
