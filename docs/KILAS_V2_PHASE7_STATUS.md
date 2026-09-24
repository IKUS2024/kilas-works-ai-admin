# Phase 7 status — BRIDGE IMPLEMENTED / FINAL QA IN PROGRESS

## Current mobile QA blocker

- Runtime checkpoint `98ea4d85caad32aad1cbdabc330dc3728c782646` is committed.
- CI `36039212956` on prior `e4579f4`: complete Finance baseline **1018 PASS**;
  SQLite Bridge 14 PASS; PostgreSQL corrections 4 PASS and Bridge 10 PASS, including
  real migrations, repeat installers, concurrency and rollback. No PG error remains.
- Mobile found horizontal overflow on the existing standalone Finance dashboard at
  390×844. This is a real sellability QA finding, not a green gate. No CSS workaround
  or assertion relaxation has been applied. Browser certification remains BLOCKED.
- Exact next action: diagnostic mobile run records screenshot and DOM geometry of
  overflowing elements, continues functional flows, then fails if any overflow remains.
  Fix the actual layout narrowly with coverage, rerun full final gates.
- Diagnostic checkpoint files: `client-hub/tests/kilas_finance_bridge_browser_qa.py`
  and this status. Product and accounting code unchanged in this checkpoint.

## QA refinement checkpoint

- Bridge implementation checkpoint: `e4579f4cd5120d711f9a18ade22c0ac38428ba0e`.
- Remote Phase 2–6 CI on that exact head SUCCESS: `36039212932`, `36039213105`,
  `36039212870`, `36039213104`, `36039212885`; includes their PostgreSQL and mobile
  suites plus Phase 1 regression. Phase 7 `36039212956` is still running.
- Exact refinement files: Bridge service/routes; shared Bridge cases; Flask route
  tests; synthetic browser harness; Phase 7 workflow; sellability audit and this status.
- Review closed a real boundary gap: Bridge refuses Personal branches because current
  Finance invoice UI is Business-only; honors existing Finance product visibility.
  Private financial form responses use `private, no-store`.
- **13 service + 4 Flask tests PASS**. Added distinct-key concurrent invoice attempts
  (exactly one winner), inverse-business connection lock ordering, Personal/hidden
  Finance rejection. Existing 1018-test baseline pass remains recorded below.
- Synthetic harness persona switching now precedes the real Finance-session routing
  hook, without changing app behavior. Local real Flask harness smoke PASS.
- Baseline and PostgreSQL/mobile CI jobs now run independently for faster feedback;
  both must pass. No pending check is called successful.
- Exact next action: inspect PostgreSQL/mobile results, fix only proven defects,
  inspect screenshots and final baseline, then record COMPLETE if all gates pass.

## Current Bridge checkpoint (supersedes recovery sections below)

- Passing Finance recovery commit: `1b616f2c5b869a3a8738ab2eb804fdafb9042d69`.
  **FINANCE BASELINE GREEN — BRIDGE IMPLEMENTATION STARTING** gate was met before
  any Bridge implementation. Both original positive move tests remain unchanged.
- Completed milestones 2–6: explicit versioned owner mapping, explicit customer link
  or creation, reviewed Job → Finance DRAFT, immutable historical links, Finance
  authoritative status/totals/payment readback, additive owner forms and cards,
  idempotency, concurrency and atomic failure coverage. Default-off explicit installer.
- Full Finance rerun after Bridge: **1018 PASS, 39 executed files, zero failures,
  errors, skips or zero-test passes** (`/tmp/kilas-phase7-bridge-baseline/results.json`).
- Bridge SQLite: **10 service + 4 real Flask/security/standalone tests PASS**.
  Phase 1–6 local regression selectors all PASS again after the UI integration.
- Exact files in this milestone: `client-hub/app.py`, `finance_service.py`;
  `client-hub/kilas_core/finance_bridge.py`, `finance_bridge_schema.py`,
  `finance_bridge_routes.py`; paired 0060 Bridge migrations; templates
  `customer_detail.html`, `job_form.html`, `_finance_bridge_panel.html`,
  `finance_bridge.html`, `finance_bridge_error.html`; tests
  `kilas_finance_bridge_cases.py`, `test_kilas_finance_bridge.py`,
  `test_kilas_finance_bridge_routes.py`, `kilas_finance_bridge_postgres_qa.py`,
  `kilas_finance_bridge_dev.py`, `kilas_finance_bridge_browser_qa.py`;
  Phase 7 workflow; this status, `KILAS_V2_FINANCE_BRIDGE.md`,
  `KILAS_V2_FINANCE_SELLABILITY.md`.
