CREATE TABLE IF NOT EXISTS finance_branches (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
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
ALTER TABLE finance_accounts ADD COLUMN IF NOT EXISTS branch_id BIGINT REFERENCES finance_branches(id);
UPDATE finance_accounts SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_accounts.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS branch_id BIGINT REFERENCES finance_branches(id);
UPDATE finance_transactions SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_transactions.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_transactions_branch ON finance_transactions(business_id,branch_id);
ALTER TABLE finance_invoices ADD COLUMN IF NOT EXISTS branch_id BIGINT REFERENCES finance_branches(id);
UPDATE finance_invoices SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_invoices.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_invoices_branch ON finance_invoices(business_id,branch_id);
ALTER TABLE finance_recurring_expenses ADD COLUMN IF NOT EXISTS branch_id BIGINT REFERENCES finance_branches(id);
UPDATE finance_recurring_expenses SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_recurring_expenses.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_recurring_expenses_branch ON finance_recurring_expenses(business_id,branch_id);
ALTER TABLE finance_bank_imports ADD COLUMN IF NOT EXISTS branch_id BIGINT REFERENCES finance_branches(id);
UPDATE finance_bank_imports SET branch_id=(SELECT b.id FROM finance_branches b WHERE b.business_id=finance_bank_imports.business_id AND b.is_default=TRUE) WHERE branch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_finance_bank_imports_branch ON finance_bank_imports(business_id,branch_id);
DO $$ DECLARE constraint_name TEXT;
BEGIN
 SELECT conname INTO constraint_name FROM pg_constraint WHERE conrelid='finance_accounts'::regclass AND contype='u'
 AND pg_get_constraintdef(oid)='UNIQUE (business_id, name, account_type, currency)';
 IF constraint_name IS NOT NULL THEN EXECUTE format('ALTER TABLE finance_accounts DROP CONSTRAINT %I',constraint_name); END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_accounts_branch_name ON finance_accounts(business_id,branch_id,name,account_type,currency);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_accounts_branch_id ON finance_accounts(business_id,branch_id,id);
ALTER TABLE finance_accounts ALTER COLUMN branch_id SET NOT NULL;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_accounts_branch') THEN ALTER TABLE finance_accounts ADD CONSTRAINT fk_finance_accounts_branch FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id); END IF; END $$;
ALTER TABLE finance_transactions ALTER COLUMN branch_id SET NOT NULL;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_transactions_branch') THEN ALTER TABLE finance_transactions ADD CONSTRAINT fk_finance_transactions_branch FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id); END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_transactions_branch_account') THEN ALTER TABLE finance_transactions ADD CONSTRAINT fk_finance_transactions_branch_account FOREIGN KEY(business_id,branch_id,account_id) REFERENCES finance_accounts(business_id,branch_id,id); END IF; END $$;
ALTER TABLE finance_invoices ALTER COLUMN branch_id SET NOT NULL;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_invoices_branch') THEN ALTER TABLE finance_invoices ADD CONSTRAINT fk_finance_invoices_branch FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id); END IF; END $$;
ALTER TABLE finance_recurring_expenses ALTER COLUMN branch_id SET NOT NULL;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_recurring_expenses_branch') THEN ALTER TABLE finance_recurring_expenses ADD CONSTRAINT fk_finance_recurring_expenses_branch FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id); END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_recurring_expenses_branch_account') THEN ALTER TABLE finance_recurring_expenses ADD CONSTRAINT fk_finance_recurring_expenses_branch_account FOREIGN KEY(business_id,branch_id,account_id) REFERENCES finance_accounts(business_id,branch_id,id); END IF; END $$;
ALTER TABLE finance_bank_imports ALTER COLUMN branch_id SET NOT NULL;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_bank_imports_branch') THEN ALTER TABLE finance_bank_imports ADD CONSTRAINT fk_finance_bank_imports_branch FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id); END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_finance_bank_imports_branch_account') THEN ALTER TABLE finance_bank_imports ADD CONSTRAINT fk_finance_bank_imports_branch_account FOREIGN KEY(business_id,branch_id,account_id) REFERENCES finance_accounts(business_id,branch_id,id); END IF; END $$;
CREATE OR REPLACE FUNCTION finance_branch_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.branch_id IS DISTINCT FROM OLD.branch_id OR NEW.business_id IS DISTINCT FROM OLD.business_id THEN
 RAISE EXCEPTION 'finance branch mismatch'; END IF; RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_branch_identity ON finance_accounts;
CREATE TRIGGER guard_branch_identity BEFORE UPDATE ON finance_accounts FOR EACH ROW EXECUTE FUNCTION finance_branch_immutable();
DROP TRIGGER IF EXISTS guard_branch_identity ON finance_transactions;
CREATE TRIGGER guard_branch_identity BEFORE UPDATE ON finance_transactions FOR EACH ROW EXECUTE FUNCTION finance_branch_immutable();
DROP TRIGGER IF EXISTS guard_branch_identity ON finance_invoices;
CREATE TRIGGER guard_branch_identity BEFORE UPDATE ON finance_invoices FOR EACH ROW EXECUTE FUNCTION finance_branch_immutable();
DROP TRIGGER IF EXISTS guard_branch_identity ON finance_recurring_expenses;
CREATE TRIGGER guard_branch_identity BEFORE UPDATE ON finance_recurring_expenses FOR EACH ROW EXECUTE FUNCTION finance_branch_immutable();
DROP TRIGGER IF EXISTS guard_branch_identity ON finance_bank_imports;
CREATE TRIGGER guard_branch_identity BEFORE UPDATE ON finance_bank_imports FOR EACH ROW EXECUTE FUNCTION finance_branch_immutable();
CREATE OR REPLACE FUNCTION finance_payment_branch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM finance_invoices i JOIN finance_accounts a ON a.business_id=i.business_id AND a.branch_id=i.branch_id WHERE i.business_id=NEW.business_id AND i.id=NEW.invoice_id AND a.id=NEW.account_id) THEN RAISE EXCEPTION 'finance payment branch mismatch'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_finance_payment_branch ON finance_invoice_payments;
CREATE TRIGGER guard_finance_payment_branch BEFORE INSERT OR UPDATE ON finance_invoice_payments FOR EACH ROW EXECUTE FUNCTION finance_payment_branch_guard();
CREATE TABLE IF NOT EXISTS finance_transaction_revisions (
 id BIGSERIAL PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
 transaction_id INTEGER NOT NULL REFERENCES finance_transactions(id),
 before_json TEXT NOT NULL, after_json TEXT NOT NULL,
 actor_user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL
);
