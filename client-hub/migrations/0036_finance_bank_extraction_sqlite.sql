-- Normalized extraction review only. Never stores source bytes or statement headers.
CREATE TABLE IF NOT EXISTS finance_bank_extraction_reviews (
 business_id INTEGER NOT NULL,
 import_id INTEGER NOT NULL,
 row_index INTEGER NOT NULL CHECK(row_index BETWEEN 0 AND 1000),
 metadata TEXT NOT NULL,
 PRIMARY KEY(business_id,import_id,row_index),
 FOREIGN KEY(business_id,import_id) REFERENCES finance_bank_imports(business_id,id)
);
