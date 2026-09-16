-- Finance Phase 1A only. Additive and idempotent. No seeding/backfill on existing businesses.
CREATE TABLE IF NOT EXISTS finance_accounts (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 name TEXT NOT NULL,
 account_type TEXT NOT NULL CHECK(account_type IN ('CASH','BANK','EWALLET','OTHER')),
 currency TEXT NOT NULL DEFAULT 'IDR' CHECK(length(currency)=3 AND currency=upper(currency)),
 opening_balance_minor BIGINT NOT NULL DEFAULT 0,
 is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(business_id,name,account_type,currency),
 UNIQUE(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_accounts_business ON finance_accounts(business_id);

CREATE TABLE IF NOT EXISTS finance_categories (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 direction TEXT NOT NULL CHECK(direction IN ('INCOME','EXPENSE')),
 name TEXT NOT NULL,
 is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(business_id,direction,name),
 UNIQUE(business_id,id,direction)
);
CREATE INDEX IF NOT EXISTS idx_finance_categories_business_direction ON finance_categories(business_id,direction);

CREATE TABLE IF NOT EXISTS finance_transactions (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 direction TEXT NOT NULL CHECK(direction IN ('INCOME','EXPENSE')),
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 currency TEXT NOT NULL DEFAULT 'IDR' CHECK(length(currency)=3 AND currency=upper(currency)),
 account_id BIGINT NOT NULL,
 category_id BIGINT NOT NULL,
 occurred_on TEXT NOT NULL CHECK(length(occurred_on)=10),
 description TEXT,
 counterparty_name TEXT,
 project_id BIGINT REFERENCES projects(id),
 source_type TEXT,
 source_ref TEXT,
 status TEXT NOT NULL DEFAULT 'POSTED' CHECK(status IN ('POSTED','VOID')),
 created_by_user_id BIGINT REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 voided_at TEXT,
 voided_by_user_id BIGINT REFERENCES users(id),
 FOREIGN KEY(business_id,account_id) REFERENCES finance_accounts(business_id,id),
 FOREIGN KEY(business_id,category_id,direction) REFERENCES finance_categories(business_id,id,direction)
);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_business_period ON finance_transactions(business_id,status,occurred_on,id);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_business_account ON finance_transactions(business_id,account_id);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_business_category ON finance_transactions(business_id,category_id);
CREATE INDEX IF NOT EXISTS idx_finance_transactions_business_project ON finance_transactions(business_id,project_id);
