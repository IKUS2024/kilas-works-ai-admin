-- Scope Finance categories by Business vs owner-private Personal workspace.
-- Legacy categories remain Business. Personal mappings are created only for
-- categories already used by Personal history; new Personal defaults are seeded by the service.
CREATE TABLE IF NOT EXISTS finance_category_workspace_settings (
 business_id INTEGER NOT NULL REFERENCES businesses(id),
 category_id INTEGER NOT NULL REFERENCES finance_categories(id),
 scope_key TEXT NOT NULL,
 workspace_type TEXT NOT NULL CHECK(workspace_type IN ('BUSINESS','PERSONAL')),
 owner_user_id INTEGER REFERENCES users(id),
 display_name TEXT NOT NULL,
 is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(business_id,category_id,scope_key),
 CHECK((workspace_type='BUSINESS' AND owner_user_id IS NULL AND scope_key='BUSINESS')
    OR (workspace_type='PERSONAL' AND owner_user_id IS NOT NULL
        AND scope_key='PERSONAL:' || owner_user_id))
);
CREATE INDEX IF NOT EXISTS idx_finance_category_workspace_scope
 ON finance_category_workspace_settings(business_id,scope_key,is_active,category_id);

INSERT OR IGNORE INTO finance_category_workspace_settings
 (business_id,category_id,scope_key,workspace_type,owner_user_id,display_name,is_active,created_at,updated_at)
SELECT c.business_id,c.id,'BUSINESS','BUSINESS',NULL,c.name,c.is_active,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM finance_categories c
WHERE NOT EXISTS (
  SELECT 1 FROM finance_category_workspace_settings p
  WHERE p.business_id=c.business_id AND p.category_id=c.id
    AND p.workspace_type='PERSONAL'
);

INSERT OR IGNORE INTO finance_category_workspace_settings
 (business_id,category_id,scope_key,workspace_type,owner_user_id,display_name,is_active,created_at,updated_at)
SELECT DISTINCT c.business_id,c.id,'PERSONAL:' || w.owner_user_id,'PERSONAL',w.owner_user_id,
       c.name,TRUE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM finance_categories c
JOIN (
 SELECT t.business_id,t.category_id,t.branch_id FROM finance_transactions t
 UNION
 SELECT b.business_id,b.category_id,b.branch_id FROM finance_budgets b
 UNION
 SELECT r.business_id,r.category_id,r.branch_id FROM finance_recurring_expenses r
) used ON used.business_id=c.business_id AND used.category_id=c.id
JOIN finance_branch_workspaces w
 ON w.business_id=used.business_id AND w.branch_id=used.branch_id
WHERE w.workspace_type='PERSONAL';

INSERT OR IGNORE INTO finance_category_workspace_settings
 (business_id,category_id,scope_key,workspace_type,owner_user_id,display_name,is_active,created_at,updated_at)
SELECT DISTINCT p.business_id,p.id,'PERSONAL:' || w.owner_user_id,'PERSONAL',w.owner_user_id,
       p.name,TRUE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM finance_category_hierarchy h
JOIN finance_categories child
 ON child.business_id=h.business_id AND child.id=h.child_category_id
JOIN finance_categories p
 ON p.business_id=h.business_id AND p.id=h.parent_category_id
JOIN finance_category_workspace_settings s
 ON s.business_id=child.business_id AND s.category_id=child.id
 AND s.workspace_type='PERSONAL'
JOIN finance_branch_workspaces w
 ON w.business_id=s.business_id AND w.owner_user_id=s.owner_user_id
 AND w.workspace_type='PERSONAL';
