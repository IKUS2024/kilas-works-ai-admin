-- Durable server-owned sponsorship of already admitted Audio jobs.
CREATE TABLE IF NOT EXISTS kilas_free_test_audio (
    job_id BIGINT PRIMARY KEY REFERENCES kilas_audio_jobs(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    end_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS kilas_free_test_audio_user ON kilas_free_test_audio(user_id,job_id);
