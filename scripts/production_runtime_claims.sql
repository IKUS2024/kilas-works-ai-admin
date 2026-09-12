-- Apply to the same Postgres database used by the bot and Client Hub.
-- Also idempotently applied by app.init_db(). No existing rows are changed.
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_runtime_claim
ON messages (number, mode)
WHERE mode IN ('_webhook_claim', '_outbound_claim');
