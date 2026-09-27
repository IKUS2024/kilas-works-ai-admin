-- All pre-router usage was Anthropic; new calls explicitly record their provider.
ALTER TABLE ai_usage_ledger ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'anthropic';