- Recovery head Phase 2–6 remote CI all PASS. Initial new Phase 7 CI `36036790413`
  failed before product tests because its Python 3.11 could not parse existing Finance
  multiline f-strings. Workflow now uses Python 3.12, matching Phase 2–6. No test or
  product assertion was weakened to fix the interpreter mismatch.
- PostgreSQL and mobile browser certification **PENDING**, not claimed complete.
  Cloud browser cannot open loopback (`ERR_BLOCKED_BY_CLIENT`); dedicated synthetic
  CI fixture/script follows existing Phase 2–6 browser QA pattern. No production data.
- Standalone feature audit documented, including honestly unsupported same-currency
  general transfers and accountant-grade capabilities deferred for Phase 9 assessment.
  Existing supported FX movement and cash meaning are unchanged.
- `git diff --check` PASS. No production deploy/WhatsApp change/Phase 8.
- Current checkpoint SHA: commit containing this section; previous exact SHA above.
- Exact next action: inspect Phase 7 PostgreSQL/mobile CI, fix real defects narrowly,
  inspect screenshots and final diff, record final exact evidence; COMPLETE only if
  every required gate passes.

## Current continuation checkpoint

**FINANCE BASELINE GREEN — BRIDGE IMPLEMENTATION STARTING**

- Resumed remote feature `2c82f9ea131862605d41206f6546a55a33f00b93`; remote main
  `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`. Head CI Phase 2–6 all SUCCESS:
  `36032254129`, `36032254008`, `36032254273`, `36032254003`, `36032253987`.
- Final complete `PYTHONPATH=/tmp/kilas-phase7-deps python scripts/run_finance_baseline.py
  --logs /tmp/kilas-phase7-relocation-final`: **1018 PASS, 39 executed files,
  0 failures, 0 errors, 0 skips, 0 zero-test passes**. Both original positive move
  tests are unchanged and pass. 12 additional correction regressions pass.
- Design: immutable database correction commands with monotonic versions, strict
  same-business ownership, owner-private workspace authorization, unchanged economics,
  retained row IDs, opening history, repeated/reverse move and concurrency protection.
  Full rationale and safe exclusions: `KILAS_V2_WORKSPACE_CORRECTIONS.md`.
- HTTP destination initialization now shares the Finance move transaction. Late
  failure restores the entire request including newly created workspace/defaults.
- Raw UPDATE/tenant changes/replayed permission/history edits remain rejected.
  Invoice/FX/import/reconciled/posted-recurring/project/customer-linked records
  cannot be partially relocated. Eligible unposted rules preserve identity/schedules.
- Exact files: `client-hub/db.py`, `finance_service.py`, `routes_finance.py`;
  paired `client-hub/migrations/0059_finance_workspace_corrections_{sqlite,postgres}.sql`;
  `client-hub/tests/test_finance_workspace_corrections.py`,
  `client-hub/tests/finance_workspace_postgres_qa.py`;
  `.github/workflows/kilas-v2-phase7-qa.yml`; this status and the design document.
- `git diff --check` PASS. Phase 1 regressions PASS (30 tests); remaining prior-phase
  regression rerun is in progress. PostgreSQL runtime is **pending CI**, not claimed:
  local `setpriv` cannot create a non-root PostgreSQL process. The new workflow uses
  a disposable loopback PostgreSQL 18 service, never production data.
- Checkpoint SHA: the commit containing this section (`git log -1 --
  docs/KILAS_V2_PHASE7_STATUS.md`); the following milestone will record its exact SHA.
- Exact next action: implement explicit, default-off connection/customer/draft-invoice
  Bridge using existing Finance `_write` and service APIs; inspect PostgreSQL CI;
  complete standalone/mobile/security gates. Do not start Phase 8 or deploy.

