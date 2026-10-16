CREATE TABLE IF NOT EXISTS finance_reset_requests (
 request_key TEXT PRIMARY KEY CHECK(length(request_key)=32),
 business_id INTEGER NOT NULL REFERENCES businesses(id),
 origin_branch_id INTEGER NOT NULL,
 actor_user_id INTEGER NOT NULL REFERENCES users(id),
 workspace_type TEXT NOT NULL CHECK(workspace_type IN ('PERSONAL','BUSINESS')),
 target_json TEXT NOT NULL,preview_json TEXT NOT NULL,state_digest TEXT NOT NULL,
 created_at TEXT NOT NULL,expires_at TEXT NOT NULL,processed_at TEXT,
 FOREIGN KEY(business_id,origin_branch_id) REFERENCES finance_branches(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_reset_owner ON finance_reset_requests(business_id,actor_user_id,created_at);
CREATE TABLE IF NOT EXISTS finance_personal_homes (
 user_id INTEGER PRIMARY KEY REFERENCES users(id),
 business_id INTEGER NOT NULL REFERENCES businesses(id),
 branch_id INTEGER NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(business_id,branch_id),
 FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id)
);
