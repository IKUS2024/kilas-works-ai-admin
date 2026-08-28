-- Business Hub V2, Phase H (PostgreSQL dialect). HONESTY NOTE: hand-translated, untested against a
-- real Postgres instance from this sandbox. ADDITIVE ONLY.

CREATE TABLE IF NOT EXISTS wa_conversation_state (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    customer_phone TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'AI_ACTIVE',
    updated_by_user_id BIGINT REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(business_id, customer_phone)
);

CREATE INDEX IF NOT EXISTS idx_wa_conversation_state_business ON wa_conversation_state(business_id);
