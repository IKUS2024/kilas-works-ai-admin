CREATE TABLE IF NOT EXISTS finance_internal_transfers (
 id BIGSERIAL PRIMARY KEY,business_id BIGINT NOT NULL REFERENCES businesses(id),branch_id BIGINT NOT NULL,
 from_account_id BIGINT NOT NULL,to_account_id BIGINT NOT NULL,
 currency TEXT NOT NULL CHECK(currency IN ('IDR','USD','SGD','MYR','EUR','GBP','AUD','JPY','CNY','HKD','THB')),
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0),occurred_on TEXT NOT NULL,
 idempotency_key TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'POSTED' CHECK(status IN ('POSTED','VOID')),
 created_by_user_id BIGINT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,
 voided_at TEXT,voided_by_user_id BIGINT REFERENCES users(id),
 CHECK(from_account_id<>to_account_id),UNIQUE(business_id,idempotency_key),
 FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id),
 FOREIGN KEY(business_id,branch_id,from_account_id) REFERENCES finance_accounts(business_id,branch_id,id),
 FOREIGN KEY(business_id,branch_id,to_account_id) REFERENCES finance_accounts(business_id,branch_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_internal_transfer_scope ON finance_internal_transfers(business_id,branch_id,status,occurred_on,id);
ALTER TABLE finance_transactions ADD COLUMN IF NOT EXISTS notes TEXT;
