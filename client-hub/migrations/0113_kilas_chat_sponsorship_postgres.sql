ALTER TABLE kilas_ai_usage ADD COLUMN IF NOT EXISTS customer_charge_exempt INTEGER NOT NULL DEFAULT 0 CHECK (customer_charge_exempt IN (0,1));
ALTER TABLE kilas_ai_usage ADD COLUMN IF NOT EXISTS customer_charge_origin TEXT;
CREATE TABLE IF NOT EXISTS kilas_ai_interactive_job_origins (
 job_id BIGINT PRIMARY KEY REFERENCES kilas_agent_jobs(id) ON DELETE CASCADE,
 user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 surface TEXT NOT NULL CHECK (surface IN ('thread','conversation')),
 surface_id BIGINT NOT NULL, request_key TEXT NOT NULL,
 text_grant INTEGER NOT NULL CHECK (text_grant IN (0,1)),
 image_grant INTEGER NOT NULL CHECK (image_grant IN (0,1))
);
