-- Finance receivables only, separate from platform commerce. No historical backfill.
CREATE TABLE IF NOT EXISTS finance_customers (
 id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL REFERENCES businesses(id), name TEXT NOT NULL,
 phone TEXT, email TEXT, notes TEXT, is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_customers_business ON finance_customers(business_id);
CREATE INDEX IF NOT EXISTS idx_finance_customers_business_name ON finance_customers(business_id,name);
CREATE TABLE IF NOT EXISTS finance_invoices (
 id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL REFERENCES businesses(id), customer_id BIGINT NOT NULL,
 invoice_number TEXT NOT NULL UNIQUE, issue_date TEXT NOT NULL, due_date TEXT NOT NULL CHECK(due_date>=issue_date),
 currency TEXT NOT NULL DEFAULT 'IDR' CHECK(currency IN ('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')),
 status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','ISSUED','PARTIALLY_PAID','PAID','VOID')),
 notes TEXT, created_by_user_id BIGINT REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 voided_at TEXT, voided_by_user_id BIGINT REFERENCES users(id), UNIQUE(business_id,id),
 FOREIGN KEY(business_id,customer_id) REFERENCES finance_customers(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_invoices_business_status ON finance_invoices(business_id,status);
CREATE INDEX IF NOT EXISTS idx_finance_invoices_business_due ON finance_invoices(business_id,due_date);
CREATE INDEX IF NOT EXISTS idx_finance_invoices_business_customer ON finance_invoices(business_id,customer_id);
CREATE TABLE IF NOT EXISTS finance_invoice_items (
 id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL REFERENCES businesses(id), invoice_id BIGINT NOT NULL,
 description TEXT NOT NULL, quantity BIGINT NOT NULL CHECK(quantity>0), unit_price_minor BIGINT NOT NULL CHECK(unit_price_minor>=0), created_at TEXT NOT NULL,
 FOREIGN KEY(business_id,invoice_id) REFERENCES finance_invoices(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_items_business_invoice ON finance_invoice_items(business_id,invoice_id);
CREATE TABLE IF NOT EXISTS finance_invoice_payments (
 id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL REFERENCES businesses(id), invoice_id BIGINT NOT NULL,
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0), paid_on TEXT NOT NULL,
 account_id BIGINT NOT NULL, category_id BIGINT NOT NULL,
 ledger_transaction_id BIGINT UNIQUE REFERENCES finance_transactions(id), note TEXT,
 idempotency_key TEXT NOT NULL, created_by_user_id BIGINT REFERENCES users(id), created_at TEXT NOT NULL,
 UNIQUE(business_id,idempotency_key),
 FOREIGN KEY(business_id,invoice_id) REFERENCES finance_invoices(business_id,id),
 FOREIGN KEY(business_id,account_id) REFERENCES finance_accounts(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_payments_business_invoice ON finance_invoice_payments(business_id,invoice_id);
CREATE INDEX IF NOT EXISTS idx_finance_payments_business_date ON finance_invoice_payments(business_id,paid_on);
ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS customer_id BIGINT REFERENCES finance_customers(id);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_business_customer ON finance_transactions(business_id,customer_id);
