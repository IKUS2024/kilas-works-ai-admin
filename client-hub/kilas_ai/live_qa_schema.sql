CREATE TABLE IF NOT EXISTS kilas_live_qa_grants (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    session_digest TEXT NOT NULL UNIQUE,
    started_ms BIGINT NOT NULL,
    deadline_ms BIGINT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','CLOSED')),
    reserved_microusd INTEGER NOT NULL DEFAULT 0 CHECK(reserved_microusd BETWEEN 0 AND 100000)
);
CREATE TABLE IF NOT EXISTS kilas_live_qa_operations (
    grant_id TEXT NOT NULL REFERENCES kilas_live_qa_grants(id),
    kind TEXT NOT NULL CHECK(kind IN ('STT','TRANSLATE','REPLY')),
    operation_key TEXT NOT NULL,
    reserved_microusd INTEGER NOT NULL CHECK(reserved_microusd>0),
    started_ms BIGINT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DISPATCHED','COMPLETED','UNCERTAIN')),
    PRIMARY KEY(grant_id,kind,operation_key)
);
