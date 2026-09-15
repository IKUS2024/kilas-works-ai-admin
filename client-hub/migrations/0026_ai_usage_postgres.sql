-- Additive accounting only. No historical transaction rows are changed.
CREATE TABLE IF NOT EXISTS ai_usage_ledger (
 id BIGSERIAL PRIMARY KEY,
 tenant_id INTEGER REFERENCES businesses(id),
 context_type TEXT NOT NULL,
 model TEXT NOT NULL,
 classification TEXT NOT NULL,
 is_reply BOOLEAN NOT NULL DEFAULT FALSE,
 input_tokens BIGINT NOT NULL CHECK(input_tokens>=0),
 output_tokens BIGINT NOT NULL CHECK(output_tokens>=0),
 cache_read_input_tokens BIGINT NOT NULL CHECK(cache_read_input_tokens>=0),
 cache_creation_input_tokens BIGINT NOT NULL CHECK(cache_creation_input_tokens>=0),
 estimated_cost_usd DOUBLE PRECISION,
 estimated_cost_idr DOUBLE PRECISION,
 pricing_date TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_usage_tenant_month ON ai_usage_ledger(tenant_id,created_at);
CREATE INDEX IF NOT EXISTS ai_usage_month ON ai_usage_ledger(created_at);
