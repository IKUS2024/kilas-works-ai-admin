# ASTRA PHASE 3 — DURABLE CUSTOMERS / CRM FOUNDATION

Repo: IKUS2024/kilas-works-ai-admin
Branch: feature/kilas-core-v2

PRECONDITION:
Phase 2 must be marked COMPLETE in docs/KILAS_V2_PHASE2_STATUS.md.
If Phase 2 is not COMPLETE, STOP. Do not implement Phase 3.

READ FIRST:
1. docs/KILAS_V2_MASTER.md
2. docs/KILAS_V2_AUDIT.md
3. docs/KILAS_V2_EXECUTION_ROADMAP.md
4. docs/KILAS_V2_PHASE1_STATUS.md
5. docs/KILAS_V2_PHASE2_STATUS.md

GOAL:
Add the durable Kilas Customers / CRM foundation so every real Public Web Chat conversation
belongs to a tenant-scoped customer record without relying on a phone-number-shaped legacy key.

This phase is BUSINESS-FIRST and TEXT-FIRST.

DO NOT:
- add image/video generation or creative AI
- add Jobs yet
- add Playbooks/actions yet
- add Finance Bridge
- alter Finance customer/accounting tables
- cut over WhatsApp production
- redesign the whole application
- deploy production automatically

PRODUCT BEHAVIOR:

1. FIRST WEB CONVERSATION -> CUSTOMER
When a new WEB visitor creates their first durable conversation/message:
- create or resolve exactly one tenant-scoped Kilas customer;
- link the WEB conversation to that customer;
- use a safe placeholder display label until the owner/customer supplies a real name;
- the same valid WEB visitor identity in the same business must resolve to the same customer;
- the same visitor token/hash in another business must NOT resolve to the same customer.

2. CUSTOMER IDENTITY MODEL
Create a generic identity model that can later support:
- WEB visitor identity
- WhatsApp phone identity
- verified email/phone identities
without converting anonymous WEB visitors into fake phone numbers.

Required rules:
- identity uniqueness is tenant-scoped;
- no name-only merge;
- no automatic merge from an unverified self-claimed email/phone;
- ambiguous identities fail closed;
- explicit merge/link behavior, if implemented, must be owner-authorized and audited;
- existing Finance customers are NOT the universal CRM and must not be reused as the Core customer table.

3. CUSTOMERS PAGE
Add a simple owner-facing Customers area for AI Admin businesses:
- list/search customers;
- customer display name;
- source/channel indicator;
- latest activity;
- conversation count;
- customer detail page with WEB conversation history/links;
- owner-editable basic profile/notes only if safe.

Use normal Indonesian UX language.
Do not expose technical identity hashes/tokens.

4. WEB INBOX INTEGRATION
WEB Inbox should show the linked customer display name when known instead of only "Pengunjung <id>".
Keep WEB channel badge visible.
Do not change existing WhatsApp Inbox behavior.

5. FUTURE-COMPATIBLE, NOT OVERBUILT
This is CRM foundation only.
Do not add:
- lead scoring
- sales pipeline stages beyond a minimal customer status if truly needed
- campaign broadcast
- automations
- customer segmentation engine
- Jobs
Those belong to later phases.

SCHEMA:
Use one minimal additive migration pair (SQLite/PostgreSQL) if required.
Prefer a shape like:
- core_customers
- core_customer_identities
- nullable customer reference on WEB conversation or a separate mapping
but choose the smallest safe design after inspecting current schema.

Safeguards:
- tenant composite uniqueness/foreign keys where possible;
- stable ids;
- created/updated timestamps;
- no destructive migration;
- no Finance-table changes;
- no data backfill that guesses identity.

MIGRATION:
- apply only the new Phase 3 additive migration in dedicated tests;
- never replay destructive historical migrations just to test this phase;
- preserve the explicit migration installer pattern used by Public Web Chat if appropriate.

TESTS:
Must cover at minimum:
- first WEB visitor creates customer;
- same WEB visitor in same business reuses customer;
- different WEB visitor creates different customer;
- same visitor-like identity across two businesses stays isolated;
- forged customer/business access rejected;
- owner A cannot read/edit owner B customer;
- placeholder -> owner-updated name works;
- no name-only dedupe;
- invalid/ambiguous identity fails closed;
- WEB Inbox displays customer name;
- Public Web Chat still works;
- human takeover/reply still works;
- Phase 1 and Phase 2 focused tests remain passing;
- no Finance writes;
- no WhatsApp send/cutover;
- PostgreSQL additive migration runtime validation;
- browser QA at mobile width for customer list/detail and linked Inbox where practical.

CHECKPOINT / RESUME:
Create docs/KILAS_V2_PHASE3_STATUS.md before substantial edits.
After each coherent milestone:
- run smallest relevant tests;
- commit passing work;
- update status with SHA/files/tests/remaining action.
If interrupted, save a coherent checkpoint and state RESUME FROM STATUS FILE.
Do not redo completed milestones.

LIKELY MODULE BOUNDARY:
Prefer new modules under:
- client-hub/kilas_core/customers.py
or a small dedicated customer package if persistence needs separation.
Do not place CRM logic into Finance.

COMPLETION:
- exact files changed documented;
- tests/results documented;
- Finance untouched;
- WhatsApp production untouched;
- no production deployment;
- docs/KILAS_V2_PHASE3_STATUS.md marked COMPLETE.

STOP after Phase 3.
Do not start Jobs/Phase 4 automatically.
