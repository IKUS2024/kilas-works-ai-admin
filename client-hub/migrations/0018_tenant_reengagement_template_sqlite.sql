-- Tenant-scoped WhatsApp re-engagement template override (Inbox unification follow-up fix).
--
-- WHY: the approved-template send path previously only read ONE global configuration
-- (WHATSAPP_REENGAGEMENT_TEMPLATE_NAME / _LANGUAGE env vars), shared across Kilas Works AND every
-- tenant. A tenant business does not necessarily have the same approved Meta template as Kilas
-- Works (or as any other tenant) — forcing one shared template name would either fail for tenants
-- who never got that exact template approved, or require every tenant to coordinate on one name,
-- neither of which is realistic. These two ADDITIVE, NULLABLE columns let an individual tenant
-- override the template name/language for ITS OWN re-engagement sends; NULL (the default) means
-- "no tenant-specific override", which correctly falls through to the global env-var config (see
-- wa_inbox_shared.resolve_reengagement_template_config_for_tenant()'s own docstring for the full
-- resolution order). Additive only — never drops/renames anything, existing rows are unaffected
-- (both columns simply read NULL, i.e. "use global fallback", for every tenant that predates this
-- migration).
ALTER TABLE tenant_whatsapp_config ADD COLUMN reengagement_template_name TEXT;
ALTER TABLE tenant_whatsapp_config ADD COLUMN reengagement_template_language TEXT;
