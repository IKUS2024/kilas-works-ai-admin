-- Purchase-flow correction (PostgreSQL side — see the _sqlite.sql sibling for full rationale).
-- Postgres supports ALTER COLUMN directly, no table rebuild needed.
ALTER TABLE projects ALTER COLUMN business_id DROP NOT NULL;
