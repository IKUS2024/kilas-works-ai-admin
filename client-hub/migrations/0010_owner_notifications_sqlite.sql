-- Business Hub V2, Final Ecosystem Sync (Section 10/11/25). ADDITIVE ONLY. SQLite dialect.
--
-- owner_notifications: an idempotency ledger for owner-facing WhatsApp notifications about
-- important ecosystem events (AI onboarding ready for review, custom project submitted, talent
-- request submitted, quotation approved, payment proof uploaded, WhatsApp-connection-ready,
-- human-attention escalation). `event_key` is UNIQUE — a logical event (e.g. "payment proof
-- uploaded for payment #42") can only ever have ONE row here, so calling the trigger point twice
-- (webhook retry, duplicate form submit, restart re-processing) never sends the notification
-- twice. See owner_notifications.py for the check-then-insert-before-send logic that relies on
-- this uniqueness.
CREATE TABLE IF NOT EXISTS owner_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    entity_id INTEGER,
    business_id INTEGER,
    message TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING | SENT | FAILED
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_owner_notifications_status ON owner_notifications(delivery_status);
CREATE INDEX IF NOT EXISTS idx_owner_notifications_business ON owner_notifications(business_id);
