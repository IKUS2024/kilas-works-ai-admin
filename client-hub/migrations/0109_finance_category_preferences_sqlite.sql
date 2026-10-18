-- Additive scoped presentation/version metadata; no ledger/history backfill.
CREATE TABLE IF NOT EXISTS finance_category_preferences (
 business_id INTEGER NOT NULL REFERENCES businesses(id),scope_key TEXT NOT NULL,
 category_id INTEGER NOT NULL REFERENCES finance_categories(id),icon_key TEXT,sort_order INTEGER,
 PRIMARY KEY(business_id,scope_key,category_id));
CREATE TABLE IF NOT EXISTS finance_category_catalog_versions (
 business_id INTEGER NOT NULL REFERENCES businesses(id),scope_key TEXT NOT NULL,version INTEGER NOT NULL,
 changes_json TEXT NOT NULL,PRIMARY KEY(business_id,scope_key,version));
