-- Unified AI Brain v2, Section 1: official links (landing page, app.kilasworks.id, Instagram,
-- demo/portfolio) must be admin-editable, not hardcoded duplicated into multiple prompts. No
-- existing generic key-value settings table exists anywhere in this schema (confirmed by audit)
-- to reuse for this — every existing config table is narrowly typed for one specific purpose
-- (ai_settings, tenant_whatsapp_config, service_catalog, etc.), none of which fits a small set of
-- admin-editable platform-level text values. This is a GENUINE, minimal, additive gap: one simple
-- key-value table, reusable for any FUTURE admin-editable platform-level setting too (not
-- single-purpose to links specifically), so it doesn't need to be redone if another such setting
-- comes up later.
CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
