-- Normalize Finance monetary storage to two decimal places for every supported currency.
-- Historical IDR/JPY rows used whole units. This migration scales those rows exactly once.
CREATE TABLE IF NOT EXISTS finance_money_scale_state (
  key TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM finance_money_scale_state WHERE key='all_currency_2dp_v1'
  ) THEN
    UPDATE finance_accounts
      SET opening_balance_minor = opening_balance_minor * 100
      WHERE currency IN ('IDR','JPY');

    UPDATE finance_transactions
      SET amount_minor = amount_minor * 100
      WHERE currency IN ('IDR','JPY');

    UPDATE finance_recurring_expenses
      SET amount_minor = amount_minor * 100
      WHERE currency IN ('IDR','JPY');

    UPDATE finance_budgets
      SET amount_minor = amount_minor * 100
      WHERE currency IN ('IDR','JPY');

    UPDATE finance_subscription_bills
      SET amount_minor = amount_minor * 100
      WHERE currency IN ('IDR','JPY');

    UPDATE finance_fx_exchanges
      SET from_amount_minor = from_amount_minor * 100
      WHERE from_currency IN ('IDR','JPY');

    UPDATE finance_fx_exchanges
      SET to_amount_minor = to_amount_minor * 100
      WHERE to_currency IN ('IDR','JPY');

    UPDATE finance_invoice_items ii
      SET unit_price_minor = ii.unit_price_minor * 100
      FROM finance_invoices i
      WHERE i.business_id=ii.business_id
        AND i.id=ii.invoice_id
        AND i.currency IN ('IDR','JPY');

    UPDATE finance_invoice_payments p
      SET amount_minor = p.amount_minor * 100
      FROM finance_invoices i
      WHERE i.business_id=p.business_id
        AND i.id=p.invoice_id
        AND i.currency IN ('IDR','JPY');

    UPDATE finance_bank_rows r
      SET amount_minor = r.amount_minor * 100
      FROM finance_bank_imports bi, finance_accounts a
      WHERE bi.business_id=r.business_id
        AND bi.id=r.import_id
        AND a.business_id=bi.business_id
        AND a.id=bi.account_id
        AND a.currency IN ('IDR','JPY');

    INSERT INTO finance_money_scale_state(key,applied_at)
    VALUES ('all_currency_2dp_v1',CURRENT_TIMESTAMP);
  END IF;
END $$;
