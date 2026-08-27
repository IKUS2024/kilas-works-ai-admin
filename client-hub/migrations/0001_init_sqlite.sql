-- Kilas Works Client Hub — initial schema (SQLite dialect, used for local dev/test in this sandbox).
-- ADDITIVE ONLY. No table drops. See 0001_init_postgres.sql for the production-equivalent schema.
--
-- Design notes:
--   - Every tenant-owned table carries business_id (the tenant_id) as a foreign key, and every
--     query in repo.py filters by it explicitly — this is the tenant isolation boundary.
--   - "businesses" IS the tenant. business.id == tenant_id throughout this codebase and in the
--     tenant_config_service.py interface meant for the existing bot to consume later.
--   - RAW client input and AI-NORMALIZED output are stored in separate columns/tables (never
--     overwritten in place) so a Kilas Admin can always see what the client actually typed
--     vs what Claude produced from it (section 9 of the request).

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'CLIENT_OWNER', -- 'KILAS_ADMIN' or 'CLIENT_OWNER'
    full_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,           -- this IS the tenant_id
    tenant_slug TEXT NOT NULL UNIQUE,                -- e.g. "tenant_000123", stable, never reused
    business_name TEXT NOT NULL,
    package TEXT NOT NULL DEFAULT 'AI_ADMIN_BASIC',  -- 'AI_ADMIN_BASIC' or 'AI_ADMIN_PRO'
    status TEXT NOT NULL DEFAULT 'DRAFT',
    -- DRAFT -> ONBOARDING -> READY_FOR_AI_SETUP -> READY_FOR_REVIEW -> APPROVED -> ACTIVE
    -- side-states: NEEDS_REVISION, SUSPENDED
    whatsapp_connected INTEGER NOT NULL DEFAULT 0,   -- 0/1 — manual step by Kilas Admin (section 30)
    whatsapp_phone_number_id TEXT,                   -- filled in manually by Kilas Admin at go-live
    trusted_owner_phone TEXT,                        -- this tenant's OWN owner number (section 21)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS business_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role_in_business TEXT NOT NULL DEFAULT 'OWNER',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(business_id, user_id)
);

