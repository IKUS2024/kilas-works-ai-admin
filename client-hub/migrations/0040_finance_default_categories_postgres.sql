-- Refresh the default EXPENSE category set without rewriting historical transactions.
-- Existing custom categories remain untouched. Legacy defaults stay active only when an active
-- recurring rule still depends on them; otherwise they are hidden from new-entry pickers.
WITH finance_businesses AS (
  SELECT DISTINCT business_id FROM finance_categories
),
defaults(name) AS (
  VALUES
    ('Biaya Sewa'),
    ('Utilitas'),
    ('Makanan & Belanja Harian'),
    ('Perlengkapan'),
    ('Transportasi'),
    ('Asuransi'),
    ('Biaya Tak Terduga')
)
INSERT INTO finance_categories
  (business_id,direction,name,is_active,created_at,updated_at)
SELECT b.business_id,'EXPENSE',d.name,TRUE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM finance_businesses b CROSS JOIN defaults d
ON CONFLICT DO NOTHING;

UPDATE finance_categories
SET is_active=TRUE, updated_at=CURRENT_TIMESTAMP
WHERE direction='EXPENSE'
  AND name IN (
    'Biaya Sewa','Utilitas','Makanan & Belanja Harian','Perlengkapan',
    'Transportasi','Asuransi','Biaya Tak Terduga'
  );

UPDATE finance_categories
SET is_active=FALSE, updated_at=CURRENT_TIMESTAMP
WHERE direction='EXPENSE'
  AND name IN (
    'Produksi / Vendor','Gaji / Freelancer','Marketing / Ads','Transport',
    'Software / API','Operasional','Pengeluaran Lain'
  )
  AND is_active=TRUE
  AND NOT EXISTS (
    SELECT 1 FROM finance_recurring_expenses r
    WHERE r.business_id=finance_categories.business_id
      AND r.category_id=finance_categories.id
      AND r.is_active=TRUE
  );
