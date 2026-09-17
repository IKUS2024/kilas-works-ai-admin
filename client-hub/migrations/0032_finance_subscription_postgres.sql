-- Independent Finance entitlement and platform subscription bills. No customer ledger.
CREATE TABLE IF NOT EXISTS finance_entitlements (
 business_id BIGINT PRIMARY KEY REFERENCES businesses(id),
 trial_started_at TEXT, trial_until TEXT, paid_until TEXT, updated_at TEXT NOT NULL,
 CHECK ((trial_started_at IS NULL AND trial_until IS NULL) OR (trial_started_at IS NOT NULL AND trial_until IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS finance_subscription_bills (
 id BIGSERIAL PRIMARY KEY, business_id BIGINT NOT NULL REFERENCES businesses(id),
 product_key TEXT NOT NULL CHECK(product_key='finance'), amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
 currency TEXT NOT NULL CHECK(currency='IDR'),
 status TEXT NOT NULL CHECK(status IN ('PENDING','REVIEW','REJECTED','VERIFIED')),
 proof_content BYTEA, proof_mime TEXT, proof_hash TEXT,
 created_by_user_id BIGINT NOT NULL REFERENCES users(id), reviewed_by_user_id BIGINT REFERENCES users(id),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, applied_until TEXT,
 UNIQUE(business_id,id),
 CHECK ((status='VERIFIED' AND applied_until IS NOT NULL AND reviewed_by_user_id IS NOT NULL) OR (status<>'VERIFIED' AND applied_until IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_bill_pending ON finance_subscription_bills(business_id) WHERE status<>'VERIFIED';
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_bill_proof ON finance_subscription_bills(proof_hash) WHERE proof_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_finance_bill_business ON finance_subscription_bills(business_id,id);
CREATE TABLE IF NOT EXISTS product_business_setups (
 user_id BIGINT NOT NULL REFERENCES users(id), intent_key TEXT NOT NULL,
 business_id BIGINT NOT NULL REFERENCES businesses(id), PRIMARY KEY(user_id,intent_key)
);

CREATE TABLE IF NOT EXISTS finance_bill_requests (
 business_id BIGINT NOT NULL REFERENCES businesses(id), request_key TEXT NOT NULL CHECK(length(request_key)=32),
 bill_id BIGINT NOT NULL, PRIMARY KEY(business_id,request_key),
 FOREIGN KEY(business_id,bill_id) REFERENCES finance_subscription_bills(business_id,id)
);
