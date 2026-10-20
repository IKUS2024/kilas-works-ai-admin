-- Exact standalone VoiceOver input and alternate lineage; no historical backfill.
ALTER TABLE kilas_audio_jobs ADD COLUMN IF NOT EXISTS spoken_script TEXT CHECK (spoken_script IS NULL OR length(spoken_script) <= 4000);
ALTER TABLE kilas_audio_jobs ADD COLUMN IF NOT EXISTS alternate_of INTEGER;
ALTER TABLE kilas_audio_jobs ADD COLUMN IF NOT EXISTS delivery_stability DOUBLE PRECISION;
ALTER TABLE kilas_audio_jobs ADD COLUMN IF NOT EXISTS voice_is_personal INTEGER NOT NULL DEFAULT 0;
