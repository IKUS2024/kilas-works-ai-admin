-- Business Hub V2, Gap-fix Area F — tenant-scoped automatic follow-up state (SQLite dialect).
-- ADDITIVE ONLY.
--
-- WHY A NEW TABLE INSTEAD OF EXTENDING ../followup_state (the bot's own global table):
-- ../app.py's `followup_state` table lives in the BOT'S OWN database (its own get_db_connection(),
-- its own init_db(), keyed by bare phone `number` only — no business_id/tenant_id column at all)
-- and is used EXCLUSIVELY for Kilas Works' own prospecting/sales-engine follow-up
-- (send_appointment_reminders()/run_followups()'s global cron, see app.py's own comment at the
-- "if is_kilas_tenant: mark_customer_activity(...)" call site documenting this exact limitation).
-- Client Hub's database is a SEPARATE schema (its own db.py/get_connection()) that already owns
-- every other piece of tenant-scoped runtime state (tenant_appointments, tenant_payment_reviews,
-- tenant_whatsapp_config, subscriptions — see migrations 0007/0013/0014). Extending the bot's bare
-- `number`-keyed global table would require retrofitting a business_id column onto a table whose
-- entire existing row set (and every existing test/regression) assumes ONE global namespace, and
-- would put tenant follow-up state in a database the tenant/business truth (businesses,
-- tenant_whatsapp_config, subscriptions) doesn't live in — exactly the "duplicate customer/business
-- truth across databases" outcome to avoid. A new table in the SAME database that already holds
-- businesses/tenant_whatsapp_config/subscriptions, scoped by (business_id, customer_phone), keeps
-- one tenant's truth in one place and can never collide with Kilas Works' own global table (which
-- is untouched by this migration).
CREATE TABLE IF NOT EXISTS tenant_followup_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,
    last_customer_msg_at TEXT,
    last_followup_at TEXT,
    followup_count INTEGER NOT NULL DEFAULT 0,
    resolved BOOLEAN NOT NULL DEFAULT 0,
    resolved_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (business_id, customer_phone)
);

CREATE INDEX IF NOT EXISTS idx_tenant_followup_state_business ON tenant_followup_state(business_id);
CREATE INDEX IF NOT EXISTS idx_tenant_followup_state_business_phone ON tenant_followup_state(business_id, customer_phone);
