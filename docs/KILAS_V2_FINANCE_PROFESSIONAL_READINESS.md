# Finance professional readiness — Phase 9 audit

Audited at feature baseline `2d6d6fe8454d3d9ff7225cf52df3fb49ffafe3d9`.
This is a code/schema capability audit, not an independent accounting certification.

Kilas Finance is an operational cash, invoice, receivables and budgeting product.
Its existing engine is preserved in Phase 9. A professional general-ledger product
must not be promised based on a dashboard redesign.

| Capability | Actual support | Boundary / gap |
| --- | --- | --- |
| Chart of accounts | Cash/bank accounts, account types, income/expense categories and subcategories | Not a formal asset/liability/equity/revenue/expense chart with posting rules |
| Double-entry general ledger | Cash transactions, invoice/payment records, paired FX operations | No general balanced debit/credit journal posting engine; FX pairs do not establish double-entry accounting |
| Journals | Transaction history and domain audit events | No general journal headers/lines, adjustment journals or accountant posting workflow |
| Reconciliation | Bank statement extraction and review, match/post/ignore decisions, retry/cancel guards | Useful row-level matching; no certified opening-to-closing bank reconciliation statement, locked reconciliation period or reviewer sign-off |
| Trial balance | Not implemented | Cannot derive a valid trial balance from cash summaries alone |
| P&L | Cash income/expense summaries and operational cash flow | Not accrual P&L; no general accruals, COGS/inventory, depreciation or adjusting entries |
| Balance sheet | Account balances and receivables views | Not a complete assets/liabilities/equity statement |
| Period close / lock | Entitlement read-only controls, void/audit and versioned mutation guards | No accounting period close/reopen permissions or immutable closed-period journal rules; entitlement expiry is not period close |
| Accountant / audit exports | Existing report PDF/CSV/ZIP, invoice/statement documents, transaction and domain audit history | Operational exports, not a complete accountant journal package or certified audit trail export |

## Evidence and existing semantics

- `client-hub/finance_service.py`: account/transaction/category operations, opening
  balance handling, FX operations and guarded workspace relocation.
- `client-hub/finance_bank_service.py` and `finance_bank_statement.py`: review and
  reconciliation states at import/row scope, separate account/statement sections.
- `client-hub/routes_finance.py`: invoice/payment lifecycle, recurring payments,
  reports and export endpoints; existing ownership/branch/entitlement checks.
- `client-hub/finance_assistant_flow.py`: already distinguishes accounting P&L
  from supported cash operations. Preserve that truthful product boundary.
- `docs/KILAS_V2_FINANCE_SELLABILITY.md` and Phase 7 status: existing baseline and
  protected owner-confirmed Bridge. Currency minor_scale is 100, including IDR;
  opening balances and FX are not operating income. Native currency reporting
  must remain distinct from estimates in a display currency.

No same-currency transfer engine was identified in the supported Finance service;
Phase 9 must call the existing operation currency exchange, without substituting
unrelated income/expense records to fabricate a transfer.

## Future work boundary

If professional accounting becomes a separately authorized product goal, first
specify the chart, balanced journal model, posting and reversal rules, migration,
period close, reconciliation controls, financial statements and accountant exports.
That requires its own data/security/accounting design and migration review.
It is not part of Phase 9 and none of these gaps are masked by new navigation.
