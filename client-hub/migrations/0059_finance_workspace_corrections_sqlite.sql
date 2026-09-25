-- Audited, monotonic workspace correction commands. No generic bypass flag.
CREATE TABLE IF NOT EXISTS finance_workspace_corrections (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 kind TEXT NOT NULL CHECK(kind IN ('transaction','recurring')),
 record_id BIGINT NOT NULL,
 transaction_id BIGINT REFERENCES finance_transactions(id),
 recurring_id BIGINT REFERENCES finance_recurring_expenses(id),
 version BIGINT NOT NULL CHECK(version>0),
 source_branch_id BIGINT NOT NULL,
 target_branch_id BIGINT NOT NULL,
 source_account_id BIGINT NOT NULL,
 target_account_id BIGINT NOT NULL,
 source_category_id BIGINT NOT NULL,
 target_category_id BIGINT NOT NULL,
 actor_user_id BIGINT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 CHECK((kind='transaction' AND transaction_id IS NOT NULL AND transaction_id=record_id AND recurring_id IS NULL)
 OR (kind='recurring' AND recurring_id IS NOT NULL AND recurring_id=record_id AND transaction_id IS NULL)),
 UNIQUE(kind,record_id,version),
 FOREIGN KEY(business_id,source_branch_id) REFERENCES finance_branches(business_id,id),
 FOREIGN KEY(business_id,target_branch_id) REFERENCES finance_branches(business_id,id),
 FOREIGN KEY(business_id,source_account_id) REFERENCES finance_accounts(business_id,id),
 FOREIGN KEY(business_id,target_account_id) REFERENCES finance_accounts(business_id,id),
 CHECK(source_branch_id<>target_branch_id)
);
CREATE TABLE IF NOT EXISTS finance_workspace_opening_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 source_account_id BIGINT NOT NULL,
 target_account_id BIGINT NOT NULL,
 source_opening_minor BIGINT NOT NULL,
 target_opening_before_minor BIGINT NOT NULL,
 actor_user_id BIGINT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 FOREIGN KEY(business_id,source_account_id) REFERENCES finance_accounts(business_id,id),
 FOREIGN KEY(business_id,target_account_id) REFERENCES finance_accounts(business_id,id),
 CHECK(source_account_id<>target_account_id)
);
ALTER TABLE finance_transactions ADD COLUMN relocation_version BIGINT NOT NULL DEFAULT 0 CHECK(relocation_version>=0);
CREATE TRIGGER IF NOT EXISTS apply_transaction_correction AFTER INSERT ON finance_workspace_corrections WHEN NEW.kind='transaction'
 BEGIN
 SELECT CASE WHEN NOT (EXISTS (SELECT 1 FROM business_memberships m
 JOIN finance_branches s ON s.business_id=m.business_id AND s.id=NEW.source_branch_id AND s.is_active=TRUE
 JOIN finance_branches d ON d.business_id=m.business_id AND d.id=NEW.target_branch_id AND d.is_active=TRUE
 JOIN finance_branch_workspaces sw ON sw.business_id=s.business_id AND sw.branch_id=s.id
 JOIN finance_branch_workspaces dw ON dw.business_id=d.business_id AND dw.branch_id=d.id
 WHERE m.business_id=NEW.business_id AND m.user_id=NEW.actor_user_id AND m.role_in_business='OWNER'
 AND sw.workspace_type<>dw.workspace_type
 AND (sw.workspace_type='BUSINESS' OR sw.owner_user_id=NEW.actor_user_id)
 AND (dw.workspace_type='BUSINESS' OR dw.owner_user_id=NEW.actor_user_id)) AND EXISTS (
 SELECT 1 FROM finance_transactions r
 JOIN finance_accounts a ON a.business_id=r.business_id AND a.id=NEW.target_account_id AND a.branch_id=NEW.target_branch_id AND a.is_active=TRUE AND a.currency=r.currency
 JOIN finance_categories c ON c.business_id=r.business_id AND c.id=NEW.target_category_id AND c.direction=r.direction
 WHERE r.business_id=NEW.business_id AND r.id=NEW.record_id
 AND r.branch_id=NEW.source_branch_id AND r.account_id=NEW.source_account_id AND r.category_id=NEW.source_category_id
 AND r.relocation_version+1=NEW.version AND COALESCE(r.source_type,'') IN ('','MANUAL','FINANCE_OPERATOR','FINANCE_RECEIPT') AND r.project_id IS NULL AND r.customer_id IS NULL AND NOT EXISTS (SELECT 1 FROM finance_invoice_payments p WHERE p.business_id=r.business_id AND p.ledger_transaction_id=r.id) AND NOT EXISTS (SELECT 1 FROM finance_recurring_postings p WHERE p.business_id=r.business_id AND p.ledger_transaction_id=r.id) AND NOT EXISTS (SELECT 1 FROM finance_bank_rows p WHERE p.business_id=r.business_id AND (p.matched_transaction_id=r.id OR p.created_transaction_id=r.id)))) THEN RAISE(ABORT,'finance correction denied') END;
 UPDATE finance_transactions SET branch_id=NEW.target_branch_id,account_id=NEW.target_account_id,
 category_id=NEW.target_category_id,relocation_version=NEW.version,updated_at=NEW.created_at
 WHERE business_id=NEW.business_id AND id=NEW.record_id;
 END;
 DROP TRIGGER IF EXISTS guard_finance_transactions_update;
 CREATE TRIGGER guard_finance_transactions_update BEFORE UPDATE ON finance_transactions
 WHEN (NEW.business_id IS NOT OLD.business_id OR
 ((NEW.branch_id IS NOT OLD.branch_id OR NEW.relocation_version<>OLD.relocation_version)
 AND NOT (EXISTS (SELECT 1 FROM finance_workspace_corrections e WHERE e.kind='transaction'
 AND e.business_id=OLD.business_id AND e.record_id=OLD.id
 AND e.version=OLD.relocation_version+1 AND NEW.relocation_version=e.version
 AND e.source_branch_id=OLD.branch_id AND e.target_branch_id=NEW.branch_id
 AND e.source_account_id=OLD.account_id AND e.target_account_id=NEW.account_id
 AND e.source_category_id=OLD.category_id AND e.target_category_id=NEW.category_id
 AND e.created_at=NEW.updated_at) AND NEW.id IS OLD.id AND NEW.business_id IS OLD.business_id AND NEW.direction IS OLD.direction AND NEW.amount_minor IS OLD.amount_minor AND NEW.currency IS OLD.currency AND NEW.occurred_on IS OLD.occurred_on AND NEW.description IS OLD.description AND NEW.counterparty_name IS OLD.counterparty_name AND NEW.project_id IS OLD.project_id AND NEW.source_type IS OLD.source_type AND NEW.source_ref IS OLD.source_ref AND NEW.status IS OLD.status AND NEW.created_by_user_id IS OLD.created_by_user_id AND NEW.created_at IS OLD.created_at AND NEW.voided_at IS OLD.voided_at AND NEW.voided_by_user_id IS OLD.voided_by_user_id AND NEW.customer_id IS OLD.customer_id))) OR NOT EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=NEW.business_id AND a.branch_id=NEW.branch_id AND a.id=NEW.account_id)
 OR NOT EXISTS (SELECT 1 FROM finance_branches b WHERE b.business_id=NEW.business_id AND b.id=NEW.branch_id)
 BEGIN SELECT RAISE(ABORT,'finance branch mismatch'); END;
