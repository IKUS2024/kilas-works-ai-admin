-- Track quota reservations separately from completed billable usage.
ALTER TABLE kilas_ai_usage ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'COMPLETE';
