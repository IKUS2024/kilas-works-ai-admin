-- Business Hub V2, Gap-fix Area E — AI Admin monthly SUBSCRIPTION lifecycle (SQLite dialect).
-- ADDITIVE ONLY. One row per business_id (UNIQUE), tracking ONLY the recurring AI Admin
-- subscription (plan_key 'ai_admin_basic' / 'ai_admin_pro') — completely separate from and never
-- read/written by projects_repo.py's creative-service (PHOTO/VIDEO/CONTENT/TALENT/EVENT) rows,
-- which stay project-based and keep working regardless of this table's contents (see
-- subscription_service.py's module docstring for the full lifecycle design).
--
-- Lifecycle: ACTIVE -> (period_end near/passed) reminder/GRACE -> (grace_days elapsed) SUSPENDED
-- -> (renewal payment recorded) ACTIVE again. Suspension NEVER deletes/touches any other table —
-- see subscription_service.run_lifecycle_sweep()'s docstring.
--
-- NAMING NOTE (accuracy fix): `last_reminder_stage_at` records when `reminder_stage` last
-- ADVANCED (H7/H3/H1) — it does NOT mean a WhatsApp/email message was actually delivered. No
-- outbound notification is sent by this table/module today; the stage change only surfaces on
-- the tenant's own Client Hub dashboard banner (get_subscription_banner()). Deliberately NOT
-- named `..._sent_at` to avoid implying a delivery guarantee that doesn't exist.
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL UNIQUE REFERENCES businesses(id),
    plan_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    grace_days INTEGER NOT NULL DEFAULT 3,
    grace_started_at TEXT,
    reminder_stage TEXT,
    last_reminder_stage_at TEXT,
    suspended_at TEXT,
    reactivated_at TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_business ON subscriptions(business_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
