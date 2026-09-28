-- Account-owned Kilas AI data. No business or Finance rows are changed.
CREATE TABLE IF NOT EXISTS kilas_ai_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Chat baru',
    selected_mode TEXT NOT NULL DEFAULT 'SMART' CHECK (selected_mode IN ('FAST','SMART','EXPERT')),
    share_token_hash TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_threads_owner_history ON kilas_ai_threads(user_id, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS kilas_ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES kilas_ai_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL DEFAULT '',
    mode TEXT CHECK (mode IN ('FAST','SMART','EXPERT')),
    provider TEXT,
    model TEXT,
    operation_key TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(thread_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_messages_thread ON kilas_ai_messages(thread_id, id);

CREATE TABLE IF NOT EXISTS kilas_ai_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id INTEGER NOT NULL REFERENCES kilas_ai_threads(id) ON DELETE CASCADE,
    message_id INTEGER REFERENCES kilas_ai_messages(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    content BLOB NOT NULL,
    extracted_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_attachments_owner ON kilas_ai_attachments(user_id, thread_id, message_id);

CREATE TABLE IF NOT EXISTS kilas_ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id INTEGER REFERENCES kilas_ai_threads(id) ON DELETE SET NULL,
    operation_key TEXT,
    operation_type TEXT NOT NULL,
    mode TEXT,
    provider TEXT,
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, operation_type, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_usage_period ON kilas_ai_usage(user_id, created_at, operation_type, mode);

CREATE TABLE IF NOT EXISTS kilas_ai_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL CHECK (plan IN ('PLUS','PRO','MAX')),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','EXPIRED','CANCELLED')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kilas_ai_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL CHECK (plan IN ('PLUS','PRO','MAX')),
    amount_idr INTEGER NOT NULL CHECK (amount_idr > 0),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING' CHECK (status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_invoices_owner ON kilas_ai_invoices(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS kilas_ai_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL UNIQUE REFERENCES kilas_ai_invoices(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('UNDER_REVIEW','VERIFIED','REJECTED')),
    proof_filename TEXT NOT NULL,
    proof_mime_type TEXT NOT NULL,
    proof_content BLOB NOT NULL,
    verified_by INTEGER REFERENCES users(id),
    verified_at TEXT,
    admin_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_payments_review ON kilas_ai_payments(status, created_at);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_payments_owner ON kilas_ai_payments(user_id, created_at DESC);
