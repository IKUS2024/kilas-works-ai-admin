# ASTRA PHASE 10 — PRODUCTION HARDENING, MERGE, RENDER DEPLOY, STAGED ROLLOUT

Status: execution specification
Branch: feature/kilas-core-v2
Prerequisite: Phase 1–9 COMPLETE with latest revalidation green.
User authorization: controlled production deploy is explicitly authorized in this phase, but ONLY after all pre-deploy gates below pass.

## Current verified baseline

At Phase 10 preparation:
- feature branch: feature/kilas-core-v2
- Phase 1–9 are certified COMPLETE
- latest Phase 2–9 workflows on the current feature head are green
- production main is still the pre-V2 baseline
- feature branch is cleanly ahead of main and not behind it
- PR #16 exists from feature/kilas-core-v2 -> main and is currently draft/mergeable
- production Render services track main with auto-deploy enabled:
  - kilas-works-client-hub — service srv-da7ti2psrm7s73dh9i2g — rootDir client-hub
  - kilas-works-ai-admin — service srv-da353nm7bikc7396r430 — rootDir repository root
- production Postgres:
  - kilas-works-db — dpg-da4ea1u417fc73fqv80g-a — PostgreSQL 18
- WhatsApp general-customer production activation remains external/permission-gated and must NOT be turned on merely because code is deployed.

Reinspect all of the above before taking action. Never trust stale SHA/config.

## Goal

Prove the complete Kilas V2 product works end-to-end, prepare the production database and environment safely,
merge the certified feature branch to main, allow Render production auto-deploy, verify real production,
and leave the system in a safe pilot-ready state.

This is NOT a feature expansion phase.

Do not add broad new modules, redesign the product again, or rewrite working architecture.

## 1. Read first

Read completely:
- docs/KILAS_V2_MASTER.md
- docs/KILAS_V2_AUDIT.md
- docs/KILAS_V2_EXECUTION_ROADMAP.md
- docs/KILAS_V2_PHASE7_STATUS.md
- docs/KILAS_V2_PHASE8_STATUS.md
- docs/KILAS_V2_PHASE9_STATUS.md
- docs/KILAS_V2_FINANCE_SELLABILITY.md
- docs/KILAS_V2_FINANCE_PROFESSIONAL_READINESS.md
- docs/ASTRA_PHASE10_PRODUCTION_ROLLOUT.md

Also inspect current remote feature head, remote main, PR #16, latest CI, Render production service config/deploy history, and production database readiness.

Create and maintain:
docs/KILAS_V2_PHASE10_STATUS.md

## 2. Freeze scope

Phase 10 is hardening/release only.

Allowed:
- fix proven release blockers
- improve error handling for proven failures
- fix broken production configuration/runbook
- fix migration/install ordering
- fix auth/session/CSRF/tenant/idempotency bugs
- fix mobile/desktop blockers
- fix production-only compatibility issues
- add release tests/health checks/rollback tooling

Not allowed:
- new product concepts
- creative AI/image/video
- new accounting architecture
- broad UI redesign
- new WhatsApp bypass
- destructive customer-data reset
- deleting historical Kilas Order schema/data

Any fix must be narrow, tested, and documented.

## 3. Final pre-production regression gate

Before touching production:
- verify current feature head is not behind main
- verify no unresolved merge conflict
- run latest Phase 1–9 regression gates
- run complete Finance baseline
- run Phase 8 WhatsApp adapter tests
- run Phase 9 browser/responsive QA
- run PostgreSQL runtime/migration tests
- git diff --check
- inspect exact feature-vs-main diff

No merge if any required gate is red.

## 4. Full end-to-end product QA

Exercise real application flows using isolated/disposable QA data.

### New AI Admin customer
signup/login
-> choose "Layani Customer"
-> create business
-> minimal setup
-> public Web Chat link
-> open as customer
-> customer sends realistic message
-> AI responds
-> Customer created/reused
-> Job/Pesanan/Booking/Shipment/Project created or updated
-> missing information only
-> owner sees Inbox
-> Human Takeover
-> manual owner reply
-> explicit return to AI
-> logout/login
-> state persists

