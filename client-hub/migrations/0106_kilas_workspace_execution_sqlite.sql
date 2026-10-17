CREATE TABLE IF NOT EXISTS kilas_workspace_executions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 job_id INTEGER REFERENCES kilas_agent_jobs(id) ON DELETE SET NULL,operation_key TEXT NOT NULL UNIQUE,
 state TEXT NOT NULL,sandbox_id TEXT,reserved_micro_usd INTEGER NOT NULL,
 cleanup_confirmed INTEGER NOT NULL DEFAULT 0,outcome_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL,expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_execution_owner ON kilas_workspace_executions(user_id,job_id);
CREATE INDEX IF NOT EXISTS idx_workspace_execution_budget ON kilas_workspace_executions(created_at,state);
