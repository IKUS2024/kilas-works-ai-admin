CREATE TABLE IF NOT EXISTS finance_fx_exchanges (
 id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL REFERENCES businesses(id),branch_id INTEGER NOT NULL,
 from_account_id INTEGER NOT NULL,to_account_id INTEGER NOT NULL,
 from_currency TEXT NOT NULL CHECK(from_currency IN ('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')),
 to_currency TEXT NOT NULL CHECK(to_currency IN ('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')),
 from_amount_minor INTEGER NOT NULL CHECK(typeof(from_amount_minor)='integer' AND from_amount_minor>0),
 to_amount_minor INTEGER NOT NULL CHECK(typeof(to_amount_minor)='integer' AND to_amount_minor>0),
 occurred_on TEXT NOT NULL,actual_rate TEXT NOT NULL,reference_rate TEXT,rate_source TEXT,rate_as_of TEXT,note TEXT,
 status TEXT NOT NULL DEFAULT 'POSTED' CHECK(status IN ('POSTED','VOID')),
 created_by_user_id INTEGER REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 voided_at TEXT,voided_by_user_id INTEGER REFERENCES users(id),CHECK(from_currency<>to_currency),UNIQUE(business_id,id),
 FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id),
 FOREIGN KEY(business_id,branch_id,from_account_id) REFERENCES finance_accounts(business_id,branch_id,id),
 FOREIGN KEY(business_id,branch_id,to_account_id) REFERENCES finance_accounts(business_id,branch_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_fx_business_date ON finance_fx_exchanges(business_id,branch_id,status,occurred_on,id);
