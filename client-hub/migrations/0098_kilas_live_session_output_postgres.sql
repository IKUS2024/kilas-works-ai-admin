ALTER TABLE kilas_audio_jobs ADD COLUMN IF NOT EXISTS content_origin TEXT NOT NULL DEFAULT 'standard';
ALTER TABLE kilas_audio_jobs ADD COLUMN IF NOT EXISTS initial_reserved_seconds INTEGER NOT NULL DEFAULT 0;
