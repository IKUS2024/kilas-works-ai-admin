-- Business Hub V2, Gap-fix Area E (PostgreSQL dialect). HONESTY NOTE: same as every other
-- *_postgres.sql file in this folder — hand-translated, not executed against a real Postgres
-- instance in this sandbox (no network access). ADDITIVE ONLY. See the _sqlite.sql sibling file
-- for the full design rationale (kept in one place rather than duplicated in both dialect files).
CREATE TABLE IF NOT EXISTS subscriptions (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL UNIQUE REFERENCES businesses(id),
    plan_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    grace_days INTEGER NOT NULL DEFAULT 3,
    grace_started_at TIMESTAMPTZ,
    reminder_stage TEXT,
    last_reminder_stage_at TIMESTAMPTZ,
    suspended_at TIMESTAMPTZ,
    reactivated_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_business ON subscriptions(business_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
