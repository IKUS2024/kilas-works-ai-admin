-- Purchase-flow correction, continued (PostgreSQL side — see the _sqlite.sql sibling for the full
-- rationale). Postgres supports ALTER COLUMN directly, no table rebuild needed.
ALTER TABLE invoices ALTER COLUMN business_id DROP NOT NULL;
ALTER TABLE payments ALTER COLUMN business_id DROP NOT NULL;
ALTER TABLE project_files ALTER COLUMN business_id DROP NOT NULL;
ALTER TABLE talent_requests ALTER COLUMN business_id DROP NOT NULL;
