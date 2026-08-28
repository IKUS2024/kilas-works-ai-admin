-- Business Hub V2, Phase H (SQLite dialect) — human takeover state, per tenant + customer phone.
-- ADDITIVE ONLY. NOTE: this table is read/written entirely within client-hub for now — it is not
-- yet consulted by the production bot (../app.py); see BOT_INTEGRATION_GUIDE.md's Patch 4.

CREATE TABLE IF NOT EXISTS wa_conversation_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,           -- the authoritative WhatsApp identifier for this customer
    mode TEXT NOT NULL DEFAULT 'AI_ACTIVE', -- AI_ACTIVE | HUMAN_TAKEOVER
    updated_by_user_id INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(business_id, customer_phone)
);

CREATE INDEX IF NOT EXISTS idx_wa_conversation_state_business ON wa_conversation_state(business_id);
