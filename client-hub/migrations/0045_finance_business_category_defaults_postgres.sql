-- Rich default Business category hierarchy.
-- Existing history stays intact. New defaults are added to the BUSINESS workspace only.
-- User-deleted/renamed workspace mappings are not reactivated by this migration.

WITH business_ids(business_id) AS (
  SELECT DISTINCT business_id FROM finance_branch_workspaces WHERE workspace_type='BUSINESS'
),
defaults(direction,name) AS (
  VALUES
  ('INCOME','Penjualan / Jasa'),
  ('INCOME','Pendapatan Lain'),
  ('EXPENSE','Produksi / HPP'),
  ('EXPENSE','Gaji & Tenaga Kerja'),
  ('EXPENSE','Biaya Sewa'),
  ('EXPENSE','Utilitas'),
  ('EXPENSE','Marketing & Promosi'),
  ('EXPENSE','Software & Langganan'),
  ('EXPENSE','Perlengkapan'),
  ('EXPENSE','Transportasi & Pengiriman'),
  ('EXPENSE','Perawatan & Perbaikan'),
  ('EXPENSE','Administrasi & Profesional'),
  ('EXPENSE','Bank & Pembayaran'),
  ('EXPENSE','Pajak & Asuransi'),
  ('EXPENSE','Makan & Operasional Tim'),
  ('EXPENSE','Biaya Tak Terduga'),
  ('INCOME','Penjualan Produk'),
  ('INCOME','Jasa / Proyek'),
  ('INCOME','Retainer / Langganan'),
  ('INCOME','Penjualan Online / Marketplace'),
  ('INCOME','Komisi / Affiliate'),
  ('INCOME','Cashback / Bunga'),
  ('INCOME','Refund / Penggantian Biaya'),
  ('INCOME','Lainnya'),
  ('EXPENSE','Bahan Baku'),
  ('EXPENSE','Stok / Persediaan'),
  ('EXPENSE','Packaging'),
  ('EXPENSE','Vendor / Outsourcing'),
  ('EXPENSE','Ongkos Produksi'),
  ('EXPENSE','Gaji'),
  ('EXPENSE','Freelancer'),
  ('EXPENSE','Komisi'),
  ('EXPENSE','Bonus / Insentif'),
  ('EXPENSE','Sewa Toko / Kantor'),
  ('EXPENSE','Sewa Gudang'),
  ('EXPENSE','Sewa Peralatan'),
  ('EXPENSE','Listrik'),
  ('EXPENSE','Air'),
  ('EXPENSE','Internet'),
  ('EXPENSE','Telepon'),
  ('EXPENSE','Gas'),
  ('EXPENSE','Laundry'),
  ('EXPENSE','Sampah / Kebersihan'),
  ('EXPENSE','Meta Ads'),
  ('EXPENSE','Google Ads'),
  ('EXPENSE','TikTok Ads'),
  ('EXPENSE','Influencer / KOL'),
  ('EXPENSE','Produksi Konten'),
  ('EXPENSE','Promo / Diskon'),
  ('EXPENSE','Software'),
  ('EXPENSE','AI / API'),
  ('EXPENSE','Hosting / Domain'),
  ('EXPENSE','SaaS / Subscription'),
  ('EXPENSE','Alat Kantor'),
  ('EXPENSE','Peralatan Operasional'),
  ('EXPENSE','Perlengkapan Kebersihan'),
  ('EXPENSE','Peralatan Kecil'),
  ('EXPENSE','BBM'),
  ('EXPENSE','Tol / Parkir'),
  ('EXPENSE','Kurir / Delivery'),
  ('EXPENSE','Transport Online'),
  ('EXPENSE','Servis Kendaraan Operasional'),
  ('EXPENSE','Servis Peralatan'),
  ('EXPENSE','Renovasi Kecil'),
  ('EXPENSE','Maintenance'),
  ('EXPENSE','Akuntan'),
  ('EXPENSE','Legal / Notaris'),
  ('EXPENSE','Perizinan'),
  ('EXPENSE','Biaya Administrasi'),
  ('EXPENSE','Biaya Transfer'),
  ('EXPENSE','MDR / Payment Gateway'),
  ('EXPENSE','Biaya Bank'),
  ('EXPENSE','Selisih Kurs'),
  ('EXPENSE','Pajak'),
  ('EXPENSE','Asuransi Bisnis'),
  ('EXPENSE','BPJS / Ketenagakerjaan'),
  ('EXPENSE','Konsumsi Karyawan'),
  ('EXPENSE','Meeting / Client'),
  ('EXPENSE','Perjalanan Dinas'),
  ('EXPENSE','Kerusakan'),
  ('EXPENSE','Kehilangan'),
  ('EXPENSE','Denda Operasional'),
  ('EXPENSE','Lainnya')
)
INSERT INTO finance_categories
 (business_id,direction,name,is_active,created_at,updated_at)
