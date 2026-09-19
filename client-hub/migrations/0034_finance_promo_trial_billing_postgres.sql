-- Reprice only unpaid/retryable legacy Finance subscription bills for the launch promo.
-- REVIEW and VERIFIED bills are preserved so submitted/paid payment history is never rewritten.
UPDATE finance_subscription_bills
SET amount_minor = 99000,
    updated_at = CURRENT_TIMESTAMP
WHERE product_key = 'finance'
  AND currency = 'IDR'
  AND amount_minor = 149000
  AND status IN ('PENDING', 'REJECTED');
