-- Unified AI Brain v2, Section 1 (PostgreSQL side — see the _sqlite.sql sibling for rationale).
CREATE TABLE IF NOT EXISTS platform_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