All earlier blocked/recovery sections below are historical and superseded by this checkpoint.

## Current recovery result (2026-09-24)
- Branch: `feature/kilas-core-v2`. Resumed existing audit checkpoint `8f33dd8de8bb14bb68dae2b64c3a12365ab166cb`; did not restart Phase 7. Phase 1–6 remain complete.
- **Baseline NOT green: 1004 passing tests, 2 errors, 0 skips, 0 zero-test passes across 38 independently executed files (1006 tests).** All 36 original Finance files ran: 35 pass; `test_finance_home_dashboard.py` has 43 passes and the two genuine workspace-move errors below. The added branch-delete file passes 4 tests and all 4 original Standalone boundary tests still pass.
- Four narrow production defects fixed: unused branch deletion FK/history handling; first Finance GET before branch setup; budget category rename/archive using workspace settings; bank-review input multiplying IDR/JPY amounts by 100 on resubmission. Money scale, reporting currency groups, isolation guards and audit semantics were preserved.
- Full original failure classification: [KILAS_V2_PHASE7_FINANCE_TRIAGE.md](KILAS_V2_PHASE7_FINANCE_TRIAGE.md) — 183 distinct failing methods / 186 failure entries including repeated subtest variants, grouped by verified root cause.
- No Bridge implementation, production deployment, production database/customer data, schema migration, WhatsApp change, or UI redesign. Synthetic test databases initialized their own schemas only.

## Exact remaining blocker — immutable branch identity versus workspace relocation
Classification: **genuine production bug / service-schema conflict**, not a stale assertion.

Both original tests remain enabled and unchanged in their positive move invariants:
1. `test_finance_home_dashboard.DashboardHomeTests.test_transaction_workspace_move_is_real_reversible_and_never_double_counts`
2. `test_finance_home_dashboard.DashboardHomeTests.test_account_workspace_move_moves_opening_balance_transactions_and_recurring_rule`

Reproduction: full-dependency fresh unittest discovery of `test_finance_home_dashboard.py` produces two `sqlite3.IntegrityError: finance branch mismatch` errors. Both routes reach `finance_service._workspace_move_revision`, which inserts a revision then attempts `UPDATE finance_transactions SET branch_id=?,account_id=?,category_id=?...`. SQLite UPDATE guards in `finance_branch_migration.migrate_sqlite` reject changing branch or business identity. PostgreSQL migration `0033_finance_branches_postgres.sql` installs the same `finance_branch_immutable()` policy for accounts, transactions, invoices, recurring rules and bank imports. PostgreSQL failure is established by the schema definition, not claimed as a new live PG reproduction.

Safety evidence from disposable SQLite probes:
- With both workspaces initialized, each failing service call restores the complete database dump exactly: opening balances, transactions, revisions, recurring schedules, destination records and audit rows all roll back. No double-counted cash or partial transaction revision remains.
- The HTTP route initializes a missing Personal workspace **before** the move transaction. A failed first move leaves that empty workspace/defaults initialized, while the original ledger row remains byte-for-byte unchanged and no move revision survives. This route-level side effect also needs resolution; service rollback is not a claim of whole-request rollback.

Why unresolved in this recovery pass: successful relocation requires reconciling an existing financial-identity guarantee with a supported move operation across both database engines and every linked record. Removing/disabling the immutable guard, deleting/reinserting historical ledger rows, or changing the test to accept failed moves would weaken isolation/history or conceal the defect. A narrow assertion/template fix cannot safely resolve it. No guard, schema or history was changed to force a pass.

Exact next action: resolve the accounting design for an audited authorized relocation versus an append-only correction, including target-workspace initialization inside the atomic boundary, paired SQLite/PostgreSQL protection, personal-owner/business authorization, immutable tenant identity, invoice/FX prohibitions, recurring/import/reconciliation links, repeat/reverse moves and concurrent rollback. Keep the two positive tests and raw-SQL isolation checks. Then rerun the complete baseline. **Do not start Bridge while this blocker remains.** This recovery pass stops at the user's documented genuine-blocker condition.

## Reproducible gate and CI limits
Install unchanged `client-hub/requirements.txt` in an isolated environment, then run from repository root:

```sh
python scripts/run_finance_baseline.py
```

