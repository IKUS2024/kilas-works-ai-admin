-- Internal Kilas Works platform CRM scope. Additive only.
-- The row points to one hidden businesses record used only to reuse the existing Core Customers/Jobs engine.
CREATE TABLE IF NOT EXISTS platform_workspace_scope (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    business_id BIGINT NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
