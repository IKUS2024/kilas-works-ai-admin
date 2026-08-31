-- Kilas Works platform-owned WhatsApp human takeover state (SQLite).
-- Separate from tenant wa_conversation_state because the Kilas Works legacy bot is not a client
-- business row and therefore has no businesses.id foreign key to reuse safely.
CREATE TABLE IF NOT EXISTS platform_wa_conversation_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_phone TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL DEFAULT 'AI_ACTIVE',
    updated_by_user_id INTEGER REFERENCES users(id),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_platform_wa_state_mode ON platform_wa_conversation_state(mode);
