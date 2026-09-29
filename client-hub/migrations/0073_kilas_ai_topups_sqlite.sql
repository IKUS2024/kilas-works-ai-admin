-- Account-owned Kilas AI top-ups. Existing plan, Finance and payment rows are unchanged.
ALTER TABLE kilas_ai_usage ADD COLUMN quota_source TEXT NOT NULL DEFAULT 'BASE'
    CHECK (quota_source IN ('BASE','TOPUP'));

CREATE TABLE IF NOT EXISTS kilas_ai_topup_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    pack TEXT NOT NULL CHECK (pack IN ('MINI','EXTRA','POWER')),
    amount_idr INTEGER NOT NULL CHECK (amount_idr > 0),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING'
        CHECK (status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
    proof_filename TEXT,
    proof_mime_type TEXT,
    proof_content BLOB,
    verified_by INTEGER REFERENCES users(id),
    verified_at TEXT,
    admin_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_orders_owner ON kilas_ai_topup_orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_orders_review ON kilas_ai_topup_orders(status, created_at);

CREATE TABLE IF NOT EXISTS kilas_ai_topup_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES kilas_ai_topup_orders(id),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_micro INTEGER NOT NULL CHECK (total_micro > 0),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_credits_owner_expiry ON kilas_ai_topup_credits(user_id, expires_at, id);

CREATE TABLE IF NOT EXISTS kilas_ai_topup_debits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credit_id INTEGER NOT NULL REFERENCES kilas_ai_topup_credits(id),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation_key TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    reserved_micro INTEGER NOT NULL CHECK (reserved_micro > 0),
    charged_micro INTEGER NOT NULL DEFAULT 0 CHECK (charged_micro >= 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE','FAILED')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(credit_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_debits_owner ON kilas_ai_topup_debits(user_id, operation_key);
