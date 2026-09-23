-- Kilas Order customer search requests.
CREATE TABLE IF NOT EXISTS kilas_order_requests (
    id BIGSERIAL PRIMARY KEY,
    request_code TEXT NOT NULL UNIQUE,
    draft_token TEXT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_text TEXT NOT NULL,
    ai_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    conversation_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    location_source TEXT NOT NULL DEFAULT '',
    location_label TEXT,
    latitude NUMERIC(9,6),
    longitude NUMERIC(9,6),
    status TEXT NOT NULL DEFAULT 'SEARCH_REQUESTED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, draft_token),
    CHECK (location_source IN ('','gps','manual')),
    CHECK (status IN (
        'SEARCH_REQUESTED','SEARCHING','RESULTS_READY','SELECTED','VERIFYING',
        'AWAITING_PAYMENT','PAID','PURCHASING','PURCHASED','SHIPPED',
        'DELIVERED','CANCELLED','ISSUE'
    ))
);
CREATE INDEX IF NOT EXISTS idx_kilas_order_requests_user_created
    ON kilas_order_requests(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kilas_order_requests_status_created
    ON kilas_order_requests(status, created_at ASC);
