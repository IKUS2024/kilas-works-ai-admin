-- Business Hub V2, Absolute Final Production Patch. ADDITIVE ONLY. SQLite dialect.
--
-- Two unrelated additive changes bundled into one migration (both are small, both are needed for
-- this cycle, neither touches an existing column/row):
--
-- 1. owner_notifications gets delivery-attempt bookkeeping so the immediate-delivery path (see
--    owner_notification_delivery.py) and the fallback retry sweep (/cron/owner-notifications) can
--    both report/inspect how many times a row has been tried and when, without changing the
--    existing delivery_status vocabulary (PENDING/SENT/FAILED) or any existing column.
--
-- 2. catalog_cache: a single-row version counter. Bumped every time an admin edits the service
--    catalog or a talent record (price/active-state/follower-count/etc.) so the live-generated
--    catalog PDF (live_catalog_pdf.py) knows its cached file is stale without re-generating the
--    PDF on every single request.
ALTER TABLE owner_notifications ADD COLUMN delivery_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE owner_notifications ADD COLUMN last_attempted_at TEXT;

CREATE TABLE IF NOT EXISTS catalog_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT OR IGNORE INTO catalog_cache (id, version) VALUES (1, 0);
