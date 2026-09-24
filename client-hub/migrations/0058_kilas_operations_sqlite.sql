-- Phase 6 additive WEB operations only. Explicit install after 0055/0056/0057.
CREATE TABLE IF NOT EXISTS kw_core_attention (
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    id TEXT NOT NULL,
    source_key TEXT NOT NULL CHECK(length(source_key) BETWEEN 1 AND 160),
    reason TEXT NOT NULL CHECK(reason IN ('HUMAN_REPLY_NEEDED','READY_FOR_QUOTE','NEEDS_INFORMATION_STUCK','FOLLOWUP_DUE','REVIEW_REQUEST_DUE','AUTOMATION_FAILED')),
    priority TEXT NOT NULL CHECK(priority IN ('NORMAL','HIGH')),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','RESOLVED')),
    customer_id TEXT,
    conversation_id TEXT,
    job_id TEXT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    resolved_at BIGINT,
    PRIMARY KEY(business_id,id),
    UNIQUE(business_id,source_key),
    CHECK(conversation_id IS NULL OR customer_id IS NOT NULL),
    CHECK(job_id IS NULL OR customer_id IS NOT NULL),
    FOREIGN KEY(business_id,customer_id) REFERENCES kw_core_customers(business_id,id),
    FOREIGN KEY(business_id,conversation_id,customer_id) REFERENCES kw_web_customer_links(business_id,conversation_id,customer_id),
    FOREIGN KEY(business_id,job_id) REFERENCES kw_core_jobs(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_kw_attention_open ON kw_core_attention(business_id,status,priority,created_at);
CREATE TABLE IF NOT EXISTS kw_core_automation_config (
    business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
    followup_enabled INTEGER NOT NULL DEFAULT 0 CHECK(followup_enabled IN (0,1)),
    delay_hours INTEGER NOT NULL DEFAULT 24 CHECK(delay_hours BETWEEN 1 AND 168),
    max_attempts INTEGER NOT NULL DEFAULT 1 CHECK(max_attempts BETWEEN 1 AND 3),
    review_enabled INTEGER NOT NULL DEFAULT 0 CHECK(review_enabled IN (0,1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
    updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS kw_core_automation_runs (
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    source_key TEXT NOT NULL CHECK(length(source_key) BETWEEN 1 AND 160),
    kind TEXT NOT NULL CHECK(kind IN ('CUSTOMER_INACTIVE_FOLLOWUP','JOB_COMPLETED_REVIEW_REQUEST')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DELIVERED','SKIPPED','FAILED')),
    customer_id TEXT NOT NULL,
    conversation_id TEXT,
    job_id TEXT,
    conversation_version INTEGER,
    customer_message_id BIGINT,
    attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 3),
    due_at BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    delivered_at BIGINT,
    error_code TEXT CHECK(error_code IS NULL OR error_code IN ('STALE','UNAVAILABLE','WRITE_FAILED','DISABLED')),
    PRIMARY KEY(business_id,source_key),
    FOREIGN KEY(business_id,customer_id) REFERENCES kw_core_customers(business_id,id),
    FOREIGN KEY(business_id,conversation_id,customer_id) REFERENCES kw_web_customer_links(business_id,conversation_id,customer_id),
    FOREIGN KEY(business_id,job_id) REFERENCES kw_core_jobs(business_id,id)
);
CREATE INDEX IF NOT EXISTS idx_kw_automation_due ON kw_core_automation_runs(business_id,status,due_at);
