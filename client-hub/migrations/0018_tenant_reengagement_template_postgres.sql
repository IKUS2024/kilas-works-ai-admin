-- Tenant-scoped WhatsApp re-engagement template override (Inbox unification follow-up fix,
-- PostgreSQL side — see the _sqlite.sql sibling file for the full rationale).
ALTER TABLE tenant_whatsapp_config ADD COLUMN IF NOT EXISTS reengagement_template_name TEXT;
ALTER TABLE tenant_whatsapp_config ADD COLUMN IF NOT EXISTS reengagement_template_language TEXT;
