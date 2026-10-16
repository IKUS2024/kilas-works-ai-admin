# Finance reset button placement — 16 October 2026

Reset Data Finance appears only inside the Finance **Dashboard context bar**, alongside Personal/Business and, in Business mode, the branch controls. Mobile wraps the same bar without overflowing. The button is absent from transaction/Income/Expense lists, Accounts, Bills, Budget, Invoices, Payees, Reports and the reset review page. Existing owner and read-only visibility checks remain.

This release changes only placement, scoped spacing and the Finance stylesheet cache version. Reset service, routes, authorization, canonical Personal selection, ledger calculations and schema are unchanged. Clicking the button still posts only to the existing warning preparation endpoint. Final reset still requires the exact server-bound target, typed RESET and separate acknowledgement. No production reset, preparation or transaction was invoked during verification.

## Read-only production navigation

- Canonical owner Personal GET: https://app.kilasworks.id/finance/personal . Existing owner session redirects to its existing ledger; no mode POST or financial write is needed.
- Previously verified owner's existing Personal Dashboard: https://app.kilasworks.id/business/2/finance?branch_id=11 . Omit `view` to stay on Dashboard.
- Read-only tabs: use the sidebar Dashboard, Transaksi, Akun, Tagihan, Anggaran, Invoice, Penerima and Laporan links. Verify the reset button only on Dashboard. Personal has no Branch or Add Branch controls.
- In an already selected Business Dashboard, inspect the same context bar next to Branch/Add Branch. Use only existing GET sidebar links and the branch GET selector. Do not submit mode changes, Reset Data Finance, typed confirmation or other forms in production verification.

## Verification and release

- **43 targeted tests pass**, zero failures/errors/skips: Personal/reset safeguards and placement, Finance UI integrity, stylesheet loading and locales. The new placement test verifies both modes and absence on the other tabs without financial mutations; staff cannot see Business reset.
- **Chromium passes at 1440, 390 and 320px**, both Personal and Business, languages Indonesian/English/Spanish/Chinese. The button is a child of the Dashboard context bar, remains within its bounds, and is absent on other tabs/review. Local warning-only clicks preserve all financial fixture rows; no final reset submissions. External requests blocked.
- [Browser evidence](evidence/finance-reset-dashboard-20261016/). Production browser access remains blocked by this workspace's execution proxy; parent cloud-browser verification can follow the GET navigation above.
- Deploy verification pending the approved main push and existing Client Hub deployment.