For the external dependency directory used in this run:

```sh
PYTHONPATH=/tmp/kilas-phase7-deps python scripts/run_finance_baseline.py
```

The runner discovers every `test_finance_*.py` plus `test_kilas_finance_baseline.py`, uses one new unittest process per file, injects the existing offline/credential-cleanup harness, records full logs and counts, continues after failures, and exits nonzero on failures/timeouts/skips/zero tests. Final full run returned exit 1 for exactly the two blocker errors. The final strengthened Phase 1B rejection assertion and home-list selector were independently rerun afterward: Phase 1B 16 PASS; home 43 PASS / 2 unchanged errors.

Existing Phase 2–6 CI was green before recovery. At production-fix checkpoint `d151d1f7b730a0583e0b20ac5c1b3d5a31e23a03`, CI again completed SUCCESS: Phase 2 `36031203536`, Phase 3 `36031203482`, Phase 4 `36031203520`, Phase 5 `36031203473`, Phase 6 `36031203594`. Those prior-phase workflows are not the full Finance gate; they do not override the two local baseline errors. No Phase 7 Bridge PostgreSQL/mobile completion is claimed.

## Mandatory coverage actually exercised
| Area | Executed coverage |
| --- | --- |
| Accounts, opening balances, income/expense | Phase 1A/1B, branches, home, dashboard design |
| Transfers / FX / currency precision | FX precision, branches, semantic agent; FX-linked move protection in home |
| Categories/subcategories, business/branch/tenant isolation | Phase 1A, branches, home category manager, multi-business, assistant suites |
| Invoices, partial/full payments, receivables/overdue | Phase 2A, Phase 4B/4C, Phase 5A/B/C, invoice editor, live conversation |
| Recurring/bills, budgets, reports/cash flow | Phase 2B, Phase 3, home, dashboard design, semantic agent |
| Finance AI / conversation assistant | Inline, upgrade, conversation, boundaries, pending intents, semantic agent/brain, unified |
| Documents/PDF | Phase 6A/B/C, bank sections, document upgrade, invoice PDF, PDF recovery/routing |
| Edit/archive/delete and audit | Branch-delete recovery, branches, invoice editor, home, live conversation, Phase 4C |
| Entitlements/read-only, trial-backed flows | Inline expiration, multi-business expiry/emergency, UX receipt entitlement; trial fixtures used throughout |
| UI/navigation | Style loading, UI integrity, UX/AI, dashboard design, home, invoice editor |
| Standalone independence | All four `test_kilas_finance_baseline.py` tests |

## Final per-file execution inventory
| File | Tests | Result |
| --- | ---: | --- |
| `test_finance_assistant_inline.py` | 47 | PASS |
| `test_finance_assistant_upgrade.py` | 20 | PASS |
| `test_finance_bank_sections.py` | 22 | PASS |
| `test_finance_branch_delete_recovery.py` | 4 | PASS |
| `test_finance_branches.py` | 39 | PASS |
| `test_finance_conversation_agent.py` | 34 | PASS |
| `test_finance_conversational_boundaries.py` | 16 | PASS |
| `test_finance_dashboard_design.py` | 10 | PASS |
| `test_finance_documents_upgrade.py` | 5 | PASS |
| `test_finance_fx_precision.py` | 4 | PASS |
| `test_finance_home_dashboard.py` | 45 | 43 PASS / 2 workspace-move errors |
| `test_finance_invoice_editor.py` | 18 | PASS |
| `test_finance_invoice_pdf.py` | 1 | PASS |
| `test_finance_live_conversation.py` | 23 | PASS |
| `test_finance_multibusiness.py` | 13 | PASS |
| `test_finance_pdf_recovery.py` | 8 | PASS |
| `test_finance_pdf_routing.py` | 13 | PASS |
| `test_finance_pending_intents.py` | 26 | PASS |
| `test_finance_phase1a.py` | 18 | PASS |
| `test_finance_phase1b.py` | 16 | PASS |
| `test_finance_phase2a.py` | 25 | PASS |
| `test_finance_phase2b.py` | 25 | PASS |
| `test_finance_phase3.py` | 20 | PASS |
| `test_finance_phase4a.py` | 15 | PASS |
| `test_finance_phase4b.py` | 35 | PASS |
| `test_finance_phase4c.py` | 25 | PASS |
| `test_finance_phase5ab.py` | 24 | PASS |
| `test_finance_phase5c.py` | 33 | PASS |
| `test_finance_phase6a.py` | 53 | PASS |
| `test_finance_phase6b.py` | 115 | PASS |
| `test_finance_phase6c.py` | 103 | PASS |
| `test_finance_semantic_agent.py` | 44 | PASS |
| `test_finance_semantic_brain.py` | 36 | PASS |
| `test_finance_style_loading.py` | 3 | PASS |
| `test_finance_ui_integrity.py` | 10 | PASS |
| `test_finance_unified_assistant.py` | 36 | PASS |
| `test_finance_ux_ai_fix.py` | 18 | PASS |
| `test_kilas_finance_baseline.py` | 4 | PASS |

