# Phase 7 Standalone Finance sellability audit

Finance remains an independent operational cash-finance product. Connected mode uses
exactly its existing customer/invoice/cash engine. No Core or Bridge row is required
for Finance access, setup, services, reports or assistant. No broad redesign or new
accounting meaning is introduced. Exact final certification is in Phase 7 status.

| Supported area | Existing coverage / evidence |
| --- | --- |
| Finance-only setup, business selection, entitlement/trial/read-only | `test_finance_phase1a`, `phase1b`, `multibusiness`, `test_kilas_finance_baseline`, new Bridge routes standalone case (package NONE; zero Bridge rows) |
| Business/Personal workspaces, branches, accounts, opening balances | `home_dashboard`, `branches`, `branch_delete_recovery`, `workspace_corrections`; both original positive move cases preserved |
| Income/expense, categories/subcategories, safe edits/archives | `phase1a`, `branches`, `phase3`, `home_dashboard`; immutable ledger identity and revision protections remain |
| Customer/invoice draft, edit, issue, partial/full payment, receivables/overdue | `phase2a`, `invoice_editor`, `phase5ab`, `phase5c`; Bridge shares the same services |
| Recurring bills/expenses, budgets, cashflow | `phase2b`, `phase3`, `phase4c`, `dashboard_design`, `home_dashboard` |
| Supported FX movement between different-currency accounts | `phase4c`, `fx_precision`; explicit source/received amounts, per-currency balances; excluded from operating income/expense |
| Reports/export/PDF | `phase3`, `branches`, `invoice_pdf`, `phase5ab`, `phase5c`, `pdf_recovery` |
| Finance AI under its own confirmation/entitlement gates | Complete assistant/operator/conversation/semantic/pending-intent tests in baseline; no Core shortcut |
| Import/reconciliation assistance | `phase6b`, `phase6c`, `bank_sections`; manual review and precision/FX holds remain |
| Mobile, useful empty/error/read-only states | New Phase 7 mobile CI (390×844), standalone routes, existing dashboard and shell tests; see status for actual browser result |

## Product limits that must be represented honestly

The current service explicitly rejects same-currency `record_currency_exchange`.
There is no general account-to-account same-currency transfer service or external
money-transfer facility. Do not simulate a transfer with an income/expense pair.
The supported movement gate covers existing different-currency exchange only;
Phase 9 must assess a separate internal-transfer capability if required for the
product's target users. The Finance assistant already avoids claiming money transfers.

Operational cashflow is not accrual P&L. The repository does not establish a full
chart of accounts, double-entry journal/general ledger, trial balance, balance sheet,
period close/lock, or accountant journal-adjustment workflow. Existing statement-row
matching/import review is useful reconciliation assistance, not certification of a
complete bank-reconciliation/period-close system. Do not market these missing
capabilities as implemented.

## Phase 9 Professional Readiness handoff

Assess and scope: internal same-currency transfers; chart of accounts and double-entry
ledger; trial balance; accrual P&L and balance sheet; full bank reconciliation;
controlled journal adjustments; period close/lock; accountant audit/export workflows.
Preserve history, native currencies and current cash semantics in any future design.
Phase 7 does not start this work or claim accountant-grade completeness.
