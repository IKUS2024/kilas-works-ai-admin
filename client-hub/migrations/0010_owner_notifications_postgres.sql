-- Business Hub V2, Final Ecosystem Sync (Section 10/11/25). ADDITIVE ONLY. PostgreSQL dialect.
-- See 0010_owner_notifications_sqlite.sql for full rationale — identical shape.
CREATE TABLE IF NOT EXISTS owner_notifications (
    id SERIAL PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    entity_id INTEGER,
    business_id INTEGER,
    message TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'PENDING',
    sent_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_owner_notifications_status ON owner_notifications(delivery_status);
CREATE INDEX IF NOT EXISTS idx_owner_notifications_business ON owner_notifications(business_id);
