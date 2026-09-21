-- Finance category hierarchy: one level of subcategories. Existing category ids remain unchanged.
CREATE TABLE IF NOT EXISTS finance_category_hierarchy (
 business_id BIGINT NOT NULL REFERENCES businesses(id),
 child_category_id BIGINT NOT NULL,
 parent_category_id BIGINT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(business_id,child_category_id),
 FOREIGN KEY(business_id,child_category_id) REFERENCES finance_categories(business_id,id),
 FOREIGN KEY(business_id,parent_category_id) REFERENCES finance_categories(business_id,id),
 CHECK(child_category_id<>parent_category_id)
);
CREATE INDEX IF NOT EXISTS idx_finance_category_hierarchy_parent
 ON finance_category_hierarchy(business_id,parent_category_id);

WITH utility_parents AS (
 SELECT business_id,id AS parent_id
 FROM finance_categories
 WHERE direction='EXPENSE' AND name='Utilitas'
),
defaults(name) AS (
 VALUES ('Listrik'),('Air'),('Internet'),('Telepon'),('Gas'),('Laundry'),('Sampah / Kebersihan')
)
INSERT INTO finance_categories
 (business_id,direction,name,is_active,created_at,updated_at)
SELECT p.business_id,'EXPENSE',d.name,TRUE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM utility_parents p CROSS JOIN defaults d
ON CONFLICT DO NOTHING;

UPDATE finance_categories
SET is_active=TRUE,updated_at=CURRENT_TIMESTAMP
WHERE direction='EXPENSE'
 AND name IN ('Listrik','Air','Internet','Telepon','Gas','Laundry','Sampah / Kebersihan')
 AND business_id IN (
   SELECT business_id FROM finance_categories
   WHERE direction='EXPENSE' AND name='Utilitas'
 );

INSERT INTO finance_category_hierarchy
 (business_id,child_category_id,parent_category_id,created_at)
SELECT p.business_id,c.id,p.parent_id,CURRENT_TIMESTAMP
FROM utility_parents p
JOIN finance_categories c ON c.business_id=p.business_id
 AND c.direction='EXPENSE'
 AND c.name IN ('Listrik','Air','Internet','Telepon','Gas','Laundry','Sampah / Kebersihan')
ON CONFLICT(business_id,child_category_id)
DO UPDATE SET parent_category_id=EXCLUDED.parent_category_id;
