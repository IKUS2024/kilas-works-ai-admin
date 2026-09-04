-- Purchase-flow correction: general fixed-price services, Talent, and custom/generic quote
-- requests must NOT require a business at all -- no placeholder business may ever be created as
-- a side effect of selecting one of these. Only AI Admin still requires a real business (its own
-- separate onboarding wizard, untouched by this).
--
-- This requires projects.business_id to become NULLABLE. SQLite has no ALTER COLUMN support for
-- constraints, so the standard, safe pattern is used: create the table with the corrected
-- constraint under a new name, copy every existing row across unchanged, drop the old table,
-- rename the new one into place. Every existing row already has a non-NULL business_id, so this
-- copies losslessly -- no data is at risk, and no other column/index/behavior changes.
--
-- IMPORTANT: foreign keys are enforced in this codebase (db.py sets PRAGMA foreign_keys = ON).
-- project_files/invoices/quotations/etc. all reference projects(id) -- on a database that
-- already has real rows in those child tables (i.e. any real production database, as opposed to
-- a fresh empty one), dropping the referenced parent table fails with a FOREIGN KEY constraint
-- error unless enforcement is temporarily suspended for the duration of this rebuild (confirmed
-- by directly testing this migration against a populated database before finalizing it -- the
-- unguarded version failed exactly this way). This is SQLite's own documented pattern for this
-- exact situation: every child row's project_id keeps pointing at the SAME id values, which are
-- preserved unchanged by the INSERT...SELECT below, so referential integrity is never actually
-- violated -- only the enforcement CHECK during the brief structural rebuild is suspended.
PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS projects_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER REFERENCES businesses(id),
    project_type TEXT NOT NULL,
    catalog_key TEXT,
    pricing_mode TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    requirements_json TEXT,
    budget_min INTEGER,
    budget_max INTEGER,
    final_price INTEGER,
    created_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO projects_new
    SELECT id, business_id, project_type, catalog_key, pricing_mode, title, status,
           requirements_json, budget_min, budget_max, final_price, created_by_user_id,
           created_at, updated_at
    FROM projects;

DROP TABLE projects;
ALTER TABLE projects_new RENAME TO projects;

-- Recreate the indexes that existed on the original table (dropped along with it above) plus one
-- new index supporting the owner-based access path for business-less projects.
CREATE INDEX IF NOT EXISTS idx_projects_business ON projects(business_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_created_by_user_id ON projects(created_by_user_id);

PRAGMA foreign_keys = ON;
