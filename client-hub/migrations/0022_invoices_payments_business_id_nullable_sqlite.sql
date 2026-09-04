-- Purchase-flow correction, continued: general fixed-price services, Talent, and custom/generic
-- quote requests must work end-to-end through checkout/invoice/payment/proof/admin-approval
-- WITHOUT ever requiring a business -- no placeholder, no auto-create, no "attach business at
-- checkout" step. Only AI Admin still requires a real business.
--
-- projects.business_id was already made nullable in migration 0021. Tracing the full checkout ->
-- invoice -> payment -> proof -> admin-approval chain (payment_service.py, ai_payment_review.py,
-- talent_service.py, routes_admin.py's payment review routes) found FIVE tables genuinely NOT
-- NULL and genuinely written to during this flow: invoices, payments, project_files (used for
-- BOTH custom-project reference attachments AND payment proof uploads themselves -- proof upload
-- is explicitly part of the required end-to-end path), and talent_requests (Talent's own request
-- intake row, alongside its own linked project). Every function in this chain already compares
-- business_id via plain "!=" equality (None != None is False, so this already works correctly
-- once NULL is allowed) and admin's verify/reject/reupload routes already derive business_id from
-- the payment row itself rather than a URL parameter, so no logic changes were needed in
-- payment_service.py/ai_payment_review.py, only these schema constraints.
--
-- Same SQLite table-rebuild pattern as 0021 (no ALTER COLUMN support for constraints), with the
-- same PRAGMA foreign_keys OFF/ON bracketing verified necessary by directly testing 0021 against
-- a populated database first.
PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS invoices_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE,
    business_id INTEGER REFERENCES businesses(id),
    project_id INTEGER NOT NULL REFERENCES projects(id),
    quotation_id INTEGER REFERENCES quotations(id),
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ISSUED',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO invoices_new
    SELECT id, invoice_number, business_id, project_id, quotation_id, amount, status,
           created_at, updated_at
    FROM invoices;
DROP TABLE invoices;
ALTER TABLE invoices_new RENAME TO invoices;
CREATE INDEX IF NOT EXISTS idx_invoices_business ON invoices(business_id);
CREATE INDEX IF NOT EXISTS idx_invoices_project ON invoices(project_id);

CREATE TABLE IF NOT EXISTS payments_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER REFERENCES businesses(id),
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    status TEXT NOT NULL DEFAULT 'PAYMENT_PENDING',
    proof_file_id INTEGER REFERENCES project_files(id),
    ai_extracted_amount INTEGER,
    ai_extracted_date TEXT,
    ai_extracted_bank TEXT,
    ai_reference TEXT,
    ai_risk_flags_json TEXT,
    ai_match_score REAL,
    duplicate_candidate INTEGER NOT NULL DEFAULT 0,
    admin_notes TEXT,
    verified_by_user_id INTEGER REFERENCES users(id),
    verified_at TEXT,
    proof_file_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO payments_new
    SELECT id, business_id, invoice_id, status, proof_file_id, ai_extracted_amount,
           ai_extracted_date, ai_extracted_bank, ai_reference, ai_risk_flags_json, ai_match_score,
           duplicate_candidate, admin_notes, verified_by_user_id, verified_at, proof_file_hash,
           created_at, updated_at
    FROM payments;
DROP TABLE payments;
ALTER TABLE payments_new RENAME TO payments;
CREATE INDEX IF NOT EXISTS idx_payments_business ON payments(business_id);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);

CREATE TABLE IF NOT EXISTS project_files_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER REFERENCES businesses(id),
    project_id INTEGER REFERENCES projects(id),
    kind TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BLOB NOT NULL,
    uploaded_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO project_files_new
    SELECT id, business_id, project_id, kind, original_filename, mime_type, size_bytes, content,
           uploaded_by_user_id, created_at
    FROM project_files;
DROP TABLE project_files;
ALTER TABLE project_files_new RENAME TO project_files;
CREATE INDEX IF NOT EXISTS idx_project_files_project ON project_files(project_id);

CREATE TABLE IF NOT EXISTS talent_requests_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talent_id INTEGER NOT NULL REFERENCES talents(id),
    business_id INTEGER REFERENCES businesses(id),
    project_id INTEGER REFERENCES projects(id),
    campaign_type TEXT,
    platform TEXT,
    deliverables TEXT,
    num_content_pieces INTEGER,
    posting_requirements TEXT,
    target_date TEXT,
    location TEXT,
    usage_purpose TEXT,
    budget INTEGER,
    brief TEXT,
    status TEXT NOT NULL DEFAULT 'WAITING_FOR_REVIEW',
    created_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO talent_requests_new
    SELECT id, talent_id, business_id, project_id, campaign_type, platform, deliverables,
           num_content_pieces, posting_requirements, target_date, location, usage_purpose, budget,
           brief, status, created_by_user_id, created_at, updated_at
    FROM talent_requests;
DROP TABLE talent_requests;
ALTER TABLE talent_requests_new RENAME TO talent_requests;
CREATE INDEX IF NOT EXISTS idx_talent_requests_business ON talent_requests(business_id);
CREATE INDEX IF NOT EXISTS idx_talent_requests_talent ON talent_requests(talent_id);

PRAGMA foreign_keys = ON;
