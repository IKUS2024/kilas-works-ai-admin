-- Payment verification hardening — file-hash duplicate-proof detection (Section 6 of the request).
--
-- WHY: the existing duplicate check (ai_payment_review._is_duplicate_reference) only compares the
-- AI-extracted transaction reference string — which is None until real vision extraction is wired
-- up (see ai_payment_review.py's own module docstring), meaning duplicate detection was
-- effectively dormant. A SHA-256 hash of the uploaded proof FILE's raw bytes needs no AI
-- extraction at all and works today: the exact same screenshot/PDF reused for a second invoice
-- produces an identical hash, catching the most common real-world duplicate-proof pattern
-- (re-submitting the same file) immediately, while the reference-based check remains as an
-- additional signal for once real extraction exists. Additive, nullable — existing rows simply
-- have no hash recorded (never treated as a duplicate of anything by omission).
ALTER TABLE payments ADD COLUMN proof_file_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_payments_proof_file_hash ON payments(proof_file_hash);
