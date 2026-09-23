-- Customer-facing Finance lane visibility.
-- SQLite repeat runs tolerate duplicate-column errors in db.init_schema().
ALTER TABLE finance_entitlements
ADD COLUMN customer_hidden INTEGER NOT NULL DEFAULT 0;