### Finance-only customer
signup/login
-> choose "Kelola Keuangan"
-> no forced AI Admin setup
-> create/use Finance workspace
-> business/branch/account
-> opening balance
-> income/expense
-> invoice
-> partial payment
-> outstanding readback
-> recurring/budget/report/export
-> Finance AI safe action
-> logout/login
-> state persists

### Full customer
choose "Keduanya"
-> AI Admin + Finance navigation
-> customer conversation
-> Customer
-> Job
-> explicit Finance mapping
-> owner-reviewed Finance Customer
-> owner-reviewed DRAFT invoice
-> issue/payment through existing Finance flow only
-> authoritative payment/outstanding readback in Customer/Job
-> no duplicate Bridge objects on retry

### Admin/operator
verify operational queues and existing support flows:
- business review/support
- subscription/payment visibility
- service projects/content/talent
- WhatsApp readiness/support
- AI usage
- search/audit
- no active legacy Kilas Order product surfaces

### Browser coverage
- 360px
- 390px
- 430px
- tablet
- desktop
- keyboard/focus
- no horizontal overflow
- useful empty/loading/error/read-only states

## 5. Security and reliability release gate

Explicitly verify:
- tenant isolation
- cross-business access denial
- direct-object-reference denial
- session persistence and logout
- CSRF on writes
- duplicate form submit
- webhook retry/idempotency
- concurrent Customer/Job/Bridge operations
- stale version handling
- failed transaction rollback
- expired/suspended subscription behavior
- read-only Finance behavior
- unknown WhatsApp phone_number_id safe handling
- no tenant credential fallback
- Human Takeover suppresses AI
- customer claims cannot mark payment/invoice paid
- no secret/token leakage in logs/UI

## 6. Production schema plan

Audit every V2 schema dependency before deployment.

Explicit V2 installers currently include:
- 0055 Public Web Chat:
  python -m public_chat.schema --apply
- 0056 Core Customers:
  python -m kilas_core.customer_schema --apply
- 0057 Core Jobs:
  python -m kilas_core.job_schema --apply
- 0058 Operations:
  python -m kilas_core.operation_schema --apply
- 0059 Finance workspace corrections:
  review the existing registered migration path / production migration policy before execution
- 0060 Finance Bridge:
  python -m kilas_core.finance_bridge_schema --apply
- 0061 WhatsApp adapter transport metadata:
  python -m kilas_core.whatsapp_schema --apply

DO NOT blindly run these commands merely because they are listed here.

First:
1. inspect production schema/readiness using read-only queries;
2. identify which migrations/installers are already present;
3. verify every required installer is additive/idempotent on PostgreSQL 18;
4. verify ordering/dependencies;
5. verify production backup/restore capability or equivalent rollback protection;
6. test the exact production migration sequence against disposable PostgreSQL 18;
7. write the exact production schema plan to Phase 10 status.

Do NOT use db.init_schema or replay unrelated historical migrations as a shortcut.
Do NOT reset production DB.
Do NOT delete old Kilas Order tables/history.

Only apply missing production schema after the tested plan is complete.

## 7. Production feature flags / rollout gates

Audit authoritative code before changing Render env.

Known relevant gates include:
- KILAS_CORE_V2_ENABLED
- KILAS_CORE_V2_TEST_BUSINESS_IDS
- KILAS_PLAYBOOKS_V2_ENABLED
- KILAS_OPERATIONS_V2_ENABLED
- KILAS_WEB_CHAT_ENABLED
- KILAS_FINANCE_BRIDGE_ENABLED
- KILAS_WHATSAPP_CORE_ENABLED
- KILAS_WHATSAPP_CORE_CHANNELS

Do not invent values.

Important:
KILAS_CORE_V2_ENABLED alone is not broad enablement: current Core rollout also requires an explicit
server-controlled business-id allowlist. Preserve fail-closed semantics.

Before production:
- inspect how each flag is consumed
- choose a controlled pilot configuration
- document exact intended values without exposing secrets
- keep WhatsApp Core production selection OFF unless official Meta asset access is explicitly verified

