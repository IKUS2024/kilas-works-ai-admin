-- Kilas Work owns its account, conversation, job, file, payment and cost data.
CREATE TABLE IF NOT EXISTS kilas_work_accounts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    trial_total_micro INTEGER NOT NULL DEFAULT 300000 CHECK (trial_total_micro > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS kilas_work_subscriptions (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL CHECK (plan IN ('PLUS','PRO','MAX')),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','EXPIRED')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS kilas_work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('PLAN','TOPUP')),
    sku TEXT NOT NULL CHECK (sku IN ('PLUS','PRO','MAX','MINI','EXTRA','POWER')),
    amount_idr INTEGER NOT NULL CHECK (amount_idr > 0),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING' CHECK (status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
    proof_filename TEXT,
    proof_mime_type TEXT,
    proof_content BLOB,
    verified_by INTEGER REFERENCES users(id),
    verified_at TEXT,
    admin_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_orders_user ON kilas_work_orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kilas_work_orders_review ON kilas_work_orders(status, created_at);
CREATE TABLE IF NOT EXISTS kilas_work_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES kilas_work_orders(id),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_micro INTEGER NOT NULL CHECK (total_micro > 0),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_credits_user ON kilas_work_credits(user_id, expires_at, id);
CREATE TABLE IF NOT EXISTS kilas_work_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Pekerjaan baru',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_threads_user ON kilas_work_threads(user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS kilas_work_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES kilas_work_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant','activity')),
    content TEXT NOT NULL DEFAULT '',
    model TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_messages_thread ON kilas_work_messages(thread_id, id);
CREATE TABLE IF NOT EXISTS kilas_work_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id INTEGER NOT NULL REFERENCES kilas_work_threads(id) ON DELETE CASCADE,
    message_id INTEGER REFERENCES kilas_work_messages(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    content BLOB NOT NULL,
    extracted_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_files_user ON kilas_work_files(user_id, thread_id, id);
CREATE TABLE IF NOT EXISTS kilas_work_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id INTEGER NOT NULL REFERENCES kilas_work_threads(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','PAUSED_USER','PAUSED_QUOTA','PAUSED_CONFIRM','COMPLETED','FAILED','CANCELLED')),
    goal TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    last_response_id TEXT,
    current_url TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_jobs_user ON kilas_work_jobs(user_id, status, id DESC);
CREATE TABLE IF NOT EXISTS kilas_work_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id INTEGER REFERENCES kilas_work_threads(id) ON DELETE SET NULL,
    job_id INTEGER REFERENCES kilas_work_jobs(id) ON DELETE SET NULL,
    operation_key TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    model TEXT,
    source TEXT NOT NULL CHECK (source IN ('TRIAL','BASE','TOPUP')),
    status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE','FAILED')),
    reserved_micro INTEGER NOT NULL CHECK (reserved_micro > 0),
    charged_micro INTEGER NOT NULL DEFAULT 0 CHECK (charged_micro >= 0),
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_usage_user ON kilas_work_usage(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS kilas_work_topup_debits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credit_id INTEGER NOT NULL REFERENCES kilas_work_credits(id),
    operation_key TEXT NOT NULL,
    reserved_micro INTEGER NOT NULL CHECK (reserved_micro > 0),
    charged_micro INTEGER NOT NULL DEFAULT 0 CHECK (charged_micro >= 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE','FAILED')),
    UNIQUE(credit_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_work_topup_debits_user ON kilas_work_topup_debits(user_id, operation_key);
