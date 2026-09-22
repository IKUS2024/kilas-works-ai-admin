# Finance UI unification — 2026-09-22

Baseline: `ddf255872664c6a08b2abdb32e25ae04e0d062c5`.

The shared Finance shell, scoped CSS, and delegated UI controls cover Dashboard,
transactions/income/expenses, accounts/details, recurring bills, budgets, invoices
and their editor/payment views, payees, reports, receipt review and Assistant.
Existing routes, forms, CSRF, access checks, workspace and branch rules remain in use.
Public invoice documents, authentication and other Client Hub products do not load
this shell. No new runtime dependencies or database schema changes.

## Financial sources of truth

| Value | Existing source |
| --- | --- |
| Income, expense, cash flow, reports | POSTED `finance_transactions`, via scoped Finance services |
| Current account balance | `get_account_balance_report`: opening balance + posted income − posted expense + exchange in − exchange out |
| FX display | `finance_fx` Decimal conversion and native money formatting; no ledger conversions |
| Bills and payments | Recurring schedules and postings linked to their original ledger transaction |
| Budgets | Existing monthly category budgets and expense-category totals, including child categories |
| Invoice receivables/status/payments | Existing invoice totals and `record_invoice_payment`; issuance creates no cash income |
| Payees/customers | Existing scoped payee/customer records and relationships |

Read-side changes: one literal, parameterized transaction search shared by list and
count; reporting links honor the selected month unless an explicit reporting range
is supplied; paid bill history displays the linked transaction's amount/currency
instead of a subsequently edited recurring rule. Financial write services unchanged.
SQLite migration execution now strips full-line SQL comments before splitting the
existing invoice migration; its SQL, historical records and Postgres path are unchanged.

## Validation

- 63 focused Python tests pass: Dashboard design (10), invoice editor (18),
  receivables/payments (25), new UI/accounting integration (10).
- Three new JavaScript UI tests pass. Offline DOM checks on real Flask-rendered HTML
  verify green/red bars, minor-unit scaling, live month changes, context synchronization,
  and transaction/branch dialog actions after replacement.
- Integration checks render 17 Finance views and exercise income, expense, opening
  balances, edit/void, category budgets, FX transfer, invoice partial/full payment and
  idempotent retries, recurring payment/history, literal search/pagination, branches,
  reporting periods, and migration replay. Existing dashboard tests cover Personal,
  business switching, currency unavailability and current all-branch fallback rules.
- Python compilation, JavaScript syntax and `git diff --check` pass.
- Broader comparison: 280 Python cases, 43 failures and 18 errors, all already failing
  on baseline (baseline: 270 cases, 44 failures and 18 errors). One pre-existing
  transaction-filter failure is resolved. Legacy JavaScript suite retains the same
  12 baseline failures out of 20 cases. Existing tests were not rewritten.

## Verification still requiring access

The production browser is reachable, but its signed-in account has no Finance
business. No production test records were created. Local browser access is blocked
by the browser service. Render requires explicit workspace confirmation before
service/deploy/log access. Consequently, authenticated visual QA of the new Finance
screens and LIVE/log verification remain outstanding; DOM checks are not visual QA.