SELECT b.business_id,d.direction,d.name,TRUE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM business_ids b CROSS JOIN defaults d
ON CONFLICT(business_id,direction,name) DO NOTHING;

UPDATE finance_categories
SET is_active=TRUE,updated_at=CURRENT_TIMESTAMP
WHERE business_id IN (
  SELECT DISTINCT business_id FROM finance_branch_workspaces WHERE workspace_type='BUSINESS'
)
AND (
  (direction='INCOME' AND name IN ('Penjualan / Jasa','Pendapatan Lain','Penjualan Produk','Jasa / Proyek','Retainer / Langganan','Penjualan Online / Marketplace','Komisi / Affiliate','Cashback / Bunga','Refund / Penggantian Biaya','Lainnya'))
  OR
  (direction='EXPENSE' AND name IN ('Produksi / HPP','Gaji & Tenaga Kerja','Biaya Sewa','Utilitas','Marketing & Promosi','Software & Langganan','Perlengkapan','Transportasi & Pengiriman','Perawatan & Perbaikan','Administrasi & Profesional','Bank & Pembayaran','Pajak & Asuransi','Makan & Operasional Tim','Biaya Tak Terduga','Bahan Baku','Stok / Persediaan','Packaging','Vendor / Outsourcing','Ongkos Produksi','Gaji','Freelancer','Komisi','Bonus / Insentif','Sewa Toko / Kantor','Sewa Gudang','Sewa Peralatan','Listrik','Air','Internet','Telepon','Gas','Laundry','Sampah / Kebersihan','Meta Ads','Google Ads','TikTok Ads','Influencer / KOL','Produksi Konten','Promo / Diskon','Software','AI / API','Hosting / Domain','SaaS / Subscription','Alat Kantor','Peralatan Operasional','Perlengkapan Kebersihan','Peralatan Kecil','BBM','Tol / Parkir','Kurir / Delivery','Transport Online','Servis Kendaraan Operasional','Servis Peralatan','Renovasi Kecil','Maintenance','Akuntan','Legal / Notaris','Perizinan','Biaya Administrasi','Biaya Transfer','MDR / Payment Gateway','Biaya Bank','Selisih Kurs','Pajak','Asuransi Bisnis','BPJS / Ketenagakerjaan','Konsumsi Karyawan','Meeting / Client','Perjalanan Dinas','Kerusakan','Kehilangan','Denda Operasional','Lainnya'))
);