ALTER TABLE finance_recurring_expenses ADD COLUMN relocation_version BIGINT NOT NULL DEFAULT 0 CHECK(relocation_version>=0);
CREATE TRIGGER IF NOT EXISTS apply_recurring_correction AFTER INSERT ON finance_workspace_corrections WHEN NEW.kind='recurring'
 BEGIN
 SELECT CASE WHEN NOT (EXISTS (SELECT 1 FROM business_memberships m
 JOIN finance_branches s ON s.business_id=m.business_id AND s.id=NEW.source_branch_id AND s.is_active=TRUE
 JOIN finance_branches d ON d.business_id=m.business_id AND d.id=NEW.target_branch_id AND d.is_active=TRUE
 JOIN finance_branch_workspaces sw ON sw.business_id=s.business_id AND sw.branch_id=s.id
 JOIN finance_branch_workspaces dw ON dw.business_id=d.business_id AND dw.branch_id=d.id
 WHERE m.business_id=NEW.business_id AND m.user_id=NEW.actor_user_id AND m.role_in_business='OWNER'
 AND sw.workspace_type<>dw.workspace_type
 AND (sw.workspace_type='BUSINESS' OR sw.owner_user_id=NEW.actor_user_id)
 AND (dw.workspace_type='BUSINESS' OR dw.owner_user_id=NEW.actor_user_id)) AND EXISTS (
 SELECT 1 FROM finance_recurring_expenses r
 JOIN finance_accounts a ON a.business_id=r.business_id AND a.id=NEW.target_account_id AND a.branch_id=NEW.target_branch_id AND a.is_active=TRUE AND a.currency=r.currency
 JOIN finance_categories c ON c.business_id=r.business_id AND c.id=NEW.target_category_id AND c.direction='EXPENSE'
 WHERE r.business_id=NEW.business_id AND r.id=NEW.record_id
 AND r.branch_id=NEW.source_branch_id AND r.account_id=NEW.source_account_id AND r.category_id=NEW.source_category_id
 AND r.relocation_version+1=NEW.version AND r.project_id IS NULL AND NOT EXISTS (SELECT 1 FROM finance_recurring_postings p WHERE p.business_id=r.business_id AND p.recurring_expense_id=r.id))) THEN RAISE(ABORT,'finance correction denied') END;
 UPDATE finance_recurring_expenses SET branch_id=NEW.target_branch_id,account_id=NEW.target_account_id,
 category_id=NEW.target_category_id,relocation_version=NEW.version,updated_at=NEW.created_at
 WHERE business_id=NEW.business_id AND id=NEW.record_id;
 END;
 DROP TRIGGER IF EXISTS guard_finance_recurring_expenses_update;
 CREATE TRIGGER guard_finance_recurring_expenses_update BEFORE UPDATE ON finance_recurring_expenses
 WHEN (NEW.business_id IS NOT OLD.business_id OR
 ((NEW.branch_id IS NOT OLD.branch_id OR NEW.relocation_version<>OLD.relocation_version)
 AND NOT (EXISTS (SELECT 1 FROM finance_workspace_corrections e WHERE e.kind='recurring'
 AND e.business_id=OLD.business_id AND e.record_id=OLD.id
 AND e.version=OLD.relocation_version+1 AND NEW.relocation_version=e.version
 AND e.source_branch_id=OLD.branch_id AND e.target_branch_id=NEW.branch_id
 AND e.source_account_id=OLD.account_id AND e.target_account_id=NEW.account_id
 AND e.source_category_id=OLD.category_id AND e.target_category_id=NEW.category_id
 AND e.created_at=NEW.updated_at) AND NEW.id IS OLD.id AND NEW.business_id IS OLD.business_id AND NEW.name IS OLD.name AND NEW.amount_minor IS OLD.amount_minor AND NEW.currency IS OLD.currency AND NEW.project_id IS OLD.project_id AND NEW.counterparty_name IS OLD.counterparty_name AND NEW.description IS OLD.description AND NEW.cadence IS OLD.cadence AND NEW.anchor_day IS OLD.anchor_day AND NEW.next_due_on IS OLD.next_due_on AND NEW.end_on IS OLD.end_on AND NEW.is_active IS OLD.is_active AND NEW.created_by_user_id IS OLD.created_by_user_id AND NEW.created_at IS OLD.created_at))) OR NOT EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=NEW.business_id AND a.branch_id=NEW.branch_id AND a.id=NEW.account_id)
 OR NOT EXISTS (SELECT 1 FROM finance_branches b WHERE b.business_id=NEW.business_id AND b.id=NEW.branch_id)
 BEGIN SELECT RAISE(ABORT,'finance branch mismatch'); END;
CREATE TRIGGER IF NOT EXISTS immutable_finance_workspace_corrections_update BEFORE UPDATE ON finance_workspace_corrections BEGIN SELECT RAISE(ABORT,'finance correction history immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_finance_workspace_corrections_delete BEFORE DELETE ON finance_workspace_corrections BEGIN SELECT RAISE(ABORT,'finance correction history immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_finance_workspace_opening_history_update BEFORE UPDATE ON finance_workspace_opening_history BEGIN SELECT RAISE(ABORT,'finance correction history immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_finance_workspace_opening_history_delete BEFORE DELETE ON finance_workspace_opening_history BEGIN SELECT RAISE(ABORT,'finance correction history immutable'); END;
