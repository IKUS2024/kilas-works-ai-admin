# Phase 7 status — CHECKPOINT / NOT COMPLETE

## Baseline / prerequisites
- Branch `feature/kilas-core-v2`; exact current remote baseline `967181a2e6ad27f8535aea89c24082acc125d47e`.
- Remote main `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`, unchanged. Upstream since Phase 6 changes only MASTER/ROADMAP/Phase 7 instructions; exact objects/tree restored locally without discarding work.
- All ten requested documents read completely. Phase 1–6 implementation retained; historical Phase 2 checkpoint prose is superseded by accepted Phase 3 prerequisite and current CI.
- Baseline CI all SUCCESS: Phase 2 `36025367120`, Phase 3 `36025367154`, Phase 4 `36025367262`, Phase 5 `36025367183`, Phase 6 `36025367315`. Phase 6 runs prior regressions, PG and mobile QA.

## Scope / decisions
- One existing Finance engine: Standalone remains independent; Connected adds optional Core-side mapping/customer/invoice references only.
- Explicit owner-authorized business + branch mapping, no name/contact merge. Draft creation only after owner-entered items/prices/currency/dates and confirmation. Issue/payment stay in existing Finance flows; Bridge reads authoritative totals/status.
- Review existing Finance `_write`, `db.app_purchase_transaction`, branch context and idempotency boundaries before implementation. No direct protected Finance SQL writes from Core.
- Default-off Bridge; no production DB/data, deployment, WhatsApp sends/cutover, media AI, redesign or Phase 8.
- Standalone sellability gate covers current operational Finance features, not a claim of double-entry/accountant-grade accounting. Professional readiness remains Phase 9.

## Milestones
1. Finance boundary audit: completed; Standalone regression baseline recorded, NOT green.
2. Connection schema/service: pending.
3. Customer link: pending.
4. Job invoice draft link: pending.
5. Authoritative read-back UI: pending.
6. Security/idempotency/concurrency: pending.
7. PostgreSQL/mobile QA: pending.
8. Exact scope/COMPLETE: pending.

## Current checkpoint / exact next action
Resume milestone 1 from this status, not from Phase 1. No Bridge implementation has started. The safe compound Finance boundary has been verified by 4 new passing tests, but the mandatory full existing Finance regression/sellability gate remains unfulfilled.

1. Triage the exact baseline failures listed below using isolated per-file processes and the full current Finance dependencies. Distinguish stale fixtures/labels/contracts from actual product defects; do not change stored-money semantics or remove assertions merely to obtain a green run.
2. Complete Standalone sellability coverage for existing accounts/transfers/opening balances/categories/invoices/payments/recurring/budgets/reports/FX/AI/edit/archive/mobile flows. A passing draft/payment boundary is not the whole sellability gate.
3. After that baseline is coherent, implement milestones 2–6 through the reviewed existing service boundary below; use explicit owner mappings and draft-only invoice creation.
4. Run disposable PostgreSQL and real mobile browser gates, all prior regressions, exact scope review. Only then mark COMPLETE. Do not start Phase 8.

## Exact remaining blockers / limits
- Existing Finance regression baseline is NOT green: 27 of 36 Python test files fail with the full current dependencies and actual unittest execution. Nine files pass. These failures precede any Phase 7 production change; no production code has been edited.
- Some confirmed failures are stale currency/category/UI expectations. Others still need diagnosis; it would be inaccurate to label every failure harmless test drift or certify Standalone sellability yet.
- This is a verification/triage backlog, not a credential/permission/production-data blocker. GitHub Actions remains available for later PG/mobile gates. No Phase 7 PG or browser pass is claimed.
- Preserve this passing audit-test checkpoint when execution time is exhausted. RESUME FROM STATUS FILE.

