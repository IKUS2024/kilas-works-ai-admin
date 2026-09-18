CREATE TABLE IF NOT EXISTS finance_branches (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 business_id INTEGER NOT NULL REFERENCES businesses(id),
 name TEXT NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE,
 is_default BOOLEAN NOT NULL DEFAULT FALSE,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(business_id,id), UNIQUE(business_id,name)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_branch_default ON finance_branches(business_id) WHERE is_default=TRUE;
INSERT INTO finance_branches (business_id,name,is_default,created_at,updated_at)
 SELECT b.id,'Utama',TRUE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP FROM businesses b
 WHERE (EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=b.id)
 OR EXISTS (SELECT 1 FROM finance_invoices i WHERE i.business_id=b.id)
 OR EXISTS (SELECT 1 FROM finance_categories c WHERE c.business_id=b.id)
 OR EXISTS (SELECT 1 FROM finance_entitlements e WHERE e.business_id=b.id))
 AND NOT EXISTS (SELECT 1 FROM finance_branches r WHERE r.business_id=b.id AND r.is_default=TRUE);
ALTER TABLE finance_accounts ADD COLUMN branch_id INTEGER REFERENCES finance_branches(id);
UPDATE finance_accounts SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_accounts.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
ALTER TABLE finance_transactions ADD COLUMN branch_id INTEGER REFERENCES finance_branches(id);
UPDATE finance_transactions SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_transactions.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_transactions_branch ON finance_transactions(business_id,branch_id);
ALTER TABLE finance_invoices ADD COLUMN branch_id INTEGER REFERENCES finance_branches(id);
UPDATE finance_invoices SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_invoices.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_invoices_branch ON finance_invoices(business_id,branch_id);
ALTER TABLE finance_recurring_expenses ADD COLUMN branch_id INTEGER REFERENCES finance_branches(id);
UPDATE finance_recurring_expenses SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_recurring_expenses.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_recurring_expenses_branch ON finance_recurring_expenses(business_id,branch_id);
ALTER TABLE finance_bank_imports ADD COLUMN branch_id INTEGER REFERENCES finance_branches(id);
UPDATE finance_bank_imports SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_bank_imports.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_bank_imports_branch ON finance_bank_imports(business_id,branch_id);
CREATE TABLE IF NOT EXISTS finance_transaction_revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL REFERENCES businesses(id),
 transaction_id INTEGER NOT NULL REFERENCES finance_transactions(id),
 before_json TEXT NOT NULL, after_json TEXT NOT NULL,
 actor_user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
