-- Kilas Works Client Hub — initial schema, PRODUCTION (Postgres) equivalent of 0001_init_sqlite.sql.
--
-- IMPORTANT — HONESTY NOTE: this file was hand-translated from the SQLite schema that this V1 was
-- actually built and tested against in this sandbox (which has no network access to install
-- psycopg2/SQLAlchemy, and no live Postgres instance to run migrations against). The SQL below has
-- NOT been executed anywhere. Review it (or have it reviewed) before running against a real
-- Postgres database. The translation is mechanical (SERIAL/BIGSERIAL for autoincrement, TIMESTAMPTZ
-- for datetimes, BOOLEAN for the 0/1 flags, BYTEA for file content, JSONB for JSON columns) and the
-- table/column shapes are otherwise identical to the SQLite version, so the application's SQL
-- queries would need a small dialect adapter (placeholder style, RETURNING id, boolean literals) —
-- see db.py's docstring for exactly what would need to change to run this app against Postgres.
--
-- ADDITIVE ONLY. No table drops. No destructive changes. Safe to run on an empty database/schema;
-- re-running is guarded with IF NOT EXISTS everywhere it's supported.

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'CLIENT_OWNER',
    full_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS businesses (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL UNIQUE,
    business_name TEXT NOT NULL,
    package TEXT NOT NULL DEFAULT 'AI_ADMIN_BASIC',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    whatsapp_connected BOOLEAN NOT NULL DEFAULT FALSE,
    whatsapp_phone_number_id TEXT,
    trusted_owner_phone TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS business_memberships (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    user_id BIGINT NOT NULL REFERENCES users(id),
    role_in_business TEXT NOT NULL DEFAULT 'OWNER',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(business_id, user_id)
);

CREATE TABLE IF NOT EXISTS business_profiles (
    business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
    category TEXT,
    short_description TEXT,
    country TEXT,
    timezone TEXT,
    address TEXT,
    business_phone TEXT,
    owner_name TEXT,
    primary_language TEXT DEFAULT 'id',
    additional_languages JSONB,
    tone TEXT DEFAULT 'friendly',
    customer_salutation TEXT DEFAULT 'Kak',
    operating_hours JSONB,
    closed_days TEXT,
    online_or_offline TEXT,
    appointment_rules_raw TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS business_services (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    raw_input TEXT NOT NULL,
    service_name TEXT,
    description TEXT,
    price_from BIGINT,
    price_to BIGINT,
    currency TEXT DEFAULT 'IDR',
    notes TEXT,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS business_faqs (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    raw_input TEXT NOT NULL,
    question TEXT,
    answer TEXT,
    category TEXT DEFAULT 'general',
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- NOTE (production recommendation): storing file bytes in Postgres (BYTEA) works for V1 volumes but
-- does not scale well and bloats DB backups. Before real client volume grows, migrate this table to
-- store an object-storage key (e.g. Supabase Storage / Cloudflare R2 / S3) instead of `content`.
CREATE TABLE IF NOT EXISTS business_files (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    content BYTEA NOT NULL,
    extracted_text TEXT,
    uploaded_by_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_settings (
    business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
    ai_status TEXT NOT NULL DEFAULT 'PENDING',
    normalized_summary TEXT,
    normalized_config_json JSONB,
    missing_fields_json JSONB,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_features (
    business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
    faq BOOLEAN NOT NULL DEFAULT TRUE,
    business_info BOOLEAN NOT NULL DEFAULT TRUE,
    catalog BOOLEAN NOT NULL DEFAULT TRUE,
    basic_lead_capture BOOLEAN NOT NULL DEFAULT TRUE,
    owner_commands BOOLEAN NOT NULL DEFAULT FALSE,
    advanced_history BOOLEAN NOT NULL DEFAULT FALSE,
    image_understanding BOOLEAN NOT NULL DEFAULT FALSE,
    voice_note BOOLEAN NOT NULL DEFAULT FALSE,
    lead_qualification BOOLEAN NOT NULL DEFAULT FALSE,
    appointment BOOLEAN NOT NULL DEFAULT FALSE,
    payment_conversation BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS onboarding_sessions (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    step TEXT NOT NULL,
    raw_payload_json JSONB NOT NULL,
    submitted_by_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS onboarding_status (
    business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
    basics_done BOOLEAN NOT NULL DEFAULT FALSE,
    services_done BOOLEAN NOT NULL DEFAULT FALSE,
    operations_done BOOLEAN NOT NULL DEFAULT FALSE,
    faq_done BOOLEAN NOT NULL DEFAULT FALSE,
    style_done BOOLEAN NOT NULL DEFAULT FALSE,
    upload_done BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_done BOOLEAN NOT NULL DEFAULT FALSE,
    simulated_done BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_activation (
    business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
    approved_by_user_id BIGINT REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    activated_by_user_id BIGINT REFERENCES users(id),
    activated_at TIMESTAMPTZ,
    deactivated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS simulation_messages (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    session_token TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    flagged_wrong BOOLEAN NOT NULL DEFAULT FALSE,
    flag_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor_user_id BIGINT REFERENCES users(id),
    business_id BIGINT REFERENCES businesses(id),
    action TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);
CREATE INDEX IF NOT EXISTS idx_memberships_user ON business_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_services_business ON business_services(business_id);
CREATE INDEX IF NOT EXISTS idx_faqs_business ON business_faqs(business_id);
CREATE INDEX IF NOT EXISTS idx_files_business ON business_files(business_id);
CREATE INDEX IF NOT EXISTS idx_audit_business ON audit_log(business_id);
CREATE INDEX IF NOT EXISTS idx_sim_business_session ON simulation_messages(business_id, session_token);
