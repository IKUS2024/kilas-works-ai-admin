-- Account-owned Kilas AI top-ups. Existing plan, Finance and payment rows are unchanged.
ALTER TABLE kilas_ai_usage ADD COLUMN IF NOT EXISTS quota_source TEXT NOT NULL DEFAULT 'BASE'
    CHECK (quota_source IN ('BASE','TOPUP'));

CREATE TABLE IF NOT EXISTS kilas_ai_topup_orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    pack TEXT NOT NULL CHECK (pack IN ('MINI','EXTRA','POWER')),
    amount_idr BIGINT NOT NULL CHECK (amount_idr > 0),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING'
        CHECK (status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
    proof_filename TEXT,
    proof_mime_type TEXT,
    proof_content BYTEA,
    verified_by BIGINT REFERENCES users(id),
    verified_at TIMESTAMPTZ,
    admin_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_orders_owner ON kilas_ai_topup_orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_orders_review ON kilas_ai_topup_orders(status, created_at);

CREATE TABLE IF NOT EXISTS kilas_ai_topup_credits (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL UNIQUE REFERENCES kilas_ai_topup_orders(id),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_micro BIGINT NOT NULL CHECK (total_micro > 0),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_credits_owner_expiry ON kilas_ai_topup_credits(user_id, expires_at, id);

CREATE TABLE IF NOT EXISTS kilas_ai_topup_debits (
    id BIGSERIAL PRIMARY KEY,
    credit_id BIGINT NOT NULL REFERENCES kilas_ai_topup_credits(id),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation_key TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    reserved_micro BIGINT NOT NULL CHECK (reserved_micro > 0),
    charged_micro BIGINT NOT NULL DEFAULT 0 CHECK (charged_micro >= 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETE','FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(credit_id, operation_key)
);
CREATE INDEX IF NOT EXISTS idx_kilas_ai_topup_debits_owner ON kilas_ai_topup_debits(user_id, operation_key);
