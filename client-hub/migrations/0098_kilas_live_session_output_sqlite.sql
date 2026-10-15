ALTER TABLE kilas_audio_jobs ADD COLUMN content_origin TEXT NOT NULL DEFAULT 'standard';
ALTER TABLE kilas_audio_jobs ADD COLUMN initial_reserved_seconds INTEGER NOT NULL DEFAULT 0;
