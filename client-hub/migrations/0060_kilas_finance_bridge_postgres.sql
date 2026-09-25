-- Optional Core-side links only. Finance remains the sole financial engine.
-- Explicit installer after 0055/0056/0057 and existing Finance schema.
CREATE TABLE IF NOT EXISTS kw_core_finance_connections (
 source_business_id BIGINT NOT NULL REFERENCES businesses(id),
 version BIGINT NOT NULL CHECK(version>0),
 finance_business_id BIGINT NOT NULL REFERENCES businesses(id),
 finance_branch_id BIGINT NOT NULL,
 enabled BOOLEAN NOT NULL,
 actor_user_id BIGINT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(source_business_id,version),
 UNIQUE(source_business_id,version,finance_business_id,finance_branch_id),
 FOREIGN KEY(finance_business_id,finance_branch_id) REFERENCES finance_branches(business_id,id)
);
CREATE TABLE IF NOT EXISTS kw_core_finance_customer_links (
 source_business_id BIGINT NOT NULL,
 core_customer_id TEXT NOT NULL,
 finance_business_id BIGINT NOT NULL,
 finance_customer_id BIGINT NOT NULL,
 finance_branch_id BIGINT NOT NULL,
 connection_version BIGINT NOT NULL,
 actor_user_id BIGINT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(source_business_id,core_customer_id,finance_business_id),
 UNIQUE(source_business_id,core_customer_id,finance_business_id,finance_customer_id),
 FOREIGN KEY(source_business_id,core_customer_id) REFERENCES kw_core_customers(business_id,id),
 FOREIGN KEY(finance_business_id,finance_customer_id) REFERENCES finance_customers(business_id,id),
 FOREIGN KEY(source_business_id,connection_version,finance_business_id,finance_branch_id)
 REFERENCES kw_core_finance_connections(source_business_id,version,finance_business_id,finance_branch_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_core_jobs_customer_identity ON kw_core_jobs(business_id,id,customer_id);
CREATE TABLE IF NOT EXISTS kw_core_finance_invoice_links (
 source_business_id BIGINT NOT NULL,
 core_job_id TEXT NOT NULL,
 core_customer_id TEXT NOT NULL,
 finance_business_id BIGINT NOT NULL,
 finance_branch_id BIGINT NOT NULL,
 finance_customer_id BIGINT NOT NULL,
 finance_invoice_id BIGINT NOT NULL,
 connection_version BIGINT NOT NULL,
 actor_user_id BIGINT NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,
 PRIMARY KEY(source_business_id,core_job_id),
 UNIQUE(finance_business_id,finance_invoice_id),
 FOREIGN KEY(source_business_id,core_job_id,core_customer_id) REFERENCES kw_core_jobs(business_id,id,customer_id),
 FOREIGN KEY(source_business_id,core_customer_id,finance_business_id,finance_customer_id)
 REFERENCES kw_core_finance_customer_links(source_business_id,core_customer_id,finance_business_id,finance_customer_id),
 FOREIGN KEY(finance_business_id,finance_invoice_id) REFERENCES finance_invoices(business_id,id),
 FOREIGN KEY(source_business_id,connection_version,finance_business_id,finance_branch_id)
 REFERENCES kw_core_finance_connections(source_business_id,version,finance_business_id,finance_branch_id)
);
CREATE TABLE IF NOT EXISTS kw_core_finance_operations (
 source_business_id BIGINT NOT NULL REFERENCES businesses(id),
 operation_key TEXT NOT NULL CHECK(length(operation_key)=32),
 request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
 kind TEXT NOT NULL CHECK(kind IN ('connection','customer','invoice')),
 actor_user_id BIGINT NOT NULL REFERENCES users(id),
 reference TEXT NOT NULL,
 finance_business_id BIGINT NOT NULL REFERENCES businesses(id),
 connection_version BIGINT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(source_business_id,operation_key),
 FOREIGN KEY(source_business_id,connection_version) REFERENCES kw_core_finance_connections(source_business_id,version)
);
