-- Business Hub V2, Production Integration (Section 6 gap-fix, PostgreSQL dialect). ADDITIVE ONLY.
-- See 0008_talent_profile_photo_url_sqlite.sql for the full rationale.
ALTER TABLE talents ADD COLUMN IF NOT EXISTS profile_photo_url TEXT;
