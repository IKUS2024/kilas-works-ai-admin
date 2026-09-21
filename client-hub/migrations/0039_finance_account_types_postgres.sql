-- User-manageable Finance account type labels. Additive only; legacy finance_accounts.account_type remains the stable accounting bucket.
CREATE TABLE IF NOT EXISTS finance_account_type_options (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 name TEXT NOT NULL,
 legacy_type TEXT NOT NULL CHECK(legacy_type IN ('CASH','BANK','EWALLET','OTHER')),
 is_default BOOLEAN NOT NULL DEFAULT FALSE,
 is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(business_id,name),
 UNIQUE(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_account_type_options_business
 ON finance_account_type_options(business_id,is_active,id);

CREATE TABLE IF NOT EXISTS finance_account_type_assignments (
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 account_id BIGINT NOT NULL,
 option_id BIGINT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(business_id,account_id),
 FOREIGN KEY(business_id,account_id) REFERENCES finance_accounts(business_id,id),
 FOREIGN KEY(business_id,option_id) REFERENCES finance_account_type_options(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_account_type_assignments_option
 ON finance_account_type_assignments(business_id,option_id);
