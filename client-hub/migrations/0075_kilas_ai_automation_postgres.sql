CREATE TABLE IF NOT EXISTS kilas_automation_settings (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    timezone TEXT NOT NULL DEFAULT 'Asia/Jakarta',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS kilas_automations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    instruction TEXT NOT NULL,
    automation_type TEXT NOT NULL CHECK (automation_type IN ('REMINDER','AI_TASK','SEARCH','WATCH')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PAUSED','PAUSED_QUOTA')),
    timezone TEXT NOT NULL,
    schedule_json TEXT NOT NULL,
    condition_json TEXT NOT NULL DEFAULT '{}',
    watch_state_json TEXT NOT NULL DEFAULT '{}',
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_kilas_automations_due ON kilas_automations(status,next_run_at,id);
CREATE INDEX IF NOT EXISTS idx_kilas_automations_owner ON kilas_automations(user_id,deleted_at,id DESC);
CREATE TABLE IF NOT EXISTS kilas_automation_runs (
    id BIGSERIAL PRIMARY KEY,
    automation_id BIGINT NOT NULL REFERENCES kilas_automations(id),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scheduled_for TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','SKIPPED_QUOTA','SKIPPED_DUPLICATE')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    retry_at TIMESTAMPTZ,
    lease_until TIMESTAMPTZ,
    result_text TEXT,
    result_metadata_json TEXT NOT NULL DEFAULT '{}',
    usage_metadata_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT,
    unread BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(automation_id,scheduled_for)
);
CREATE INDEX IF NOT EXISTS idx_kilas_automation_runs_owner ON kilas_automation_runs(user_id,unread,id DESC);
CREATE INDEX IF NOT EXISTS idx_kilas_automation_runs_retry ON kilas_automation_runs(status,retry_at,id);
