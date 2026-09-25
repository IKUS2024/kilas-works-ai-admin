# Kilas V2 Phase 4 status

Status: COMPLETE
Completed: 2026-09-24. Phase 4 only; STOP before Phase 5.
Branch: `feature/kilas-core-v2`.
Baseline: `65bfb99449fd7fa250e431b86d34b57dabe55869`.
Verified application/test head: `cb1db2f367f00366d6fc93e60229068d340bd744`.
Final status checkpoint is documentation-only; identify its SHA with
`git log -1 -- docs/KILAS_V2_PHASE4_STATUS.md`.
Remote main inspected: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c` (unchanged).

## Prerequisites and inspection

Read MASTER, AUDIT, EXECUTION_ROADMAP, Phase 1/2/3 status and ASTRA_PHASE4_JOBS completely.
Inspected current branch/log/diff and CI before coding. Baseline Phase 2 run `36011624161`
and Phase 3 run `36011624099` both SUCCESS, including PostgreSQL and mobile QA.
Historical Phase 2 pending notes are superseded by this observed evidence and the prior
product-owner confirmation. No completed Phase 1, 2 or 3 implementation was redone.

Inspected legacy order_service.py and the audit of migrations 0051–0053. Legacy requests
are user-scoped shopping/procurement records; unscoped mutation helpers are unsuitable
for tenant Jobs. Reused UUID, bounded JSON and operation-key concepts without importing
or modifying legacy Order code/data. No wholesale migration, rename, deletion or backfill.
Actual business category comes from business_profiles.category via repo.get_business_profile;
it is free text (wizard examples include Coffee shop and Klinik).

## Completed product and service

- Durable tenant-scoped Job linked to exactly one Core Customer and optionally its WEB conversation.
- Generic storage, one deterministic category-to-label mapping: Pesanan, Booking, Pengiriman,
  Project, Service, fallback Pekerjaan. Indonesian singular/plural labels remain the same noun.
- Owner list/search/status filter, 10-row pagination, create/detail/edit and empty states.
- Customer detail and selected WEB Inbox expose explicit manual creation and linked Jobs.
  Job detail links back to Customer and optional source conversation.
- Forward-only explicit lifecycle: NEW -> NEEDS_INFORMATION / READY_FOR_QUOTE -> QUOTED ->
  APPROVED -> IN_PROGRESS -> COMPLETED. Nonterminal states can cancel; no back-transitions.
  Current status can remain unchanged during a profile/detail edit; terminal status cannot reopen.
- create_job, get_job, list_jobs, update_job, transition_job and jobs_for_customer form the
  deterministic service boundary. Callers authenticate/authorize the actor; service independently
  validates tenant references, payload, lifecycle, operation key and optimistic version.
- Short transactions serialize writes with a PostgreSQL business-row lock / SQLite BEGIN IMMEDIATE.
  Operation record, Job and audit commit atomically. Retry with identical actor/payload returns
  current authoritative state without rewriting it; changed payload/key reuse or stale version is 409.
- Explicit structured keys only: details, quantity, unit, origin, destination, scheduled_at,
  reference, missing_information. No unknown metadata or secret/token keys. Text <=1000 chars
  per field, finite positive numeric quantity <=1e9, serialized JSON <=8192 UTF-8 bytes.
  Title <=160, summary <=2000; form body <=24 KiB before CSRF parsing. UI uses ordinary fields.
- No LLM Job writes, extraction, Playbooks or automatic state changes. WEB chat and simulator
  remain conversation-only until a later authorized phase.

## Schema and rollout boundary

Only additive paired migration 0057: kw_core_jobs, kw_core_job_operations and indexes.
An additive unique index on the existing WEB link triple supports a composite FK enforcing
business + conversation + customer equality at the database layer. Customer FK is tenant-scoped.
No destructive ALTER/DROP or guessed identity backfill. Existing Finance and Order tables untouched.
Explicit installer: `python -m kilas_core.job_schema --apply`, only against an authorized target
with 0055/0056 already installed. It is not registered in boot or the historical migration runner.

Production rollout was NOT performed. KILAS_JOBS_V2_ENABLED defaults off. Visibility/access also
requires Customers enabled, Core business allowlist, eligible AI Admin package, ACTIVE/GRACE
subscription, business membership and non-Finance session. Normal owner CSRF checks remain intact.
Disabling Jobs hides its routes/panels without querying Jobs tables or deleting any data.

## Passing checkpoints

| Milestone | Published commit |
| --- | --- |
| Scope/prerequisites before substantial edits | 298f528273321a41d4ebe3a93c55fe876ca8d9c3 |
| 1. Additive schema + isolated SQLite constraint test | 9c4dc62f82ca023d12b2468b7f045ddf3ed7d587 |
| 2. Deterministic service/lifecycle/retry + 15 tests | 6cd48da67fdd0ccd7c37e53eb9c4d1074f718000 |
| 3. Owner UI/routes + security checks | e2aadd2729ffbed1135929ba60e3118acdf7de7d |
| 4. Customer / WEB Inbox linkage | e832f0269f3a0db6b743efab36cc04e81529fcc8 |
| 5. Protected writes/manual-only/security | c361f0bfdf6b4a8800533db865c8f9c19a282fda |
| 6. PostgreSQL / mobile QA infrastructure | 6aa646f27ca6b5507e3fc54e584858d9676c2684 |
| Scoped mobile wrapping + actual category aliases | f8b8cd1930700b42313c0a4f474dcd23298afcfa |
| Body limit before CSRF parsing + HTTP 413 assertion | cb1db2f367f00366d6fc93e60229068d340bd744 |
| 7. Exact scope review and COMPLETE | This documentation-only checkpoint |

Each implementation milestone ran its smallest relevant SQLite tests and updated this status.
Git transport could fetch but push lacked credentials; authenticated GitHub Git-data API published
clean milestone trees to the feature branch without force or main changes. Local pre-publication
commit IDs were replaced by the exact published objects above.

## Final verification

[Phase 4 CI run 36014487448](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36014487448),
job `107683362616`, exact verified head above: SUCCESS including cleanup.
Independent Phase 3 workflow `36014487529` at the same head: SUCCESS.
Full Phase 2 workflow `36014487410` at the same head: SUCCESS, including the existing
Inbox/tenant regression steps on disposable SQLite, PostgreSQL and browser QA.

| Required gate | Result |
| --- | --- |
| Phase 1 contract/simulator regression | PASS, 30 tests locally; same suites in final CI |
| Phase 2 routes/store regression | PASS, 27 tests locally; same suites in final CI |
| Phase 3 Customers SQLite regression | PASS, 9 tests locally; same suite in final CI |
| Phase 4 SQLite migration/constraints | PASS, 1 test; additive installer twice, mismatched/foreign FK rejection, legacy row preserved |
| Phase 4 service/lifecycle/concurrency | PASS, 15 SQLite tests |
| Phase 4 actual owner routes/security | PASS, 8 SQLite tests |
| PostgreSQL 18 Phase 2 / 0055 | PASS, 4 runtime tests |
| PostgreSQL 18 Phase 3 / 0056 | PASS, 2 runtime tests |
| PostgreSQL 18 Phase 4 / 0057 | PASS, 17 runtime tests including parallel create/update/retry, tenant separation and legacy preservation |
| Existing public chat / Customers mobile QA | PASS, real Chromium at 390x844 |
| Jobs mobile QA | PASS, Customer -> create -> detail -> allowed status -> Customer link -> WEB create/open -> filter/search -> foreign 404 |
| Mobile layout | PASS, no horizontal overflow on create/detail/list/linked Inbox; screenshots inspected |
| Finance protection | PASS, no Finance writes; real Finance entry pixel parity and unchanged session redirect |
| WhatsApp / legacy Order / model isolation | PASS, write authorizers and negative API spies; no automatic chat/simulator Job creation |
| Exact scope / whitespace | PASS, 24 files listed below; git diff --check clean |

Commands used the isolated subprocess runner, with local dependency prefix
`PYTHONPATH=/tmp/kilas-phase1-deps` and CI `PYTHONPATH=client-hub`:
- `python scripts/run_offline_tests.py --only test_kilas_core`
- same runner with `test_public_chat_routes.py`, `test_public_chat_store.py`,
  `test_kilas_customers.py`, `test_kilas_jobs_schema.py`, `test_kilas_jobs_store.py`,
  `test_kilas_jobs_routes.py` (each separately).
- CI runs test_public_chat_postgres.py, test_kilas_customers_postgres.py and
  test_kilas_jobs_postgres.py with explicit QA flags; the Jobs runner additionally requires
  loopback host and database name kilas_phase4. Only minimal synthetic prerequisites and
  explicit 0055/0056/0057 were used; no historical migration replay for these focused tests.
- CI runs public_chat_browser_qa.py and kilas_jobs_browser_qa.py against the conditional
  disposable loopback harness. Compile checks also passed.

Browser artifact: `kilas-phase4-browser-qa`, ID `10814167048`, final run above.
Downloaded and inspected final updated-Job, linked-Inbox and filtered-list screenshots;
prior passing run `36014270170` screenshots also showed Customer links and Finance entry.
Final Finance before/after PNG bytes were independently compared and identical.
The initial run `36014047791` failed the strict mobile overflow assertion on Inbox tabs;
fix f8b8cd1 addressed that layout defect. No assertion was removed or weakened.

QA limitations are explicit: synthetic tenants only, stubbed model transport, real Flask/Core,
DB/auth/templates and real Chromium. Finance visual QA covers the unchanged entry page with
an account having no Finance businesses; no accounting form was submitted. No live AI-provider,
production Finance/WhatsApp, Render deployment or production-data certification is claimed.

## Exact changed files / protected boundary

Compared with baseline 65bfb99449fd7fa250e431b86d34b57dabe55869:

- `.github/workflows/kilas-v2-phase4-qa.yml`
- `client-hub/app.py`
- `client-hub/kilas_core/customer_routes.py`
- `client-hub/kilas_core/job_routes.py`
- `client-hub/kilas_core/job_schema.py`
- `client-hub/kilas_core/jobs.py`
- `client-hub/migrations/0057_kilas_core_jobs_postgres.sql`
- `client-hub/migrations/0057_kilas_core_jobs_sqlite.sql`
- `client-hub/public_chat/owner.py`
- `client-hub/templates/_jobs_panel.html`
- `client-hub/templates/customer_detail.html`
- `client-hub/templates/job_error.html`
- `client-hub/templates/job_form.html`
- `client-hub/templates/jobs.html`
- `client-hub/templates/product_dashboard.html`
- `client-hub/templates/web_inbox.html`
- `client-hub/tests/kilas_jobs_browser_qa.py`
- `client-hub/tests/kilas_jobs_cases.py`
- `client-hub/tests/public_chat_dev.py`
- `client-hub/tests/test_kilas_jobs_postgres.py`
- `client-hub/tests/test_kilas_jobs_routes.py`
- `client-hub/tests/test_kilas_jobs_schema.py`
- `client-hub/tests/test_kilas_jobs_store.py`
- `docs/KILAS_V2_PHASE4_STATUS.md`

Reviewed all production integration hunks: hub registration only; Customers adds a gated panel;
WEB owner adds scoped linked Jobs; product/WEB navigation adds gated labels; mobile wrapping is
Jobs-only. Prior phase tests/assertions are unchanged. Public WEB processing and WhatsApp Inbox
handlers are unchanged. Auth/security.py, db.py, root app.py, legacy Order services/tables and all
prior migrations are unchanged. All Finance code, assets, accounting logic and tables remain
untouched. Write-authorizer tests allow only Job/operation/audit/SQLite-sequence writes during
owner Job actions and assert Finance/WhatsApp/model entry points were never called.

No production database or customer data used. No production deployment or WhatsApp cutover.
No Jobs-from-LLM, Playbooks, Finance Bridge, image/video AI or creative studio.
No remaining Phase 4 implementation or required QA blocker. STOP. Do not start Phase 5.
