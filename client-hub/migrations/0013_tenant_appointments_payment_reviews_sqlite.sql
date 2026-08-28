-- Business Hub V2, tenant-persistence cycle (Tasks 1/2, SQLite dialect). ADDITIVE ONLY.
--
-- Moves two Pro tenant features that were previously ONLY backed by ../app.py's in-process
-- Python dicts (tenant_meeting_requests, and no persistence at all for payment-proof review) onto
-- real, durable, tenant-scoped storage in Client Hub's own database — the natural home for
-- durable tenant-scoped data, same as business_profiles/projects/etc.
--
-- Both tables are COMPLETELY SEPARATE from Kilas Works' own platform-billing tables (invoices,
-- payments, project_files kind='PAYMENT_PROOF') added in migration 0005 — those record a CLIENT
-- BUSINESS paying KILAS WORKS for its subscription/project, verified by Kilas Works' own admin
-- team (routes_admin.py/payment_service.py/ai_payment_review.py). tenant_payment_reviews below
-- records a CLIENT BUSINESS'S OWN CUSTOMER paying THAT BUSINESS directly (e.g. a coffee shop's
-- customer transferring for their order) — verified by that business's own owner via WhatsApp.
-- The two flows never share a table, a notification path, or an owner-command handler.
--
-- tenant_appointments — one row per booking request/negotiation for a tenant's own customer.
-- Status values are exactly the ones the bot's actual flow uses (request/reschedule/cancel/
-- confirm) — no speculative extra states.
CREATE TABLE IF NOT EXISTS tenant_appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,
    customer_name TEXT,
    request_text TEXT,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tenant_appointments_business ON tenant_appointments(business_id);
CREATE INDEX IF NOT EXISTS idx_tenant_appointments_business_phone ON tenant_appointments(business_id, customer_phone);
CREATE INDEX IF NOT EXISTS idx_tenant_appointments_status ON tenant_appointments(business_id, status);

-- tenant_payment_reviews — one row per payment-proof image a tenant's own customer sends. Never
-- claims authenticity (see ai_payment_review.py's docstring for the SAME strict rule applied to
-- Kilas Works' own platform-payment flow) — amount_detected is a best-effort AI reading of the
-- image, always subordinate to the tenant owner's own manual CONFIRMED/REJECTED decision.
-- proof_file_id reuses the EXISTING project_files storage table/pattern (kind='TENANT_PAYMENT_PROOF',
-- project_id left NULL since this isn't tied to any Kilas Works Business Hub project) rather than
-- inventing a second blob-storage mechanism.
CREATE TABLE IF NOT EXISTS tenant_payment_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,
    customer_name TEXT,
    amount_claimed INTEGER,
    amount_detected INTEGER,
    proof_file_id INTEGER REFERENCES project_files(id),
    status TEXT NOT NULL DEFAULT 'PENDING_OWNER_VERIFICATION',
    owner_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    verified_at TEXT,
    verified_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_tenant_payment_reviews_business ON tenant_payment_reviews(business_id);
CREATE INDEX IF NOT EXISTS idx_tenant_payment_reviews_business_status ON tenant_payment_reviews(business_id, status);