## Historical audit and recovery checkpoints
The original audit inventory below is retained for traceability; it is superseded by the current result above. Original-checkpoint statements about unchanged production code apply only to that checkpoint.

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

## Original audit checkpoint scope / protection (historical)
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

## Recovery pass — checkpoint 2
- Cluster: stale minor-unit payment fixtures and translated UI selectors. Operator/payment invoices now use 50,000,000 minor units for Rp500,000 requests; live conversation fixtures similarly use the current IDR scale. Overpayment, concurrent/replayed confirmation, audit rollback, stale invoice re-review, partial/full settlement and exact cash assertions remain intact. Decimal-input coverage explicitly tests supported fractions/rounding and rejects invalid precision/nonpositive amounts.
- UI assertions follow the verified current AI Finance navigation, invoice-create URL, and Buka Tampilan Pelanggan label, retaining pagination/search/archive and no-AI-on-GET invariants.
- Files: `test_finance_phase4a.py`, `test_finance_phase4b.py`, `test_finance_phase4c.py`, `test_finance_phase5ab.py`, `test_finance_invoice_editor.py`, `test_finance_live_conversation.py`.
- Isolated full-file verification: 15 + 35 + 25 + 24 + 18 + 23 = 140 tests PASS. No production code changes in this checkpoint. Other assistant fixture repairs are in progress and are not certified green yet.

## Recovery pass — checkpoint 3
- Genuine production defect: deleting an unused branch failed its workspace foreign key. `finance_branches.update_record` now removes only its workspace metadata inside the existing atomic delete transaction. Budget/payee records also count as branch history, so those branches archive and retain all records instead of attempting deletion.
- Added `test_finance_branch_delete_recovery.py`: empty deletion, final-active-branch protection, budget/payee preservation, and audit-failure rollback of the account/workspace/branch deletion. No schema changes or production data access.
- Isolated verification: new recovery 4, Phase 1A 18, Phase 2A 25, Standalone boundary 4 — 51 tests PASS. The original branch file still has separate stale contracts to resolve; it is not marked green.

## Recovery pass — checkpoint 4: documents and bank review
- Genuine production defect: the bank-review amount input rendered raw minor units for IDR/JPY but submission parsed major units, multiplying an unchanged reviewed value by 100. The template now uses the existing decimal-safe `finance_input_money` filter for every currency. No monetary scale or parser behavior changed.
- New full HTTP round-trip regression in Phase 6B asserts 1234 minor units render as `12.34` and remain 1234 after correction for IDR, JPY and USD, with no ledger write.
- Stale fixtures: receipt/bank shorthand, CSV and model amounts now agree with two-decimal IDR storage; fractional amounts are supported, not held as old precision errors. Category state uses workspace overrides. FX rows remain held; unknown categories require explicit review rather than obsolete catch-all auto-posting. USD manual review retains its own currency and exact amount. Repeated confirmations/cancellation/review and tenant protections remain covered.
- Isolated files PASS: Phase 6A 53, Phase 6B 115, Phase 6C 103, bank sections 22, unified assistant 36. Nearby document upgrade 5, invoice PDF 1, PDF recovery 8, PDF routing 13 also PASS (356 tests total). Full unchanged requirements installed; no missing-dependency exclusions.

