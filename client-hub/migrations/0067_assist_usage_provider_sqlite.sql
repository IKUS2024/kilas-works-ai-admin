-- Add provider attribution to the existing usage authority; no monetary ledger changes.
ALTER TABLE ai_usage_ledger ADD COLUMN provider TEXT NOT NULL DEFAULT 'anthropic';
