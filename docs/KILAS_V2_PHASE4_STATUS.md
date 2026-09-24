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

## Milestone 2 — deterministic service (PASS)
Added jobs.py and shared backend test cases + SQLite runner. Offline
`--only test_kilas_jobs_store.py`: PASS (15 tests), including threaded duplicate create,
competing version updates and same-key concurrent retry. Scope checked again inside service;
PostgreSQL tenant-row lock / SQLite immediate transaction serializes short writes. Operations
and audit commit atomically. Same key/different payload or actor conflicts; valid replay returns
current authoritative state without rewriting it. Forward-only transitions, no back-transitions.
Structured data accepts only documented operational keys in FIELD_LABELS, flat bounded text or
positive finite numeric quantity, <=8192 UTF-8 bytes; unknown keys rejected. No arbitrary secrets
metadata. UI will expose plain fields, not raw JSON. Service callers must authenticate actor;
owner routes will enforce existing membership/package/subscription/CSRF guards.
Prior schema checkpoint: `11672ea`. Next: owner routes/UI and linkage.

## Milestone 3 — owner routes/UI (PASS)
New job_routes.py, jobs/job_form/job_error templates, hub blueprint registration.
Offline `--only test_kilas_jobs_routes.py`: PASS (4 tests): real authenticated create/edit,
CSRF, foreign references/owners, forged payload, flag/package/subscription and Finance-session gates.
Normal Indonesian fields and errors; no JSON editor, AI action or external sends. Forward status
choices only; operation keys and optimistic versions travel with explicit owner forms.
Published prior milestones: planning `298f528`, schema `9c4dc62`, service `6cd48da`.
(Local pre-publication hashes above are historical; GitHub Git-data publishing preserves trees.)
Next: add Customer/WEB Inbox links and verify them with focused route tests.

## Milestone 4 — Customer / WEB Inbox linkage (PASS)
Customer detail and selected WEB conversation now expose gated manual creation and linked records.
Job detail links back to both; server resolves/validates conversation+customer, never trusts scope
payloads. AI product and WEB navigation use one category mapping helper. Default-off paths do not
query Jobs storage. Offline route suite PASS (5 tests), including create/open/back links and flag-off
preservation. Files: job_routes, customer_routes, public_chat/owner, Customer/WEB/product templates,
_jobs_panel template and route tests. Prior local owner checkpoint `5cd6c86`.
Next: complete protected-write/security cases; rerun prior phases; add PostgreSQL/mobile CI.

## Milestone 5 — security/concurrency (PASS locally)
SQLite Jobs: schema 1 + service 15 + owner routes 8 tests PASS. Strict quantity types hardened.
SQL authorizers on all connections allow only Jobs/operation/audit writes during owner flows;
Finance write APIs, WhatsApp send and model-call spies stay unused. WEB chat and simulator do
not create Jobs automatically. CSRF, payload tampering, escaped text, replay, stale update,
terminal transitions and separate tenant owners verified. Phase 1 PASS 30, Phase 2 PASS 27,
Phase 3 PASS 9 using the offline subprocess runner; completed implementations not redone.
Next: execute new disposable PostgreSQL and mobile CI harness; no runtime pass claimed yet.

## Milestone 6 — verification infrastructure checkpoint (runtime pending)
Added Phase 4 CI workflow, PostgreSQL runner reusing 15 service/concurrency cases plus legacy
preservation and parallel-tenant checks, mobile Jobs flow and conditional Jobs synthetic harness.
PostgreSQL runner requires an explicit flag AND loopback database named kilas_phase4.
Browser tests will create/edit from Customer, create/open from WEB conversation, filter/search,
reject foreign owner and compare existing Finance entry screenshots before/after Jobs activity.
Finance visual scope is the real unchanged entry page with a synthetic no-Finance-business account;
no accounting data or production Finance QA is implied. No Finance form is submitted.
Compile checks and git diff --check PASS. PostgreSQL/browser remain PENDING until CI evidence.
Exact next action: publish checkpoints, observe Phase 4 CI and resolve only actual failures.

## Milestone 6 progress / mobile review
CI `36014047791` at `6aa646f` has passed Phase 1–4 SQLite and PostgreSQL 0055/0056/0057,
including Jobs concurrency. Browser was still running when recorded; no browser pass yet.
Code review found fourth Inbox tab needs wrapping at mobile width; scoped Jobs-only wrapping
and linked-panel styles added, with long-title wrapping. Actual onboarding category placeholder
is free text (Coffee shop / Klinik / Influencer); added Coffee shop and Makanan/Minuman aliases.
Focused service 15 + route 8 tests PASS again. Next: final-head CI/browser results/screenshots.
Published owner/link/security/QA commits: `e2aadd2`, `e832f02`, `c361f0b`, `6aa646f`.