WITH business_ids(business_id) AS (
  SELECT DISTINCT business_id FROM finance_branch_workspaces WHERE workspace_type='BUSINESS'
),
defaults(direction,name) AS (
  VALUES
  ('INCOME','Penjualan / Jasa'),
  ('INCOME','Pendapatan Lain'),
  ('EXPENSE','Produksi / HPP'),
  ('EXPENSE','Gaji & Tenaga Kerja'),
  ('EXPENSE','Biaya Sewa'),
  ('EXPENSE','Utilitas'),
  ('EXPENSE','Marketing & Promosi'),
  ('EXPENSE','Software & Langganan'),
  ('EXPENSE','Perlengkapan'),
  ('EXPENSE','Transportasi & Pengiriman'),
  ('EXPENSE','Perawatan & Perbaikan'),
  ('EXPENSE','Administrasi & Profesional'),
  ('EXPENSE','Bank & Pembayaran'),
  ('EXPENSE','Pajak & Asuransi'),
  ('EXPENSE','Makan & Operasional Tim'),
  ('EXPENSE','Biaya Tak Terduga'),
  ('INCOME','Penjualan Produk'),
  ('INCOME','Jasa / Proyek'),
  ('INCOME','Retainer / Langganan'),
  ('INCOME','Penjualan Online / Marketplace'),
  ('INCOME','Komisi / Affiliate'),
  ('INCOME','Cashback / Bunga'),
  ('INCOME','Refund / Penggantian Biaya'),
  ('INCOME','Lainnya'),
  ('EXPENSE','Bahan Baku'),
  ('EXPENSE','Stok / Persediaan'),
  ('EXPENSE','Packaging'),
  ('EXPENSE','Vendor / Outsourcing'),
  ('EXPENSE','Ongkos Produksi'),
  ('EXPENSE','Gaji'),
  ('EXPENSE','Freelancer'),
  ('EXPENSE','Komisi'),
  ('EXPENSE','Bonus / Insentif'),
  ('EXPENSE','Sewa Toko / Kantor'),
  ('EXPENSE','Sewa Gudang'),
  ('EXPENSE','Sewa Peralatan'),
  ('EXPENSE','Listrik'),
  ('EXPENSE','Air'),
  ('EXPENSE','Internet'),
  ('EXPENSE','Telepon'),
  ('EXPENSE','Gas'),
  ('EXPENSE','Laundry'),
  ('EXPENSE','Sampah / Kebersihan'),
  ('EXPENSE','Meta Ads'),
  ('EXPENSE','Google Ads'),
  ('EXPENSE','TikTok Ads'),
  ('EXPENSE','Influencer / KOL'),
  ('EXPENSE','Produksi Konten'),
  ('EXPENSE','Promo / Diskon'),
  ('EXPENSE','Software'),
  ('EXPENSE','AI / API'),
  ('EXPENSE','Hosting / Domain'),
  ('EXPENSE','SaaS / Subscription'),
  ('EXPENSE','Alat Kantor'),
  ('EXPENSE','Peralatan Operasional'),
  ('EXPENSE','Perlengkapan Kebersihan'),
  ('EXPENSE','Peralatan Kecil'),
  ('EXPENSE','BBM'),
  ('EXPENSE','Tol / Parkir'),
  ('EXPENSE','Kurir / Delivery'),
  ('EXPENSE','Transport Online'),
  ('EXPENSE','Servis Kendaraan Operasional'),
  ('EXPENSE','Servis Peralatan'),
  ('EXPENSE','Renovasi Kecil'),
  ('EXPENSE','Maintenance'),
  ('EXPENSE','Akuntan'),
  ('EXPENSE','Legal / Notaris'),
  ('EXPENSE','Perizinan'),
  ('EXPENSE','Biaya Administrasi'),
  ('EXPENSE','Biaya Transfer'),
  ('EXPENSE','MDR / Payment Gateway'),
  ('EXPENSE','Biaya Bank'),
  ('EXPENSE','Selisih Kurs'),
  ('EXPENSE','Pajak'),
  ('EXPENSE','Asuransi Bisnis'),
  ('EXPENSE','BPJS / Ketenagakerjaan'),
  ('EXPENSE','Konsumsi Karyawan'),
  ('EXPENSE','Meeting / Client'),
  ('EXPENSE','Perjalanan Dinas'),
  ('EXPENSE','Kerusakan'),
  ('EXPENSE','Kehilangan'),
  ('EXPENSE','Denda Operasional'),
  ('EXPENSE','Lainnya')
)
INSERT INTO finance_category_workspace_settings
 (business_id,category_id,scope_key,workspace_type,owner_user_id,display_name,is_active,created_at,updated_at)
