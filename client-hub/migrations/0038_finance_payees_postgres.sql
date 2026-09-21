-- HomeBudget-style Finance Payees. Payees are branch-scoped master data; transactions remain the ledger.
CREATE TABLE IF NOT EXISTS finance_payees (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 branch_id BIGINT NOT NULL,
 name TEXT NOT NULL,
 is_active BOOLEAN NOT NULL DEFAULT TRUE,
 created_by_user_id BIGINT REFERENCES users(id),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(business_id,branch_id,name),
 FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_payees_business_branch_name
 ON finance_payees(business_id,branch_id,is_active,name);

INSERT INTO finance_payees
 (business_id,branch_id,name,is_active,created_by_user_id,created_at,updated_at)
SELECT t.business_id,t.branch_id,TRIM(t.counterparty_name),TRUE,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM finance_transactions t
WHERE t.branch_id IS NOT NULL
  AND t.direction='EXPENSE'
  AND t.counterparty_name IS NOT NULL
  AND TRIM(t.counterparty_name)<>''
GROUP BY t.business_id,t.branch_id,TRIM(t.counterparty_name)
ON CONFLICT (business_id,branch_id,name) DO NOTHING;
