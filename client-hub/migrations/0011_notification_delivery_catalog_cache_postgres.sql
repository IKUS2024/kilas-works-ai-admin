-- Business Hub V2, Absolute Final Production Patch. ADDITIVE ONLY. PostgreSQL dialect.
-- See 0011_notification_delivery_catalog_cache_sqlite.sql for full rationale — identical shape.
ALTER TABLE owner_notifications ADD COLUMN IF NOT EXISTS delivery_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE owner_notifications ADD COLUMN IF NOT EXISTS last_attempted_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS catalog_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
INSERT INTO catalog_cache (id, version) VALUES (1, 0) ON CONFLICT (id) DO NOTHING;