SELECT c.business_id,c.id,'BUSINESS','BUSINESS',NULL,c.name,TRUE,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
FROM business_ids b
JOIN finance_categories c ON c.business_id=b.business_id
JOIN defaults d ON d.direction=c.direction AND d.name=c.name
ON CONFLICT(business_id,category_id,scope_key) DO NOTHING;

WITH links(direction,parent_name,child_name) AS (
  VALUES
  ('INCOME','Penjualan / Jasa','Penjualan Produk'),
  ('INCOME','Penjualan / Jasa','Jasa / Proyek'),
  ('INCOME','Penjualan / Jasa','Retainer / Langganan'),
  ('INCOME','Penjualan / Jasa','Penjualan Online / Marketplace'),
  ('INCOME','Pendapatan Lain','Komisi / Affiliate'),
  ('INCOME','Pendapatan Lain','Cashback / Bunga'),
  ('INCOME','Pendapatan Lain','Refund / Penggantian Biaya'),
  ('INCOME','Pendapatan Lain','Lainnya'),
  ('EXPENSE','Produksi / HPP','Bahan Baku'),
  ('EXPENSE','Produksi / HPP','Stok / Persediaan'),
  ('EXPENSE','Produksi / HPP','Packaging'),
  ('EXPENSE','Produksi / HPP','Vendor / Outsourcing'),
  ('EXPENSE','Produksi / HPP','Ongkos Produksi'),
  ('EXPENSE','Gaji & Tenaga Kerja','Gaji'),
  ('EXPENSE','Gaji & Tenaga Kerja','Freelancer'),
  ('EXPENSE','Gaji & Tenaga Kerja','Komisi'),
  ('EXPENSE','Gaji & Tenaga Kerja','Bonus / Insentif'),
  ('EXPENSE','Biaya Sewa','Sewa Toko / Kantor'),
  ('EXPENSE','Biaya Sewa','Sewa Gudang'),
  ('EXPENSE','Biaya Sewa','Sewa Peralatan'),
  ('EXPENSE','Utilitas','Listrik'),
  ('EXPENSE','Utilitas','Air'),
  ('EXPENSE','Utilitas','Internet'),
  ('EXPENSE','Utilitas','Telepon'),
  ('EXPENSE','Utilitas','Gas'),
  ('EXPENSE','Utilitas','Laundry'),
  ('EXPENSE','Utilitas','Sampah / Kebersihan'),
  ('EXPENSE','Marketing & Promosi','Meta Ads'),
  ('EXPENSE','Marketing & Promosi','Google Ads'),
  ('EXPENSE','Marketing & Promosi','TikTok Ads'),
  ('EXPENSE','Marketing & Promosi','Influencer / KOL'),
  ('EXPENSE','Marketing & Promosi','Produksi Konten'),
  ('EXPENSE','Marketing & Promosi','Promo / Diskon'),
  ('EXPENSE','Software & Langganan','Software'),
  ('EXPENSE','Software & Langganan','AI / API'),
  ('EXPENSE','Software & Langganan','Hosting / Domain'),
  ('EXPENSE','Software & Langganan','SaaS / Subscription'),
  ('EXPENSE','Perlengkapan','Alat Kantor'),
  ('EXPENSE','Perlengkapan','Peralatan Operasional'),
  ('EXPENSE','Perlengkapan','Perlengkapan Kebersihan'),
  ('EXPENSE','Perlengkapan','Peralatan Kecil'),
  ('EXPENSE','Transportasi & Pengiriman','BBM'),
  ('EXPENSE','Transportasi & Pengiriman','Tol / Parkir'),
  ('EXPENSE','Transportasi & Pengiriman','Kurir / Delivery'),
  ('EXPENSE','Transportasi & Pengiriman','Transport Online'),
  ('EXPENSE','Transportasi & Pengiriman','Servis Kendaraan Operasional'),
  ('EXPENSE','Perawatan & Perbaikan','Servis Peralatan'),
  ('EXPENSE','Perawatan & Perbaikan','Renovasi Kecil'),
  ('EXPENSE','Perawatan & Perbaikan','Maintenance'),
  ('EXPENSE','Administrasi & Profesional','Akuntan'),
  ('EXPENSE','Administrasi & Profesional','Legal / Notaris'),
  ('EXPENSE','Administrasi & Profesional','Perizinan'),
  ('EXPENSE','Administrasi & Profesional','Biaya Administrasi'),
  ('EXPENSE','Bank & Pembayaran','Biaya Transfer'),
  ('EXPENSE','Bank & Pembayaran','MDR / Payment Gateway'),
  ('EXPENSE','Bank & Pembayaran','Biaya Bank'),
  ('EXPENSE','Bank & Pembayaran','Selisih Kurs'),
  ('EXPENSE','Pajak & Asuransi','Pajak'),
  ('EXPENSE','Pajak & Asuransi','Asuransi Bisnis'),
  ('EXPENSE','Pajak & Asuransi','BPJS / Ketenagakerjaan'),
  ('EXPENSE','Makan & Operasional Tim','Konsumsi Karyawan'),
  ('EXPENSE','Makan & Operasional Tim','Meeting / Client'),
  ('EXPENSE','Makan & Operasional Tim','Perjalanan Dinas'),
  ('EXPENSE','Biaya Tak Terduga','Kerusakan'),
  ('EXPENSE','Biaya Tak Terduga','Kehilangan'),
  ('EXPENSE','Biaya Tak Terduga','Denda Operasional'),
  ('EXPENSE','Biaya Tak Terduga','Lainnya')
)
INSERT INTO finance_category_hierarchy
 (business_id,child_category_id,parent_category_id,created_at)
