# Finance calculation audit — 2026-11-04

Base: `bf57edc67aef890bac2ad97f0853e3a541b1e5b1` (live checkout).
Implementation: `715edaa3f6c0cb4e9c048ad890d480bead41dab6`.
Draft PR: https://github.com/IKUS2024/kilas-works-ai-admin/pull/205.
Detailed per-suite results and failure classifications: [JSON artifact](finance-calculation-audit-20261104.json).

## Verified defects and repairs

1. **Split expenses in ledger/conversation summaries.** A single 10,000-minor expense allocated 6,000/3,000/1,000 to three categories previously appeared entirely under the first category; filtering the secondary category returned no summary. `get_entry_summary` and category-aware `get_cash_totals` now use `finance_category_amounts`. Two children under one parent contribute 9,000 and one transaction, not two. Category filtering selects allocated money; the transaction list continues to display the complete underlying transaction. Account, customer, project, branch and unfiltered totals stay cash-based and do not multiply entries. Tests cover date, account, literal search, branch isolation, voiding, unsplit entries and personal income source grouping.
2. **FX chart rounding.** At a synthetic but realistic USD/IDR reference rate of 15,750.25, two monthly USD-cent incomes independently format as 15,750 IDR minor units each, but the whole range is 31,501, not 31,500. Range income/expense/net now convert the native range once. Net converts native income minus native expense before rounding, matching the existing main period summary; it is not computed by subtracting rounded displays. Monthly bars remain independently formatted. Missing required FX rates remain unavailable, never partial totals.
3. **Retired category budget history.** A 10,000 budget and 2,500 expense disappeared from the budget summary when its category was deactivated. Summary totals now include all scoped budgets and posted category allocations, independently of editable category visibility. The existing category editor design is unchanged.
4. **Historical inactive-account currencies.** Budget FX lookup only included active account/budget currencies. A historical USD expense on a deactivated account could show an unavailable total despite a usable rate. Needed currencies now also come from the actual historical expense rows.
5. **Large category sums.** Two individually valid amounts, `2**63-1` and `17`, caused SQLite `SUM` overflow. Category totals now reuse the existing exact integer aggregator and normalize PostgreSQL numeric results to Python integers. This is SQLite parity and a stable return-type repair; it is not evidence of corrupted production balances.

No templates, styles, browser layout, receipt implementation, credentials, stored finance history, or schema migrations were changed.

## Validation

- **131 tests passed**, zero failures/errors/skips, across 13 current suites: calculation audit, approved revisions, edit package, expense entries, purchase plans, FX precision, invoice editor, direction filters, UI accounting integrity, workspace corrections, current final package, receipt preview and standalone Finance boundary.
- **7 native PostgreSQL 18 tests passed**: two new allocation/overflow parity cases and five existing atomic invoice/bill edit, concurrency, rollback and scope cases. Used a newly created disposable Docker database `kilas_finance_qa` bound to loopback, not production.
- The new calculation suite contains **11 tests**. Running the identical suite against a pristine archive of the base commit is red; candidate is green. Some source-group tests additionally exercise the new optional parent-grouping API.
- Originally selected isolated baseline: **57 files / 1,183 tests**, including the 11 new tests. All **56 pre-existing suite results are identical** between pristine base and candidate. This selection omitted the two Finance Bridge files; it must not be described as full Bridge coverage. See the expanded follow-up below. The only changed suite in this original selection is the new calculation suite, now passing. Original tracked selection has 1,172 tests.
- The complete baseline is **not green**: candidate has 109 assertion-failure events, 653 error events and 10 skipped PostgreSQL cleanup cases. Subtests can produce multiple events per test. Do not describe those scenarios as tested successfully.
- `git diff --check` passed. Added a dedicated SQLite/PostgreSQL workflow; existing broad workflows remain responsible for reporting their failures.

The full baseline was run in fresh subprocesses with the repository offline guard. Current focused suites additionally clear provider/database environment settings. Production data was not mutated. No paid inference or real receipt upload was performed.

### Failure investigation, not blanket baseline acceptance

