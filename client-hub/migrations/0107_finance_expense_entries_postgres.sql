-- Additive expense allocation/receipt metadata. Existing ledger rows are unchanged.
CREATE TABLE IF NOT EXISTS finance_expense_entries (
 transaction_id BIGINT PRIMARY KEY REFERENCES finance_transactions(id) ON DELETE CASCADE,
 business_id BIGINT NOT NULL REFERENCES businesses(id),actor_user_id BIGINT NOT NULL REFERENCES users(id),submission_key TEXT NOT NULL,payload_hash TEXT NOT NULL,
 UNIQUE(business_id,submission_key));
CREATE TABLE IF NOT EXISTS finance_expense_allocations (
 transaction_id BIGINT NOT NULL REFERENCES finance_transactions(id) ON DELETE CASCADE,
 sequence INTEGER NOT NULL,category_id BIGINT NOT NULL REFERENCES finance_categories(id),
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0),PRIMARY KEY(transaction_id,sequence),UNIQUE(transaction_id,category_id));
CREATE INDEX IF NOT EXISTS idx_expense_allocation_category ON finance_expense_allocations(category_id,transaction_id);
CREATE TABLE IF NOT EXISTS finance_expense_receipts (
 transaction_id BIGINT PRIMARY KEY REFERENCES finance_transactions(id) ON DELETE CASCADE,
 filename TEXT NOT NULL,mime_type TEXT NOT NULL,content BYTEA NOT NULL,byte_size INTEGER NOT NULL CHECK(byte_size>0 AND byte_size<=4194304),digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS finance_expense_revisions (
 id BIGSERIAL PRIMARY KEY,transaction_id BIGINT NOT NULL REFERENCES finance_transactions(id) ON DELETE CASCADE,
 before_json TEXT NOT NULL,after_json TEXT NOT NULL,actor_user_id BIGINT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL);
CREATE OR REPLACE VIEW finance_category_amounts AS
 SELECT t.id,t.business_id,t.branch_id,t.account_id,t.occurred_on,t.status,t.direction,t.currency,
 COALESCE(a.category_id,t.category_id) AS category_id,COALESCE(a.amount_minor,t.amount_minor) AS amount_minor
 FROM finance_transactions t LEFT JOIN finance_expense_allocations a ON a.transaction_id=t.id;