Web Chat may be enabled for the authorized pilot/business set after production verification.

## 8. Pre-merge release checkpoint

Before merging PR #16:
- all required CI green
- exact release diff reviewed
- production schema plan verified
- rollback commit recorded (current production main SHA)
- Render service/deploy config verified
- required environment names present
- no secret values printed
- no unresolved external dependency required for Web Chat/AI Admin/Finance launch
- WhatsApp general activation explicitly excluded if Meta access is unverified

Update docs/KILAS_V2_PHASE10_STATUS.md with:
PRE-MERGE GATE PASS

If any condition fails, STOP before merge and document the exact blocker.

## 9. Merge to main

Only after PRE-MERGE GATE PASS.

Use PR #16 or the repository's normal safe merge mechanism.
Do not force-push main.
Do not rewrite published history.

After merge:
- record the exact new main SHA
- confirm both Render production services detect/deploy that main commit
- do not manually trigger duplicate deploys if auto-deploy already started

## 10. Render production deployment

Production services:
- kilas-works-client-hub
- kilas-works-ai-admin

Both currently auto-deploy main.

Monitor builds/deploys until live.
If one fails while the other succeeds:
- do not pretend release succeeded
- assess compatibility immediately
- use the documented rollback plan if required

Do not activate unverified WhatsApp tenant channels.

## 11. Production smoke + end-to-end verification

After both services are LIVE, verify production itself.

At minimum:
- production app loads
- login works
- existing user data still visible
- Home/nav package visibility
- AI-only path
- Finance-only path
- Full path
- Public Web Chat
- Web Chat -> Inbox
- Customer identity
- Job create/update
- Human Takeover
- manual Web reply
- Finance standalone read/write smoke using authorized safe test data only
- Finance Bridge with authorized safe test data only
- admin dashboard
- mobile production pages
- logout/login persistence
- no elevated 5xx/log errors
- no migration error loops
- no cross-tenant visibility

Never create destructive or misleading test transactions in a real customer's business.
Use an explicitly authorized internal/pilot business for production QA.

## 12. Rollback criteria

Rollback production if any critical issue appears, including:
- login/auth broken
- widespread 5xx
- tenant data leak
- incorrect financial balance/accounting behavior
- migration corruption/incompatibility
- duplicate financial writes
- Web Chat routes unusable for enabled pilot
- broken Inbox/Customer/Job core path
- production services on incompatible revisions

Rollback target must be the recorded pre-Phase-10 production main SHA unless a safer reviewed hotfix is clearly preferable.

After rollback, document:
- exact cause
- affected component
- data impact
- rollback SHA/deploy
- follow-up fix/tests

## 13. Staged rollout

After production smoke passes:
1. internal business
2. 2–3 pilot businesses
3. 5–10 businesses
4. broader rollout only after observed stability

Use explicit server-side allowlists/flags where available.
Do not globally open features merely because one pilot succeeds.

Track:
- errors
- response latency
- user dead ends
- duplicate events
- support cases
- Finance/Bridge issues
- Web Chat reliability

WhatsApp general rollout remains separate and requires official Meta authorization.

## 14. Completion

Phase 10 is COMPLETE only when:
- all pre-production gates passed
- required production schema is safely present
- feature branch is merged into main
- both Render production services are LIVE on the intended main SHA
- production smoke/end-to-end verification passes
- existing customer data is preserved
- Finance accounting semantics remain intact
- Web Chat/AI Admin/Finance are usable for the authorized rollout
- no unverified WhatsApp general activation occurred
- rollback path is documented
- pilot configuration is documented
- docs/KILAS_V2_PHASE10_STATUS.md is COMPLETE

If interrupted:
commit/checkpoint any safe non-production work,
update Phase 10 status,
and state:
RESUME FROM STATUS FILE

If production has already been changed, leave an exact operational status:
- current main SHA
- each Render service deploy SHA/status
- schema state
- feature flags state by name (never secret values)
- smoke-test state
- rollback readiness

Never leave production state ambiguous.
