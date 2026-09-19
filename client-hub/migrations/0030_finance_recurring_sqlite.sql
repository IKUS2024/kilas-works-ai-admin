-- Finance recurring expense rules and immutable occurrence history only.
CREATE TABLE IF NOT EXISTS finance_recurring_expenses (
 id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL REFERENCES businesses(id), name TEXT NOT NULL,
 amount_minor INTEGER NOT NULL CHECK(typeof(amount_minor)='integer' AND amount_minor>0), currency TEXT NOT NULL DEFAULT 'IDR' CHECK(currency IN ('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')),
 account_id INTEGER NOT NULL, category_id INTEGER NOT NULL REFERENCES finance_categories(id),
 project_id INTEGER REFERENCES projects(id), counterparty_name TEXT, description TEXT,
 cadence TEXT NOT NULL CHECK(cadence IN ('WEEKLY','MONTHLY')), anchor_day INTEGER CHECK(anchor_day BETWEEN 1 AND 31),
 next_due_on TEXT NOT NULL, end_on TEXT,
 is_active BOOLEAN NOT NULL DEFAULT TRUE, created_by_user_id INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(business_id,id),
 CHECK((cadence='MONTHLY' AND anchor_day IS NOT NULL) OR (cadence='WEEKLY' AND anchor_day IS NULL)),
 FOREIGN KEY(business_id,account_id) REFERENCES finance_accounts(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_recurring_business_due ON finance_recurring_expenses(business_id,is_active,next_due_on);
CREATE INDEX IF NOT EXISTS idx_finance_recurring_business_project ON finance_recurring_expenses(business_id,project_id);
CREATE TABLE IF NOT EXISTS finance_recurring_postings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL REFERENCES businesses(id), recurring_expense_id INTEGER NOT NULL,
 scheduled_on TEXT NOT NULL, ledger_transaction_id INTEGER UNIQUE REFERENCES finance_transactions(id), created_at TEXT NOT NULL,
 UNIQUE(business_id,recurring_expense_id,scheduled_on),
 FOREIGN KEY(business_id,recurring_expense_id) REFERENCES finance_recurring_expenses(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_recurring_postings_business_rule_date ON finance_recurring_postings(business_id,recurring_expense_id,scheduled_on);
CREATE INDEX IF NOT EXISTS idx_finance_recurring_postings_business_date ON finance_recurring_postings(business_id,scheduled_on);
