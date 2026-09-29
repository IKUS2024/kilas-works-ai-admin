-- Kilas Work owns its account, conversation, job, file, payment and cost data.
CREATE TABLE IF NOT EXISTS kilas_work_accounts (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    trial_total_micro BIGINT NOT NULL DEFAULT 300000 CHECK (trial_total_micro > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS kilas_work_subscriptions (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL CHECK (plan IN ('PLUS','PRO','MAX')),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','EXPIRED')),
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS kilas_work_orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('PLAN','TOPUP')),
    sku TEXT NOT NULL CHECK (sku IN ('PLUS','PRO','MAX','MINI','EXTRA','POWER')),
    amount_idr BIGINT NOT NULL CHECK (amount_idr > 0),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING' CHECK (status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
    proof_filename TEXT,
    proof_mime_type TEXT,
    proof_content BYTEA,
    verified_by BIGINT REFERENCES users(id),
    verified_at TIMESTAMPTZ,
    admin_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_orders_user ON kilas_work_orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kilas_work_orders_review ON kilas_work_orders(status, created_at);
CREATE TABLE IF NOT EXISTS kilas_work_credits (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL UNIQUE REFERENCES kilas_work_orders(id),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_micro BIGINT NOT NULL CHECK (total_micro > 0),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_credits_user ON kilas_work_credits(user_id, expires_at, id);
CREATE TABLE IF NOT EXISTS kilas_work_threads (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Pekerjaan baru',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_threads_user ON kilas_work_threads(user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS kilas_work_messages (
    id BIGSERIAL PRIMARY KEY,
    thread_id BIGINT NOT NULL REFERENCES kilas_work_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant','activity')),
    content TEXT NOT NULL DEFAULT '',
    model TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_messages_thread ON kilas_work_messages(thread_id, id);
CREATE TABLE IF NOT EXISTS kilas_work_files (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id BIGINT NOT NULL REFERENCES kilas_work_threads(id) ON DELETE CASCADE,
    message_id BIGINT REFERENCES kilas_work_messages(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    content BYTEA NOT NULL,
    extracted_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_files_user ON kilas_work_files(user_id, thread_id, id);
CREATE TABLE IF NOT EXISTS kilas_work_jobs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id BIGINT NOT NULL REFERENCES kilas_work_threads(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','PAUSED_USER','PAUSED_QUOTA','PAUSED_CONFIRM','COMPLETED','FAILED','CANCELLED')),
    goal TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    last_response_id TEXT,
    current_url TEXT,
    error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_jobs_user ON kilas_work_jobs(user_id, status, id DESC);
CREATE TABLE IF NOT EXISTS kilas_work_usage (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id BIGINT REFERENCES kilas_work_threads(id) ON DELETE SET NULL,
    job_id BIGINT REFERENCES kilas_work_jobs(id) ON DELETE SET NULL,
    operation_key TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    model TEXT,
    source TEXT NOT NULL CHECK (source IN ('TRIAL','BASE','TOPUP')),
    status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE','FAILED')),
    reserved_micro BIGINT NOT NULL CHECK (reserved_micro > 0),
    charged_micro BIGINT NOT NULL DEFAULT 0 CHECK (charged_micro >= 0),
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_usage_user ON kilas_work_usage(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS kilas_work_topup_debits (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credit_id BIGINT NOT NULL REFERENCES kilas_work_credits(id),
    operation_key TEXT NOT NULL,
    reserved_micro BIGINT NOT NULL CHECK (reserved_micro > 0),
    charged_micro BIGINT NOT NULL DEFAULT 0 CHECK (charged_micro >= 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE','FAILED')),
    UNIQUE(credit_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_topup_debits_user ON kilas_work_topup_debits(user_id, operation_key);
