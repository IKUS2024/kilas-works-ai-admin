-- Internal product candidates discovered for Kilas Order requests.
CREATE TABLE IF NOT EXISTS kilas_order_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES kilas_order_requests(id) ON DELETE CASCADE,
    rank_no INTEGER NOT NULL DEFAULT 0,
    product_name TEXT NOT NULL,
    price_text TEXT,
    currency TEXT,
    condition_text TEXT,
    seller_name TEXT,
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    source_title TEXT,
    availability TEXT,
    trust_score INTEGER NOT NULL DEFAULT 0,
    trust_level TEXT NOT NULL DEFAULT 'REVIEW',
    trust_reason TEXT,
    match_reason TEXT,
    risk_flags_json TEXT NOT NULL DEFAULT '[]',
    evidence_text TEXT,
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(request_id, source_url),
    CHECK (trust_score >= 0 AND trust_score <= 100),
    CHECK (trust_level IN ('HIGH','MEDIUM','REVIEW')),
    CHECK (status IN ('DISCOVERED','VERIFIED','REJECTED'))
);
CREATE INDEX IF NOT EXISTS idx_kilas_order_candidates_request_rank
    ON kilas_order_candidates(request_id, rank_no, id);
CREATE INDEX IF NOT EXISTS idx_kilas_order_candidates_status
    ON kilas_order_candidates(status, created_at);
