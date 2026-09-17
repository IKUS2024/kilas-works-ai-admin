-- Phase 6B: normalized staging only, no raw statement bytes or bank credentials.
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_transactions_business_id ON finance_transactions(business_id,id);
CREATE TABLE IF NOT EXISTS finance_bank_imports (
 id BIGSERIAL PRIMARY KEY,
 business_id BIGINT NOT NULL REFERENCES businesses(id), account_id BIGINT NOT NULL,
 source_kind TEXT NOT NULL CHECK(source_kind IN ('CSV','PDF','IMAGES')),
 display_label TEXT NOT NULL, file_hash TEXT NOT NULL CHECK(length(file_hash)=64 AND file_hash=lower(file_hash)),
 source_count INTEGER NOT NULL CHECK(source_count BETWEEN 1 AND 10),
 status TEXT NOT NULL DEFAULT 'REVIEW' CHECK(status IN ('REVIEW','OPEN','COMPLETED','CANCELLED')),
 revision INTEGER NOT NULL DEFAULT 0,
 imported_by_user_id BIGINT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(business_id,id), UNIQUE(business_id,account_id,file_hash),
 FOREIGN KEY(business_id,account_id) REFERENCES finance_accounts(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_finance_bank_imports_business ON finance_bank_imports(business_id,status,id);
CREATE TABLE IF NOT EXISTS finance_bank_rows (
 id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL REFERENCES businesses(id), import_id BIGINT NOT NULL,
 row_index INTEGER NOT NULL CHECK(row_index BETWEEN 1 AND 1000),
 row_hash TEXT NOT NULL CHECK(length(row_hash)=64 AND row_hash=lower(row_hash)),
 occurred_on TEXT NOT NULL CHECK(length(occurred_on)=10), direction TEXT NOT NULL CHECK(direction IN ('INCOME','EXPENSE')),
 amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 description TEXT NOT NULL, reference TEXT,
 reconciliation_status TEXT NOT NULL DEFAULT 'UNMATCHED' CHECK(reconciliation_status IN ('UNMATCHED','MATCHED','POSTED','IGNORED')),
 matched_transaction_id BIGINT, created_transaction_id BIGINT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(business_id,id), UNIQUE(business_id,import_id,row_index), UNIQUE(business_id,row_hash),
 FOREIGN KEY(business_id,import_id) REFERENCES finance_bank_imports(business_id,id),
 FOREIGN KEY(business_id,matched_transaction_id) REFERENCES finance_transactions(business_id,id),
 FOREIGN KEY(business_id,created_transaction_id) REFERENCES finance_transactions(business_id,id),
 CHECK((reconciliation_status='MATCHED' AND matched_transaction_id IS NOT NULL AND created_transaction_id IS NULL)
 OR (reconciliation_status='POSTED' AND created_transaction_id IS NOT NULL AND matched_transaction_id IS NULL)
 OR (reconciliation_status IN ('UNMATCHED','IGNORED') AND matched_transaction_id IS NULL AND created_transaction_id IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_finance_bank_rows_import ON finance_bank_rows(business_id,import_id,reconciliation_status,row_index);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_bank_rows_one_link ON finance_bank_rows(business_id,COALESCE(matched_transaction_id,created_transaction_id))
 WHERE matched_transaction_id IS NOT NULL OR created_transaction_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_bank_origin ON finance_transactions(business_id,source_ref) WHERE source_type='FINANCE_BANK_IMPORT';
CREATE INDEX IF NOT EXISTS idx_finance_bank_candidates ON finance_transactions(business_id,account_id,status,occurred_on,id);