## Recovery pass — checkpoint 5: conversation contracts
- Stale fixtures: spoken IDR amounts and invoice/ledger fixtures now agree in minor units. Model patches use the current typed schema; bank extraction respects signed recognized currency. A reused document token stays rejected (422) with an unchanged database snapshot.
- Intentional current behavior: explicit all-branch POST requests are rejected with 403; GET resolves the default workspace. Native-currency summaries stay separate. Short ambiguous `BKA` requires exact account choice rather than automatic BCA selection. Bill drafts default to ONCE, ask category/date in current order, and receive explicit monthly/account review where intended. New-command clarification preserves the pending draft and creates no ledger/token. No model result authorizes a write without confirmation.
- UI/copy drift: Tagihan, Data pelanggan, Finance capabilities, and current confirmation wording. Capability summaries are not required to enumerate every command; issue/payment/void behavior is tested separately.
- Isolation correction: the raw-model negative validation cases exhausted the shared six-call rate limit before their positive case. Reset only that test's quota between independent cases; dedicated quota/security tests remain intact.
- Isolated PASS: inline 47, conversation agent 34, conversational boundaries 16, pending intents 26, semantic agent 44, semantic brain 36. Nearby assistant upgrade 20, live conversation 23, unified assistant 36 and Standalone boundary 4 also PASS (286 tests). Production assistant code unchanged.

## Recovery pass — checkpoint 6: workspace setup and category routes
- Genuine production defect: the first Finance GET attempted category synchronization before any branch existed, raising all-branches-read-only. Synchronization now runs only with a resolved branch. Existing first-use regression verifies 200, the start screen, empty accounts/categories and unchanged audit history; explicit all-scope POST and foreign scope remain rejected.
- Genuine production defect: budget rename/delete wrote the obsolete base-category state, so workspace names/active state never changed. Both actions now use `update_category_workspace_setting`, retaining expense-only selection, usage guards and audit behavior. The original budget create/rename/archive regression passes, including rejection of income-category renaming. Its containing home suite has unrelated workspace-move failures, documented below; it is not certified green.
- Stale branch fixtures now follow workspace category overrides, current nonzero-balance deactivation protection, default-workspace redirects, display-currency selection, nine default roots, and historical migration 0042's existing money conversion. Balanced-account deactivation, preserved transaction/history, repeat migration, cross-branch writes, last-active protections, and exact CSV minor-to-major equivalence remain asserted.
- Multi-business tests consume the verified by-currency reporting structure. IDR totals explicitly exclude USD; independent USD amounts are asserted. No combined cross-currency financial total was introduced.
- Isolated full-file PASS: branches 39, multi-business 13, Phase 1B 16, nearby Phase 1A 18, Phase 2A 25, branch-delete recovery 4 and Standalone boundary 4 (119 tests).

## Recovery pass — checkpoint 7: recurring, reports and current navigation
- Intentional current behavior: cron only counts due rules (`auto_post=disabled`); the test now checks that query, sanitized failure and an exact unchanged database snapshot. Actual payment requires an explicit payment account and date. The test asserts one posting, exact minor amount and actual date.
- Scheduled historical bills retain archived category identities, while new manual writes reject inactive categories. Added coverage for both sides. Invalid account and wrong-direction category references still produce no posting, remain due, and recover only after correction. Production recurring code unchanged.
- Stale report contracts: long-range reports now permit 240 months / 7305 days. Added accepted 13-/240-month coverage and retained rejection beyond the current limit. CSV asserts exact decimal major-unit export while retaining BOM, formula escaping, quoting, VOID history and source immutability. Collection reminders assert the exact minor-unit remainder.
- UI drift: reports offer their current PDF download route and cash-basis/native-currency notes; payment controls live in the selected bill day/list; transaction pagination and filters are checked against rendered records/context. Current sidebar and assistant entry points preserve branch parameters and no obsolete AI tools. Report-limit errors remain unavailable, never fake zeros. No UI redesign.
- Isolated full-file PASS: Phase 2B 25, Phase 3 20, Phase 5C 33, dashboard design 10 and UX/AI 18 (106 tests). Full home file separately executes 45 tests: 43 pass, two genuine workspace-move errors remain. No expected-failure or skip markers were added.
