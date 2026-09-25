# ASTRA PHASE 4 — GENERIC JOBS ENGINE

Repo: IKUS2024/kilas-works-ai-admin
Branch: feature/kilas-core-v2

PRECONDITION:
- Phase 1 COMPLETE.
- Phase 2 COMPLETE and current-head QA passing.
- Phase 3 COMPLETE and current-head QA passing.
- Current feature head before Phase 4: inspect; do not assume an old SHA.

READ FIRST, COMPLETELY:
1. docs/KILAS_V2_MASTER.md
2. docs/KILAS_V2_AUDIT.md
3. docs/KILAS_V2_EXECUTION_ROADMAP.md
4. docs/KILAS_V2_PHASE1_STATUS.md
5. docs/KILAS_V2_PHASE2_STATUS.md
6. docs/KILAS_V2_PHASE3_STATUS.md
7. current Phase 2/3 CI status
8. current git diff/log

PRODUCT DIRECTION:
Kilas is BUSINESS-FIRST and TEXT-FIRST.
This phase builds the operational work layer after Customer.

Core product flow after this phase:
Conversation -> Customer -> Job

"Job" is the internal generic concept only.
Owner-facing labels depend on business type:
- restaurant / retail -> Order / Pesanan
- salon / appointment service -> Booking
- logistics / freight -> Shipment / Pengiriman
- agency / videography -> Project
- workshop / repair -> Service Job
- unknown/generic service -> Pekerjaan

Do not add image/video generation, creative studio, general-purpose AI, or unrelated media features.

PHASE 4 GOAL:
Build a durable tenant-scoped Jobs engine and owner UI that can safely represent operational work linked to a Customer and optionally a WEB conversation.

This phase must produce a clean service/API boundary that Phase 5 Playbooks + AI Actions can call later.

IMPORTANT PHASE BOUNDARY:
- Do NOT let the LLM silently create/update Jobs yet.
- Do NOT implement Playbook extraction or missing-field questioning yet.
- Do NOT parse free-form chat into operational fields with AI yet.
- In Phase 4, Job creation/update must be deterministic and owner-authorized/manual or test-controlled.
- Phase 5 will connect AI understanding/actions to this engine.

DATA / DOMAIN REQUIREMENTS:
Create the smallest additive durable model required for:
- business/tenant id
- stable job id
- customer id
- optional conversation id
- internal job kind / presentation label
- title/summary
- lifecycle status
- bounded structured fields JSON for future business-specific data
- created_at / updated_at
- optional completed/cancelled timestamps if useful
- optimistic version or equivalent safe update fencing
- idempotency / operation key support where a write endpoint/service can be retried

Recommended common lifecycle:
NEW
NEEDS_INFORMATION
READY_FOR_QUOTE
QUOTED
APPROVED
IN_PROGRESS
COMPLETED
CANCELLED

Use these as internal semantics unless current repo constraints require equivalent names.
Do not create dozens of business-specific status tables.

BUSINESS TYPE / LABEL MAPPING:
Inspect the actual existing business type/category fields before implementing.
Create one deterministic mapping helper/service for UI labels.
Do not duplicate label logic across templates/routes.

Examples:
- Restaurant -> Pesanan
- Retail -> Pesanan
- Salon -> Booking
- Logistics -> Pengiriman
- Agency/Videography -> Project
- Workshop/Repair -> Service
- fallback -> Pekerjaan

The internal storage remains generic Job regardless of label.

CUSTOMER / CONVERSATION LINK RULES:
- Job belongs to exactly one business.
- Referenced Customer must belong to the same business.
- Referenced WEB conversation, when present, must belong to the same business and resolve to the same Customer.
- Foreign/mismatched references fail closed.
- Job id/request payload must never be trusted to override business scope.
- No cross-tenant linking.
- Existing Phase 3 customer identity semantics remain unchanged.

OWNER EXPERIENCE — MINIMAL, SELLABLE:
Add a Jobs area for AI Admin businesses:
- Jobs list, paginated if needed
- search
- status filter
- business-specific singular/plural label in UI
- create Job from a Customer detail page
- create Job from a WEB Inbox conversation/customer where safe
- Job detail page
- edit title/summary/status and bounded structured fields through explicit deterministic owner actions
- link back to Customer
- link back to source conversation when present
- show created/updated/latest status
- clear empty states
- mobile-friendly layout

Keep UI simple. Do not redesign the whole app shell in Phase 4.

CUSTOMER EXPERIENCE:
No new public form is required in Phase 4.
Public Web Chat behavior must continue unchanged.
A customer should not see internal Job terminology unless explicitly surfaced later.

SERVICE BOUNDARY:
Prefer a focused module, conceptually:
- client-hub/kilas_core/jobs.py
- optional small job schema/routes modules if needed

Required service capabilities should be deterministic, such as:
- create_job(...)
- get_job(...)
- list_jobs(...)
- update_job(...)
- transition_job(...)
- jobs_for_customer(...)
- maybe create_job_from_conversation(...) after strict server-side scope validation

Every write:
- validates tenant scope
- validates customer/conversation relation
- validates lifecycle transition
- is idempotent/retry-safe where an operation key is supplied
- records useful audit information
- does not call an LLM
- does not send WhatsApp
- does not write Finance

