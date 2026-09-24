-- Phase 4 additive Jobs only. Requires explicit 0055 and 0056 installation.
-- Triple key enforces that the source conversation resolves to the selected customer.
CREATE UNIQUE INDEX IF NOT EXISTS idx_kw_web_link_job_parent
    ON kw_web_customer_links(business_id, conversation_id, customer_id);
CREATE TABLE IF NOT EXISTS kw_core_jobs (
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    conversation_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('ORDER','BOOKING','SHIPMENT','PROJECT','SERVICE','GENERIC')),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
    summary TEXT NOT NULL DEFAULT '' CHECK(length(summary)<=2000),
    status TEXT NOT NULL DEFAULT 'NEW' CHECK(status IN
        ('NEW','NEEDS_INFORMATION','READY_FOR_QUOTE','QUOTED','APPROVED','IN_PROGRESS','COMPLETED','CANCELLED')),
    fields_json TEXT NOT NULL DEFAULT '{}' CHECK(length(fields_json)<=8192),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY(business_id,id),
    FOREIGN KEY(business_id,customer_id) REFERENCES kw_core_customers(business_id,id),
    FOREIGN KEY(business_id,conversation_id,customer_id)
        REFERENCES kw_web_customer_links(business_id,conversation_id,customer_id)
);
CREATE INDEX IF NOT EXISTS idx_kw_jobs_status ON kw_core_jobs(business_id,status,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kw_jobs_customer ON kw_core_jobs(business_id,customer_id,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kw_jobs_activity ON kw_core_jobs(business_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS kw_core_job_operations (
    business_id INTEGER NOT NULL,
    operation_key TEXT NOT NULL CHECK(length(operation_key) BETWEEN 16 AND 128),
    request_hash TEXT NOT NULL,
    job_id TEXT NOT NULL,
    result_version INTEGER NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY(business_id,operation_key),
    FOREIGN KEY(business_id,job_id) REFERENCES kw_core_jobs(business_id,id)
);