## Reviewed Finance architecture and safe reuse boundary
- `finance_service` is the sole tenant-scoped cash-ledger/invoice engine, with integer minor units. `finance_fx.minor_scale` currently returns 100 for every supported currency, including IDR. Do NOT revert this production contract to satisfy historical whole-rupiah fixtures.
- `finance_service._scope` validates business and real actor membership/admin rules. Finance services do not depend on Core/Jobs/Inbox/Bridge tables.
- `finance_entitlements.require_write` enforces self-service trial/paid state and emergency disable; `require_ai`/`capability` separately protect Finance AI. Read access remains available under existing rules when expired.
- `finance_branches.scope(target_business, branch, actor)` is the explicit context; `validate(write=True)` rejects all-branch or inactive targets, and Personal branches are private to their owner. No session/default inference should select a Bridge write destination.
- `finance_service._write(target_business, actor)` is already the reviewed compound command boundary used by `finance_invoice_editor.create`. It owns `db.app_purchase_transaction`; nested Finance service calls reuse the exact same business/actor transaction. The new proof test demonstrates customer + invoice + Core-side marker rollback together after a simulated link failure.
- Proposed Bridge use: reviewed `create_customer`, `get_customer`, `list_customers`, `create_finance_invoice`, `get_finance_invoice`, `get_invoice_totals`; owner explicitly confirms copied customer data and enters invoice items/currency/dates. No direct protected Finance SQL. Any Core-side link/operation writes must share the proven compound transaction.
- Existing customer/invoice create APIs accept 32-hex idempotency keys and reject incompatible replay via audited markers. Bridge also needs its own payload/actor/mapping-version operation record and immutable resulting references, so later edits/changed mappings cannot silently redirect replay.
- Draft invoice creation does not post a ledger entry. Existing Finance issue/payment flows remain authoritative. Partial/full payment read-back has been tested via the existing services; Bridge itself will not record payment or recalculate totals.
- Existing invoice detail route: `/business/<finance_business>/finance/invoices/<invoice>?branch_id=<explicit_branch>`. Invoice list lives at `/finance/receivables?section=invoices`, not `/finance/invoices`. Accounts/categories are managed via existing dashboard sections and POST routes.
- Business+Personal share one Finance feature set and remain isolated by existing workspace/branch rules. Finance product selection uses entitlement/master-data ownership; AI Admin-only records must not be silently converted into Finance businesses.
- No new schema/Bridge module/UI/Finance change has been made at this checkpoint. Proposed later storage is Core-side connection/customer/invoice/operation references only, with paired additive migration and explicit installer.

## New passing audit tests
Exact new test file: `client-hub/tests/test_kilas_finance_baseline.py` (4 tests PASS).
- Actual Finance dashboard/receivables/reports/assistant routes return 200 with Core/Customers/Jobs/Bridge disabled and no Core tables present.
- Existing compound transaction rolls back Finance customer, draft invoice, audit and a test-only link marker together if the link stage fails.
- Explicit branch and real actor, idempotent customer/invoice replay, DRAFT with no ledger posting, and existing Finance partial/full payments with authoritative totals/status.
- Expired self-service, emergency disable and all-branch write denial; expired invoice read remains available.

Command (from repo root; fresh subprocess):
`PYTHONPATH=/tmp/kilas-phase7-deps:$PWD/client-hub python scripts/run_offline_tests.py --only test_kilas_finance_baseline.py`

## Baseline execution protocol and honest results
- Installed the unchanged `client-hub/requirements.txt` into `/tmp/kilas-phase7-deps` outside the repo. Full PDF dependencies matter: PDF recovery passes with pypdf/pikepdf available.
- Baseline tests used temporary synthetic SQLite fixtures. Tests initialize their own disposable historical schema; no production database, customer data or migration invocation occurred.
- Initial exploratory run had incomplete dependencies/import path; its import/PDF failures are superseded by the full-dependency results below and are NOT product failures.
- Each file ran in its own process with `PYTHONPATH=/tmp/kilas-phase7-deps:$PWD/client-hub:$PWD/client-hub/tests`.
- Most files execute with `python client-hub/tests/<file>`. Four files have no main invocation: `test_finance_branches.py`, `test_finance_dashboard_design.py`, `test_finance_style_loading.py`, `test_finance_ui_integrity.py`; these were actually executed with `python -m unittest discover -s client-hub/tests -p <file>`. A bare exit 0 with zero tests is NOT counted as a pass.

| Existing test file | Actual baseline result |
| --- | --- |
| `test_finance_assistant_inline.py` | FAIL: failures=4, errors=1; 47 tests |
| `test_finance_assistant_upgrade.py` | PASS; 20 tests |
| `test_finance_bank_sections.py` | FAIL: failures=8, errors=1; 22 tests |
| `test_finance_branches.py` | FAIL: failures=12, errors=5; 39 tests |
| `test_finance_conversation_agent.py` | FAIL: failures=13, errors=2; 34 tests |
| `test_finance_conversational_boundaries.py` | FAIL: failures=7; 16 tests |
| `test_finance_dashboard_design.py` | FAIL: failures=2; 10 tests |
| `test_finance_documents_upgrade.py` | PASS; 5 tests |
| `test_finance_fx_precision.py` | FAIL: failures=1; 4 tests |
| `test_finance_home_dashboard.py` | FAIL: failures=15, errors=2; 45 tests |
| `test_finance_invoice_editor.py` | FAIL: failures=1; 18 tests |
| `test_finance_invoice_pdf.py` | PASS; 1 tests |
| `test_finance_live_conversation.py` | FAIL: failures=11; 23 tests |
| `test_finance_multibusiness.py` | FAIL: errors=10; 13 tests |
| `test_finance_pdf_recovery.py` | PASS; 8 tests |
| `test_finance_pdf_routing.py` | PASS; 13 tests |
| `test_finance_pending_intents.py` | FAIL: failures=8, errors=2; 26 tests |
| `test_finance_phase1a.py` | FAIL: failures=3; 18 tests |
| `test_finance_phase1b.py` | FAIL: failures=10, errors=1; 16 tests |
| `test_finance_phase2a.py` | PASS; 25 tests |
| `test_finance_phase2b.py` | FAIL: failures=4; 24 tests |
| `test_finance_phase3.py` | FAIL: failures=5; 20 tests |
| `test_finance_phase4a.py` | FAIL: failures=1; 15 tests |
| `test_finance_phase4b.py` | FAIL: failures=6; 35 tests |
| `test_finance_phase4c.py` | FAIL: failures=3; 25 tests |
| `test_finance_phase5ab.py` | FAIL: failures=1; 24 tests |
| `test_finance_phase5c.py` | FAIL: failures=2; 33 tests |
| `test_finance_phase6a.py` | FAIL: failures=5; 53 tests |
| `test_finance_phase6b.py` | FAIL: failures=5; 114 tests |
| `test_finance_phase6c.py` | PASS; 103 tests |
| `test_finance_semantic_agent.py` | FAIL: failures=17; 44 tests |
| `test_finance_semantic_brain.py` | FAIL: failures=9; 36 tests |
| `test_finance_style_loading.py` | PASS; 3 tests |
| `test_finance_ui_integrity.py` | PASS; 10 tests |
| `test_finance_unified_assistant.py` | FAIL: failures=4; 36 tests |
| `test_finance_ux_ai_fix.py` | FAIL: failures=4, errors=1; 18 tests |