LIFECYCLE RULES:
Implement a small explicit transition map.
At minimum reject impossible/unsafe transitions.
Examples:
- NEW -> NEEDS_INFORMATION / READY_FOR_QUOTE / CANCELLED
- NEEDS_INFORMATION -> READY_FOR_QUOTE / CANCELLED
- READY_FOR_QUOTE -> QUOTED / CANCELLED
- QUOTED -> APPROVED / CANCELLED
- APPROVED -> IN_PROGRESS / CANCELLED
- IN_PROGRESS -> COMPLETED / CANCELLED

If product/manual editing needs a carefully justified back-transition, document it and test it.
Do not let arbitrary strings become statuses.

STRUCTURED FIELDS:
Phase 4 may store bounded JSON for known/missing operational data, but:
- no Playbook enforcement yet
- no AI extraction yet
- enforce size/type limits
- owner edits must be safe
- preserve unknown future-compatible keys only if explicitly allowed
- do not store secrets/tokens
- do not make schema business-specific

LEGACY KILAS ORDER:
Audit the current Kilas Order implementation before coding.
Reuse safe patterns/helpers where useful, especially request-code/idempotency concepts.
Do NOT rename/migrate/delete legacy Kilas Order tables or rows wholesale.
Do NOT force existing shopping/procurement rows into the new Jobs model.
Keep legacy data intact.

FINANCE BOUNDARY:
Finance remains protected.
Do NOT:
- create Finance transactions
- create Finance invoices
- record payments
- update balances/accounts
- write finance_customers
- add Finance Bridge
- change accounting logic
A Job may have future placeholder/reference fields only if they do not touch Finance.

WHATSAPP BOUNDARY:
- no production WhatsApp cutover
- no WhatsApp send
- no legacy phone-key writes
- current WhatsApp Inbox behavior remains unchanged

MIGRATIONS:
Use minimal additive SQLite/PostgreSQL migration pair only if required.
Recommended logical storage:
- core_jobs
- optional compact operation/event table only if needed for idempotency/audit/state safety

Safeguards:
- tenant composite foreign keys
- Customer same-tenant FK
- conversation linkage same-tenant
- indexes for business/status/customer/updated_at
- bounded JSON/text
- no destructive ALTER/DROP/backfill guessing
- do not replay unsafe legacy migration chain for focused tests

PACKAGE / AUTH:
Jobs belongs to AI Admin/business-operations experience.
Reuse existing auth/business membership/subscription gates.
Finance-only session/package must not expose Jobs.
Unauthorized/foreign job IDs return 404/fail closed.

REQUIRED TESTS:
At minimum cover:
1. owner creates Job for own Customer
2. foreign Customer rejected
3. same-business conversation+Customer link accepted
4. mismatched conversation/Customer rejected
5. foreign business/job access rejected
6. two tenants may have independent Jobs safely
7. idempotent create with same operation key does not duplicate
8. invalid status rejected
9. allowed status transition succeeds
10. invalid transition rejected
11. list/search/status filter tenant-scoped
12. Customer detail shows linked Jobs
13. WEB Inbox can open/create linked Job through owner-authorized action without AI
14. business-specific label mapping works with fallback
15. structured fields validation/size bounds
16. audit entry for owner write
17. Phase 1 regression remains passing
18. Phase 2 regression remains passing
19. Phase 3 Customers regression remains passing
20. no Finance writes
21. no WhatsApp send/legacy WhatsApp writes
22. additive SQLite migration idempotent in safe fixture
23. PostgreSQL migration/runtime validation
24. concurrent/idempotent create/update cannot duplicate or cross-link tenants

BROWSER / UX QA:
Use disposable/synthetic QA only.
At mobile width verify:
1. owner opens Customer detail
2. creates a Job
3. opens Job detail
4. changes an allowed status
5. sees Job linked back to Customer
6. opens linked WEB Inbox conversation
7. second business cannot access Job
8. Finance remains visually/behaviorally unaffected

CHECKPOINT / RESUME PROTOCOL:
Create docs/KILAS_V2_PHASE4_STATUS.md before substantial edits.

Milestones:
1. schema/contracts/storage
2. deterministic Jobs service + lifecycle
3. owner routes/UI
4. Customer/Inbox linkage
5. tests/security/concurrency
6. PostgreSQL + browser QA
7. exact scope review and COMPLETE status

After each coherent milestone:
- run smallest relevant tests
- commit passing work
- update docs/KILAS_V2_PHASE4_STATUS.md with:
  - milestone completed
  - current commit SHA
  - files changed
  - tests/results
  - remaining work
  - blockers
  - exact next action

If interrupted:
- keep a coherent passing checkpoint
- do not restart completed milestones
- commit valid work
- update status
- state RESUME FROM STATUS FILE

FINAL COMPLETION:
Only when all Phase 4 implementation/tests/QA pass:
- mark docs/KILAS_V2_PHASE4_STATUS.md COMPLETE
- verify Phase 1 tests
- verify Phase 2 tests
- verify Phase 3 tests
- verify Phase 4 tests
- PostgreSQL validation
- mobile browser QA
- git diff --check
- exact changed-file review
- Finance unchanged
- production WhatsApp unchanged
- no production deployment
- STOP

Do NOT start Phase 5 automatically.