Most legacy error cases inherit `test_finance_phase6a.ReceiptTests.setUp`, which patches `finance_receipts.requests.post`; that attribute no longer exists after the scanner moved to the shared OpenAI adapter. Those tests fail before their scenarios execute. Current `test_finance_final_package` and `test_finance_receipt_preview` pass (12 tests combined), including strict GPT-6 Luna request shape, no autosave, explicit human confirmation, replay protection, entitlement/scope/CSRF checks and ambiguous-provider-failure handling.

Other groups were inspected against implementation: archived general AI returns false from `finance_entitlements.capability`; deterministic Finance explicitly returns FREE access; modern authentication uses the authenticate helper instead of raw session `user_id`; default UI locale is English; current category names follow EXPENSE_V4. Old expectations for enabled analyst/operator endpoints, expired paid access, Indonesian text, old catalogs and raw sessions therefore do not establish calculation defects. Their precise failing test names/signatures remain in the JSON artifact rather than being suppressed or rewritten to force a green result.

`test_finance_style_loading` reports an existing stylesheet-after-body ordering violation. That is an unchanged UI issue, outside the explicit calculation-only scope. Legacy fixture maintenance and this UI issue remain follow-up work; this audit does not certify the entire historical suite.

## Additional scope conclusions

- Existing current tests reconcile manual income/expense, opening balance, FX/internal transfers, invoice partial/full payments, payment edits, recurring bills, installment rounding and workspace moves with balances/reports. Issuing an invoice or scheduling a bill does not post cash; explicit payment posts exactly once.
- Invoice financial totals are integer quantity × integer unit-price minor units, bounded to signed BIGINT before persistence. The current Finance invoice model has no separate percentage tax/discount calculation fields; tax ID is identity text. No new tax/discount policy was invented.
- `get_report_invoices(as_of=...)` reconstructs dated payments; `get_receivables_summary(today=...)` is the live outstanding summary with an aging reference day. Call sites use the latter for current workspace status. It was not changed into a historical report.
- Receipt `extract()` already calls `chat_models.check('gpt-6-luna')` and `providers._openai`, with no Anthropic fallback. The parent independently verified deployment `dep-dblloiui0phs73b3pfog` at the base SHA and startup log `2026-11-04T16:26:28.316509633Z`, `KILAS_CHAT_MODELS {"gpt-6-luna":"verified"}`. That production account-access evidence is parent-provided; this worker performed only offline mocked scanner tests.

## Reproduction and deployment handoff

```sh
python scripts/run_finance_baseline.py --logs /tmp/finance-audit-results
python client-hub/tests/run_finance_regressions.py \
  test_finance_calculation_audit test_finance_approved_revisions \
  test_finance_edit_package test_finance_expense_entries test_finance_purchase_plans \
  test_finance_fx_precision test_finance_invoice_editor test_finance_direction_filters \
  test_finance_ui_integrity test_finance_workspace_corrections \
  test_finance_final_package test_finance_receipt_preview test_kilas_finance_baseline \
  test_kilas_finance_bridge test_kilas_finance_bridge_routes
```

Native scripts require an explicit `FINANCE_LOCAL_PG_QA=1` and loopback `DATABASE_URL` with database name exactly `kilas_finance_qa`; they refuse production/non-loopback targets. See the added workflow for the synthetic setup. Run `finance_calculation_postgres_qa.py` and `finance_edit_postgres_qa.py` against that disposable database.

No migration, secret, model, or environment change is required for deployment. Parent must coordinate review/CI disposition and integration, then deploy the integrated SHA to Client Hub and verify it live. This worker did not approve, merge or deploy the PR. Ordinary application rollback to the previous SHA is sufficient because these repairs alter read aggregation only.

## Reviewer follow-up: Bridge scope and exact-head CI

The dedicated calculation workflow on `875030e4e8b9ef8e7e91b1f68536acde31f148f9` [completed successfully](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/41870616838), including offline and native PostgreSQL steps. No production implementation changes were made during the following coverage repair.

The reviewer correctly identified that `test_kilas_finance_bridge.py` and `test_kilas_finance_bridge_routes.py` were outside the original filename selection. Both exact original suites were executed on pristine `bf57edc` and candidate `875030e4`: **26 tests, the same 3 service + 6 route failures on both**. These were investigated individually:

| Original failing case | Verified cause and current check |
| --- | --- |
| expired/emergency/disabled AI | Expected expired paid-only Finance, but current deterministic Finance is FREE. Free mapping succeeds; emergency disable and suspended source still reject writes. |
| personal branch/unavailable product | Personal branch rejection already passes; the historical beta flag does not disable FREE Finance. A genuinely unavailable product is explicitly tested and rejected. |
| verified Assist includes owned Finance | Expected inactive → PAID_ACTIVE; current state remains FREE. Foreign target ownership and suspended source are still explicitly rejected, with no cash posting. |
| owner forms | Raw `user_id` switched to a different actor while retaining the old revocable-session token; auth redirected to login before the route ran. Modern authenticated owner flow passes. |
| CSRF/foreign forms | Same invalid-session fixture. Real authenticated CSRF, oversized payload and foreign-owner assertions now execute and pass. |
| job editor/payment | Same invalid-session fixture. Draft/issue, rollback, full payment and replay now execute and pass. |
| platform admin auto connection | Same invalid-session fixture. Real admin session and emergency-disable/automatic connection checks now execute and pass. |
| revoked Finance access route | Same invalid-session fixture: the 303 was login, not leaked Finance access. With a valid source-owner session, Core job stays 200 without invoice details and the Bridge route rejects access with 404. |
| standalone Finance | Raw actor swap followed redirects to the login page, giving misleading 200s. Real standalone sessions now verify Finance pages, explicit 404 for archived assistant, and zero Bridge writes. |

Updated tests use the existing real-session authentication helper; no auth middleware, entitlement policy or Bridge implementation was weakened. Added direct service coverage for revoked destination membership (read, payment options and mapping writes reject without changing records), and a route regression proving forged raw-session actor swaps still reject without disclosing invoice data.

**All 28 updated Bridge tests pass on both pristine base production code and candidate production code.** This verifies current behavior independently of the calculation changes and demonstrates that the observed nine failures were stale fixture/contract expectations, not a current permission bypass. Baseline discovery now includes all `test_kilas_finance_*.py`; the dedicated regression workflow includes both Bridge suites.

Other final-head CI failures were independently reproduced on pristine base: four Home UI assertions; the known Finance catalog/style assertions; WhatsApp auth fixtures (3 failures/2 errors); three workspace navigation assertions; the subscription dashboard status assertion at line 602; Assist forced-language dict-versus-None; and six Node viewport fixture errors (`root.dataset` missing for `chatReflow`). These remain failures, not successful coverage. The exact-base reproductions used isolated offline fixtures; broad workflows are not being marked green or bypassed.

Expanded candidate baseline completed: **59 files / 1,211 tests**, including both updated Bridge suites. All original 57 suite results are unchanged; both added suites pass (28 tests). The selected current suites therefore total **159 passing tests**, plus the previously verified 7 native PostgreSQL tests. The expanded historical baseline remains non-green for the documented existing failures. Full expanded per-file results are included in the JSON artifact.

## Mobile Bridge browser follow-up

The calculation workflow on `8b98a584` passed. Phase 7 then reached its previously skipped browser step and failed at line 34: the standalone persona redirected to `/login`. Running the exact original browser script and harness against base `bf57edc` reproduced that same assertion. The harness wrote only `user_id`, omitting the current revocable authentication session.

The synthetic harness now calls production `security.login_user` for its disposable personas. The browser explicitly selects Indonesian locale, expects the archived assistant to return 404, and uses emergency disable to test readable history plus blocked writes; historical paid-expiry flags no longer disable FREE Finance. No production implementation or authentication/UI assertion was weakened.

The complete updated browser script passes against **both base and candidate production code**, at 390×844: standalone Finance pages, explicit workspace/customer mapping, reviewed invoice draft, authoritative invoice detail and partial payment, foreign-tenant rejection, emergency read/write behavior, no horizontal overflow and no JavaScript errors. Both produced `Phase 7 mobile browser QA PASS`. Local execution used installed Chromium 151.0.7922.173 via a temporary launch adapter because Playwright CDN download returned HTTP 403; CI continues using its installed Playwright browser. No assertion was bypassed by the adapter. New-head CI must still be verified after this harness-only commit.