## Confirmed triage examples (not blanket exclusions)
- `test_finance_fx_precision.test_combined_total_rounds_once` expects 1 while current minor-unit contract gives 50. The test's 25 IDR-per-unit rates encode the old IDR scale; preserve the once-at-end rounding invariant with correct current-unit fixtures instead of changing production FX.
- `test_finance_assistant_inline.test_expense_fills_draft_no_write_and_confirm_once` expects 120000 minor units for “120 ribu”; current two-decimal contract correctly stores 12000000. Other amount-related fixtures need the same contract review, not a production scale rollback.
- `test_finance_phase1a` expects 10 default categories while current catalog has 9; it directly deactivates the old category row instead of the current workspace category state. Verify public category-management behavior before changing assertions.
- `test_finance_invoice_editor.test_list_compact_search_status_archive_pagination` fails on the old exact “Buat Invoice” label; keep its pagination/search/archive invariants when repairing selectors.
- `test_finance_multibusiness` errors include `total_outstanding_minor` expectations that need review against the current grouped-currency report contract. Do not manufacture a cross-currency financial total.
- Other semantic/bank/branch/recurring/UI failures remain unclassified. Full test names are reproducible with the commands above; do not silently skip these files in a Phase 7 completion claim.

## Exact checkpoint scope / protection
Only `docs/KILAS_V2_PHASE7_STATUS.md` and `client-hub/tests/test_kilas_finance_baseline.py` are changed from baseline `967181a2e6ad27f8535aea89c24082acc125d47e`.
No Finance production code/accounting semantics/data/schema, existing assertions, prior phase implementation/status, WhatsApp behavior, deployment settings or production service changed. No second ledger, payment automation, invoice auto-issue, media AI or Phase 8 work.
The checkpoint commit is identified by `git log -1 -- docs/KILAS_V2_PHASE7_STATUS.md`; no self-referential SHA is fabricated.

## Recovery pass — checkpoint 1 (2026-09-24)
- Resumed exact remote feature `8f33dd8de8bb14bb68dae2b64c3a12365ab166cb`; remote main unchanged at `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.
- Current feature CI verified SUCCESS: Phase 2 `36027001196`, Phase 3 `36027001207`, Phase 4 `36027001279`, Phase 5 `36027001178`, Phase 6 `36027001321`. These are prior-phase gates, not evidence of a green Finance baseline.
- Re-executed all 36 existing Finance files and the four boundary tests with full installed requirements, offline network denial, synthetic SQLite, and fresh per-file unittest discovery processes. All counts match the preceding inventory; reproduced 9 passing / 27 failing existing files. No zero-test passes.
- Cluster: stale FX scale and category fixture contracts. FX once-at-end rounding now uses two 0.25-IDR-minor-unit contributions (individual rounding 0, combined 1), retaining every precision assertion. Category defaults assert the current nine sorted roots and seven utility children. Legacy catalog test now reproduces a pre-sync workspace with a genuinely retired system category; inactive/re-add tests use the authoritative workspace category service instead of the obsolete raw category flag.
- Changed only `test_finance_fx_precision.py`, `test_finance_phase1a.py`, and this status. Production contracts unchanged.
- Verification: FX 4, Phase 1A 18, nearby invoice/payment Phase 2A 25, Standalone boundary 4 — all PASS (51 tests).
- Remaining: other root-cause clusters require diagnosis. Bridge remains unstarted. This recovery run stops at a trustworthy green Finance baseline; it does not proceed to Bridge.
