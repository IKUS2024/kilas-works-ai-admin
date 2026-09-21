-- Monthly expense budgets. Planning only; never posts ledger transactions.
CREATE TABLE IF NOT EXISTS finance_budgets (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 branch_id BIGINT NOT NULL,
 month TEXT NOT NULL CHECK(length(month)=7),
 category_id BIGINT NOT NULL REFERENCES finance_categories(id),
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 currency TEXT NOT NULL CHECK(currency IN ('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')),
 created_by_user_id BIGINT REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(business_id,branch_id,month,category_id),
 FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_budgets_business_month ON finance_budgets(business_id,branch_id,month);
