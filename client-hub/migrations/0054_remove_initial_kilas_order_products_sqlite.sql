-- Remove the original demo/seed Kilas Order products while keeping the catalog schema intact.
-- Safe to re-run.
DELETE FROM kilas_order_catalog
WHERE product_code IN (
  'KIL-P-1001','KIL-P-1002','KIL-P-1003','KIL-P-1004','KIL-P-1005',
  'KIL-P-1006','KIL-P-1007','KIL-P-1008','KIL-P-1009','KIL-P-1010'
);
