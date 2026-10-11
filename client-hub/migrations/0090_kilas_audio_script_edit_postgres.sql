-- Preserve only new VoiceOver originals for owner-requested Edit; no backfill.
ALTER TABLE kilas_audio_jobs ADD COLUMN IF NOT EXISTS original_script TEXT CHECK (original_script IS NULL OR length(original_script) <= 4000);