-- STEP 1 — Business Basics (raw client input, one row per business, replaced on re-submit but
-- previous raw value is kept in onboarding_sessions.raw_payload for audit — see below).
CREATE TABLE IF NOT EXISTS business_profiles (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    category TEXT,
    short_description TEXT,
    country TEXT,
    timezone TEXT,
    address TEXT,
    business_phone TEXT,
    owner_name TEXT,
    primary_language TEXT DEFAULT 'id',              -- 'id' or 'en'
    additional_languages TEXT,                        -- JSON array, e.g. '["en"]'
    tone TEXT DEFAULT 'friendly',                      -- 'formal' | 'friendly' | 'casual-professional'
    customer_salutation TEXT DEFAULT 'Kak',
    operating_hours TEXT,                              -- JSON, raw client text or structured
    closed_days TEXT,
    online_or_offline TEXT,                            -- 'online' | 'offline' | 'both'
    appointment_rules_raw TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- STEP 2 — Products/Services. Both raw and normalized fields live on the same row: raw_* is what
-- the client typed, the rest is what Claude produced. needs_review=1 means Claude could not
-- confidently normalize this row (e.g. ambiguous price) and a Kilas Admin must resolve it by hand.
CREATE TABLE IF NOT EXISTS business_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    raw_input TEXT NOT NULL,
    service_name TEXT,
    description TEXT,
    price_from INTEGER,           -- smallest currency unit (e.g. IDR whole rupiah), NULL if unknown
    price_to INTEGER,
    currency TEXT DEFAULT 'IDR',
    notes TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- STEP 4 — FAQs / policies. Same raw-vs-normalized pattern.
CREATE TABLE IF NOT EXISTS business_faqs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    raw_input TEXT NOT NULL,
    question TEXT,
    answer TEXT,
    category TEXT DEFAULT 'general', -- 'general' | 'policy' | 'shipping' | 'booking'
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- STEP 6 — Uploaded business material. File BYTES are stored in the DB for V1 (see final report,
-- section on DB/storage choice, for why — no object storage configured yet, and Render's own disk
-- is ephemeral so it is NOT used for this). Never executed, only parsed as text/PDF/image.
CREATE TABLE IF NOT EXISTS business_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BLOB NOT NULL,
    extracted_text TEXT,             -- best-effort text extraction (PDF/TXT), for AI review only
    uploaded_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The structured tenant configuration Claude produces + the app assembles. This is what
-- tenant_config_service.py hands to the (future) bot integration — see section 12/19 of request.
-- One row per business; overwritten on re-normalization, but the INPUT that produced it is always
-- recoverable from business_profiles/business_services/business_faqs/onboarding_sessions.
CREATE TABLE IF NOT EXISTS ai_settings (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    ai_status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | RUNNING | DONE | FAILED
    normalized_summary TEXT,                    -- Claude's clean business summary
    normalized_config_json TEXT,                -- full structured config (JSON), see ai_onboarding.py
    missing_fields_json TEXT,                    -- JSON array of field names flagged missing/unclear
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Feature flags — backend-enforced (section 13), never inferred from prompt wording alone.
CREATE TABLE IF NOT EXISTS tenant_features (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    faq INTEGER NOT NULL DEFAULT 1,
    business_info INTEGER NOT NULL DEFAULT 1,
    catalog INTEGER NOT NULL DEFAULT 1,
    basic_lead_capture INTEGER NOT NULL DEFAULT 1,
    owner_commands INTEGER NOT NULL DEFAULT 0,
    advanced_history INTEGER NOT NULL DEFAULT 0,
    image_understanding INTEGER NOT NULL DEFAULT 0,
    voice_note INTEGER NOT NULL DEFAULT 0,
    lead_qualification INTEGER NOT NULL DEFAULT 0,
    appointment INTEGER NOT NULL DEFAULT 0,
    payment_conversation INTEGER NOT NULL DEFAULT 0
);

-- One row per onboarding wizard submission — an append-only audit trail of RAW payloads (section 9:
-- "do not destroy original submissions"), independent of whatever business_profiles currently holds.
CREATE TABLE IF NOT EXISTS onboarding_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    step TEXT NOT NULL,             -- 'basics' | 'services' | 'operations' | 'faq' | 'style' | 'upload'
    raw_payload_json TEXT NOT NULL,
    submitted_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS onboarding_status (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    basics_done INTEGER NOT NULL DEFAULT 0,
    services_done INTEGER NOT NULL DEFAULT 0,
    operations_done INTEGER NOT NULL DEFAULT 0,
    faq_done INTEGER NOT NULL DEFAULT 0,
    style_done INTEGER NOT NULL DEFAULT 0,
    upload_done INTEGER NOT NULL DEFAULT 0,          -- upload is optional, but tracked for % complete
    reviewed_done INTEGER NOT NULL DEFAULT 0,
    simulated_done INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tenant_activation (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    approved_by_user_id INTEGER REFERENCES users(id),
    approved_at TEXT,
    activated_by_user_id INTEGER REFERENCES users(id),
    activated_at TEXT,
    deactivated_at TEXT
);

-- Simulation runs — fully isolated from production conversations/appointments/payments (section 15).
CREATE TABLE IF NOT EXISTS simulation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    session_token TEXT NOT NULL,     -- groups one simulated conversation, not tied to any real customer
    role TEXT NOT NULL,               -- 'user' | 'assistant'
    content TEXT NOT NULL,
    flagged_wrong INTEGER NOT NULL DEFAULT 0,   -- client clicked "Jawaban ini salah" (section 16)
    flag_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Lightweight audit trail (section 29) — never edited/deleted, append-only.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER REFERENCES users(id),
    business_id INTEGER REFERENCES businesses(id),
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);
CREATE INDEX IF NOT EXISTS idx_memberships_user ON business_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_services_business ON business_services(business_id);
CREATE INDEX IF NOT EXISTS idx_faqs_business ON business_faqs(business_id);
CREATE INDEX IF NOT EXISTS idx_files_business ON business_files(business_id);
CREATE INDEX IF NOT EXISTS idx_audit_business ON audit_log(business_id);
CREATE INDEX IF NOT EXISTS idx_sim_business_session ON simulation_messages(business_id, session_token);
