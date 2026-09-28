-- Account-owned Kilas AI data. No business or Finance rows are changed.
CREATE TABLE IF NOT EXISTS kilas_ai_threads (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Chat baru',
    selected_mode TEXT NOT NULL DEFAULT 'SMART' CHECK (selected_mode IN ('FAST','SMART','EXPERT')),
    share_token_hash TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_threads_owner_history ON kilas_ai_threads(user_id, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS kilas_ai_messages (
    id BIGSERIAL PRIMARY KEY,
    thread_id BIGINT NOT NULL REFERENCES kilas_ai_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL DEFAULT '',
    mode TEXT CHECK (mode IN ('FAST','SMART','EXPERT')),
    provider TEXT,
    model TEXT,
    operation_key TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(thread_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_messages_thread ON kilas_ai_messages(thread_id, id);

CREATE TABLE IF NOT EXISTS kilas_ai_attachments (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id BIGINT NOT NULL REFERENCES kilas_ai_threads(id) ON DELETE CASCADE,
    message_id BIGINT REFERENCES kilas_ai_messages(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    content BYTEA NOT NULL,
    extracted_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_attachments_owner ON kilas_ai_attachments(user_id, thread_id, message_id);

CREATE TABLE IF NOT EXISTS kilas_ai_usage (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id BIGINT REFERENCES kilas_ai_threads(id) ON DELETE SET NULL,
    operation_key TEXT,
    operation_type TEXT NOT NULL,
    mode TEXT,
    provider TEXT,
    model TEXT,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    estimated_cost_usd TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, operation_type, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_usage_period ON kilas_ai_usage(user_id, created_at, operation_type, mode);

CREATE TABLE IF NOT EXISTS kilas_ai_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL CHECK (plan IN ('PLUS','PRO','MAX')),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','EXPIRED','CANCELLED')),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kilas_ai_invoices (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL CHECK (plan IN ('PLUS','PRO','MAX')),
    amount_idr BIGINT NOT NULL CHECK (amount_idr > 0),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING' CHECK (status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_invoices_owner ON kilas_ai_invoices(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS kilas_ai_payments (
    id BIGSERIAL PRIMARY KEY,
    invoice_id BIGINT NOT NULL UNIQUE REFERENCES kilas_ai_invoices(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('UNDER_REVIEW','VERIFIED','REJECTED')),
    proof_filename TEXT NOT NULL,
    proof_mime_type TEXT NOT NULL,
    proof_content BYTEA NOT NULL,
    verified_by BIGINT REFERENCES users(id),
    verified_at TIMESTAMPTZ,
    admin_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_payments_review ON kilas_ai_payments(status, created_at);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_payments_owner ON kilas_ai_payments(user_id, created_at DESC);
