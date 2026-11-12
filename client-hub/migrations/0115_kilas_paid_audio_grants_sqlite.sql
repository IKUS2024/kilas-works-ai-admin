CREATE TABLE IF NOT EXISTS kilas_paid_audio_grants (
 job_id BIGINT PRIMARY KEY REFERENCES kilas_audio_jobs(id) ON DELETE CASCADE,
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 admitted_at TEXT NOT NULL
);