SELECT child.business_id,child.id,parent.id,CURRENT_TIMESTAMP
FROM links l
JOIN finance_categories parent
 ON parent.direction=l.direction AND parent.name=l.parent_name
JOIN finance_categories child
 ON child.business_id=parent.business_id
 AND child.direction=l.direction AND child.name=l.child_name
JOIN finance_branch_workspaces w
 ON w.business_id=parent.business_id AND w.workspace_type='BUSINESS'
ON CONFLICT(business_id,child_category_id)
DO UPDATE SET parent_category_id=EXCLUDED.parent_category_id;

-- Superseded legacy defaults disappear only when they have never been used in Business.
UPDATE finance_category_workspace_settings s
SET is_active=FALSE,updated_at=CURRENT_TIMESTAMP
WHERE s.scope_key='BUSINESS'
  AND s.display_name IN ('Subscription','Makanan & Belanja Harian','Transportasi','Asuransi')
  AND NOT EXISTS (
    SELECT 1 FROM finance_transactions t
    JOIN finance_branch_workspaces w
      ON w.business_id=t.business_id AND w.branch_id=t.branch_id
     AND w.workspace_type='BUSINESS'
    WHERE t.business_id=s.business_id AND t.category_id=s.category_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM finance_budgets b
    JOIN finance_branch_workspaces w
      ON w.business_id=b.business_id AND w.branch_id=b.branch_id
     AND w.workspace_type='BUSINESS'
    WHERE b.business_id=s.business_id AND b.category_id=s.category_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM finance_recurring_expenses r
    JOIN finance_branch_workspaces w
      ON w.business_id=r.business_id AND w.branch_id=r.branch_id
     AND w.workspace_type='BUSINESS'
    WHERE r.business_id=s.business_id AND r.category_id=s.category_id
  );
