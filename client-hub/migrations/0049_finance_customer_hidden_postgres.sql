-- Customer-facing Finance lane visibility.
-- Soft-hide a Finance business from Finance lists without deleting ledger data or affecting Kilas Assist.
ALTER TABLE finance_entitlements
ADD COLUMN IF NOT EXISTS customer_hidden BOOLEAN NOT NULL DEFAULT FALSE;
