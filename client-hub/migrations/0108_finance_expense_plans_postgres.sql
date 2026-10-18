-- Additive metadata/schedules only. No legacy rows, balances or history are rewritten.
CREATE TABLE IF NOT EXISTS finance_catalog_items (
 business_id BIGINT NOT NULL REFERENCES businesses(id),scope_key TEXT NOT NULL,canonical_key TEXT NOT NULL,
 category_id BIGINT NOT NULL REFERENCES finance_categories(id),sort_order INTEGER NOT NULL,builtin_name TEXT NOT NULL,
 PRIMARY KEY(business_id,scope_key,canonical_key),UNIQUE(business_id,scope_key,category_id));
CREATE TABLE IF NOT EXISTS finance_installment_plans (
 id BIGSERIAL PRIMARY KEY,business_id BIGINT NOT NULL REFERENCES businesses(id),branch_id BIGINT NOT NULL REFERENCES finance_branches(id),
 actor_user_id BIGINT NOT NULL REFERENCES users(id),submission_key TEXT NOT NULL,payload_hash TEXT NOT NULL,
 total_minor BIGINT NOT NULL CHECK(total_minor>0),currency TEXT NOT NULL,account_id BIGINT NOT NULL REFERENCES finance_accounts(id),
 category_id BIGINT NOT NULL REFERENCES finance_categories(id),purchase_on TEXT NOT NULL,notes TEXT,payee TEXT,
 splits_json TEXT NOT NULL,duration_months INTEGER NOT NULL,schedule TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(business_id,submission_key));
CREATE TABLE IF NOT EXISTS finance_installment_items (
 plan_id BIGINT NOT NULL REFERENCES finance_installment_plans(id),sequence INTEGER NOT NULL,
 recurring_id BIGINT NOT NULL UNIQUE REFERENCES finance_recurring_expenses(id),amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 due_on TEXT NOT NULL,allocations_json TEXT NOT NULL,PRIMARY KEY(plan_id,sequence));
CREATE TABLE IF NOT EXISTS finance_installment_receipts (
 plan_id BIGINT PRIMARY KEY REFERENCES finance_installment_plans(id),filename TEXT NOT NULL,mime_type TEXT NOT NULL,
 content BYTEA NOT NULL,byte_size INTEGER NOT NULL CHECK(byte_size>0 AND byte_size<=4194304),digest TEXT NOT NULL);
