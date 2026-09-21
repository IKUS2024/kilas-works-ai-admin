-- Normalize Finance monetary storage to two decimal places for every supported currency.
-- Historical IDR/JPY rows used whole units. This migration scales those rows exactly once.
CREATE TABLE IF NOT EXISTS finance_money_scale_state (
  key TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

BEGIN IMMEDIATE;

UPDATE finance_accounts
SET opening_balance_minor = opening_balance_minor * 100
WHERE currency IN ('IDR','JPY')
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_transactions
SET amount_minor = amount_minor * 100
WHERE currency IN ('IDR','JPY')
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_recurring_expenses
SET amount_minor = amount_minor * 100
WHERE currency IN ('IDR','JPY')
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_budgets
SET amount_minor = amount_minor * 100
WHERE currency IN ('IDR','JPY')
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_subscription_bills
SET amount_minor = amount_minor * 100
WHERE currency IN ('IDR','JPY')
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_fx_exchanges
SET from_amount_minor = from_amount_minor * 100
WHERE from_currency IN ('IDR','JPY')
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_fx_exchanges
SET to_amount_minor = to_amount_minor * 100
WHERE to_currency IN ('IDR','JPY')
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_invoice_items
SET unit_price_minor = unit_price_minor * 100
WHERE EXISTS (
    SELECT 1 FROM finance_invoices i
    WHERE i.business_id=finance_invoice_items.business_id
      AND i.id=finance_invoice_items.invoice_id
      AND i.currency IN ('IDR','JPY')
  )
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_invoice_payments
SET amount_minor = amount_minor * 100
WHERE EXISTS (
    SELECT 1 FROM finance_invoices i
    WHERE i.business_id=finance_invoice_payments.business_id
      AND i.id=finance_invoice_payments.invoice_id
      AND i.currency IN ('IDR','JPY')
  )
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

UPDATE finance_bank_rows
SET amount_minor = amount_minor * 100
WHERE EXISTS (
    SELECT 1
    FROM finance_bank_imports bi
    JOIN finance_accounts a
      ON a.business_id=bi.business_id AND a.id=bi.account_id
    WHERE bi.business_id=finance_bank_rows.business_id
      AND bi.id=finance_bank_rows.import_id
      AND a.currency IN ('IDR','JPY')
  )
  AND NOT EXISTS (SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1');

INSERT OR IGNORE INTO finance_money_scale_state(key,applied_at)
VALUES ('all_currency_2dp_v1',CURRENT_TIMESTAMP);

COMMIT;
