-- Internal Kilas Works platform CRM scope. Additive only.
-- The row points to one hidden businesses record used only to reuse the existing Core Customers/Jobs engine.
CREATE TABLE IF NOT EXISTS platform_workspace_scope (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    business_id BIGINT NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform_workspace_outbound (
    event_id TEXT PRIMARY KEY,
    customer_phone TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('attempting','accepted','failed','unknown','suppressed')),
    error TEXT,
    created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_platform_workspace_outbound_phone
    ON platform_workspace_outbound(customer_phone,created_at DESC);
