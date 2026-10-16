# Finance reset button placement — 16 October 2026

Reset Data Finance appears only inside the Finance **Dashboard context bar**, alongside Personal/Business and, in Business mode, the branch controls. Mobile wraps the same bar without overflowing. The button is absent from transaction/Income/Expense lists, Accounts, Bills, Budget, Invoices, Payees, Reports and the reset review page. Existing owner and read-only visibility checks remain.

This release changes only placement, scoped spacing and the Finance stylesheet cache version. Reset service, routes, authorization, canonical Personal selection, ledger calculations and schema are unchanged. Clicking the button still posts only to the existing warning preparation endpoint. Final reset still requires the exact server-bound target, typed RESET and separate acknowledgement. This task invoked no production reset, preparation or transaction.

## Read-only production navigation

- Canonical owner Personal GET: https://app.kilasworks.id/finance/personal . Existing owner session redirects to its existing ledger; no mode POST or financial write is needed.
- Previously verified owner's existing Personal Dashboard: https://app.kilasworks.id/business/2/finance?branch_id=11 . Omit `view` to stay on Dashboard.
- Read-only tabs: use the sidebar Dashboard, Transaksi, Akun, Tagihan, Anggaran, Invoice, Penerima and Laporan links. Verify the reset button only on Dashboard. Personal has no Branch or Add Branch controls.
- In an already selected Business Dashboard, inspect the same context bar next to Branch/Add Branch. Use only existing GET sidebar links and the branch GET selector. Do not submit mode changes, Reset Data Finance, typed confirmation or other forms in production verification.

## Verification and release

- **43 targeted tests pass**, zero failures/errors/skips: Personal/reset safeguards and placement, Finance UI integrity, stylesheet loading and locales. The new placement test verifies both modes and absence on the other tabs without financial mutations; staff cannot see Business reset.
- **Chromium passes at 1440, 390 and 320px**, both Personal and Business, languages Indonesian/English/Spanish/Chinese. The button is a child of the Dashboard context bar, remains within its bounds, and is absent on other tabs/review. Local warning-only clicks preserve all financial fixture rows; no final reset submissions. External requests blocked.
- [Browser evidence](evidence/finance-reset-dashboard-20261016/). Production browser access remains blocked by this workspace's execution proxy; parent cloud-browser verification can follow the GET navigation above.
- Application commit `e8da82a35d62375c28e2dd55beab3f53501383c9` pushed to main. Existing Client Hub deploy `dep-db98370m7kps73bgkbb0` is **LIVE**, finished **2026-10-16 19:58:22 UTC**. Running worker confirms the same SHA. No error-level logs observed from deployment start through 19:59:10 UTC. No schema/configuration changes.
- Production verification was read-only. The 31-table comparison found 29 unchanged tables and changes to accounts/transactions from two pre-deployment Business reset confirmations already recorded under actor 2: business 2 / branch 1 completed **19:55:20 UTC**, and business 13 / branch 19 completed **19:56:51 UTC**. Both predate this placement deployment; the local tests never contact production. Audit events confirm their exact scope. No reset request was created after this deploy at the verification cutoff. No attempt was made to reverse or modify this production activity. Therefore this checkpoint does **not** claim that all production data stayed unchanged during the concurrent work.
- Evidence follow-up modifies documentation only; application source remains identical to the LIVE commit.
