-- Finance workspace split. Existing branch/data is Business by default.
CREATE TABLE IF NOT EXISTS finance_branch_workspaces (
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 branch_id BIGINT NOT NULL REFERENCES finance_branches(id),
 workspace_type TEXT NOT NULL CHECK(workspace_type IN ('BUSINESS','PERSONAL')),
 owner_user_id BIGINT REFERENCES users(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(business_id,branch_id),
 FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id),
 CHECK((workspace_type='BUSINESS' AND owner_user_id IS NULL)
    OR (workspace_type='PERSONAL' AND owner_user_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_personal_workspace_owner
 ON finance_branch_workspaces(business_id,owner_user_id)
 WHERE workspace_type='PERSONAL';
CREATE INDEX IF NOT EXISTS idx_finance_workspace_business_type
 ON finance_branch_workspaces(business_id,workspace_type,branch_id);

INSERT INTO finance_branch_workspaces
 (business_id,branch_id,workspace_type,owner_user_id,created_at)
SELECT business_id,id,'BUSINESS',NULL,CURRENT_TIMESTAMP
FROM finance_branches
ON CONFLICT(business_id,branch_id) DO NOTHING;
