# Kilas V2 Phase 4 status

Status: CHECKPOINT — planning complete, implementation not yet started.
Branch: `feature/kilas-core-v2`.
Baseline: `65bfb99449fd7fa250e431b86d34b57dabe55869`.
Remote main inspected: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.

Read all seven requested documents completely. Current-head Phase 2 CI `36011624161`
and Phase 3 CI `36011624099` are SUCCESS, including regressions, PostgreSQL and mobile
browser gates. Prior phases are complete; historical Phase 2 pending notes are superseded.

## Inspection / decisions
Legacy `order_service.py` and migrations 0051–0053 retain user-scoped shopping data.
Reuse its bounded JSON/UUID/unique operation-key patterns, not unsafe unscoped mutators.
No legacy Order table, row, route or service will be changed.
Business category is `business_profiles.category` (via repo.get_business_profile).
One deterministic helper will map that category to labels and internal kinds.
New default-off Jobs gate; existing membership, AI package/subscription and Finance-session guards.
No automatic/LLM writes. Strict forward lifecycle; terminal jobs cannot transition further.

## Intended scope before edits
New: kilas_core/jobs.py, job_schema.py, job_routes.py; additive paired migration 0057;
Jobs templates; focused SQLite/PostgreSQL/browser tests and Phase 4 CI workflow.
Small integration changes: hub app registration, Customers route/detail, WEB owner/detail,
AI product navigation, synthetic QA harness only. This status file tracks milestones.
Existing Finance, WhatsApp runtime, legacy Order, prior migration files and prior test assertions
remain protected. No production database/deployment or live model/WhatsApp credentials.

## Remaining milestones
1. Schema/contracts/storage and focused tests.
2. Deterministic service/lifecycle, retry and version safety.
3. Owner routes/UI.
4. Customer/Inbox linkage.
5. Security/concurrency/protected-write tests and Phase 1–3 regressions.
6. Disposable PostgreSQL and real mobile Chromium QA.
7. Exact scope review and COMPLETE checkpoint, then STOP before Phase 5.

Next: implement additive schema and contracts with minimal synthetic SQLite validation.
No blockers. Status commit SHA: `git log -1 -- docs/KILAS_V2_PHASE4_STATUS.md`.

## Milestone 1 — schema (PASS)
Created paired additive 0057, explicit installer, and isolated SQLite schema test.
Triple tenant/conversation/customer FK, idempotent installer, rejected foreign/mismatched
links and preservation of synthetic legacy Order row verified. Offline
`--only test_kilas_jobs_schema.py`: PASS (1 test). No old migration chain executed.
Files: migrations/0057 pair, kilas_core/job_schema.py, tests/test_kilas_jobs_schema.py.
Prior checkpoint: `8feb318`. Next: deterministic service/lifecycle and retry tests.
