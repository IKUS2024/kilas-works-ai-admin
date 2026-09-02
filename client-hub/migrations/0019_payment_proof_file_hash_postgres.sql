-- Payment verification hardening — file-hash duplicate-proof detection (PostgreSQL side — see the
-- _sqlite.sql sibling file for the full rationale).
ALTER TABLE payments ADD COLUMN IF NOT EXISTS proof_file_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_payments_proof_file_hash ON payments(proof_file_hash);
