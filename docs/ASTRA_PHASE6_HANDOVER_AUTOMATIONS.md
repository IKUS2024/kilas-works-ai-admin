# ASTRA PHASE 6 — HUMAN HANDOVER + SIMPLE AUTOMATIONS + ATTENTION HOME

Repo: IKUS2024/kilas-works-ai-admin
Branch: feature/kilas-core-v2

PRECONDITION:
- Phase 1 COMPLETE
- Phase 2 COMPLETE
- Phase 3 COMPLETE
- Phase 4 COMPLETE
- Phase 5 COMPLETE
- Inspect current remote feature head, remote main, and latest Phase 2–5 CI first.
- Do not assume an old SHA.

READ FIRST, COMPLETELY:
1. docs/KILAS_V2_MASTER.md
2. docs/KILAS_V2_AUDIT.md
3. docs/KILAS_V2_EXECUTION_ROADMAP.md
4. docs/KILAS_V2_PHASE1_STATUS.md
5. docs/KILAS_V2_PHASE2_STATUS.md
6. docs/KILAS_V2_PHASE3_STATUS.md
7. docs/KILAS_V2_PHASE4_STATUS.md
8. docs/KILAS_V2_PHASE5_STATUS.md
9. docs/ASTRA_PHASE5_PLAYBOOKS_ACTIONS.md
10. current git log/diff and current CI

PRODUCT DIRECTION:
Kilas remains BUSINESS-FIRST and TEXT-FIRST.
No image/video generation.
No creative studio.
No general-purpose chatbot.
No Finance Bridge yet.
No WhatsApp production cutover.
No production deployment.

PHASE 6 GOAL:
Turn Kilas from a smart business chatbot into an operational assistant that:
1. knows when a human needs to take over;
2. keeps AI/Human ownership of a conversation explicit and race-safe;
3. creates a concise owner Attention queue;
4. runs a very small set of human-readable business automations;
5. never sends through unsupported/external channels.

The owner should be able to open Home and quickly see what needs attention.

TARGET OWNER EXPERIENCE:
Home should begin moving toward an attention dashboard, for example:

"3 hal perlu perhatian"
- 2 customer menunggu balasan manusia
- 1 Pengiriman siap dibuat quotation
- 1 Job selesai dan bisa diminta review

This is a functional Phase 6 addition only.
Do NOT do the full global UI/app-shell/admin-dashboard redesign here.
That belongs to Phase 9.

HUMAN HANDOVER — BUILD ON EXISTING PHASE 2:
Do not replace/rewrite the proven WEB takeover system.
Extend it safely.

Required behavior:
- customer explicitly asks for human -> system may mark conversation as HUMAN_ATTENTION_REQUIRED;
- Phase 5 understanding may request handover only through a closed validated signal;
- unsupported/uncertain/high-risk request may create a human-attention item;
- human takeover must suppress AI replies AND automatic Job writes/actions;
- manual owner reply continues to work;
- owner can return conversation to AI explicitly;
- stale inference/automation cannot write after takeover;
- return-to-AI cannot resurrect an old in-flight AI result;
- every mode change has an audit trail;
- no automatic WhatsApp send.

Do not let LLM output directly flip DB state.
A deterministic handover service/action must validate and execute it.

ATTENTION QUEUE:
Add the smallest durable or derived owner attention model required.

Attention items should be tenant scoped and link to the relevant:
- conversation
- Customer
- Job
where available.

Initial attention reasons may include:
- HUMAN_REPLY_NEEDED
- READY_FOR_QUOTE
- NEEDS_INFORMATION_STUCK
- FOLLOWUP_DUE
- REVIEW_REQUEST_DUE
- AUTOMATION_FAILED

Requirements:
- deterministic reason enum
- priority may be a small deterministic enum (e.g. NORMAL/HIGH), not LLM-scored
- open/resolved state
- idempotent event/source key so the same condition does not spam duplicates
- created/updated/resolved timestamps
- owner-authorized resolution
- foreign tenant access fails closed
- resolving an attention item must not silently mutate unrelated financial/business state

Where possible, derive rather than persist duplicate truth.
Persist only what is necessary for idempotency/history/actionability.

SIMPLE AUTOMATIONS — NOT A ZAPIER BUILDER:
Keep rules human-readable and few.

Initial allowed automations:

1. CUSTOMER_INACTIVE_FOLLOWUP
If a WEB conversation is AI_ACTIVE and the customer has not replied for a configured bounded interval:
- create one due automation instance;
- send/store at most one deterministic follow-up message per cooldown window;
- only in the existing WEB conversation;
- never WhatsApp/email/SMS;
- never while HUMAN_TAKEOVER;
- respect max-attempt and cooldown limits;
- duplicate scheduler/cron runs must be idempotent.

2. JOB_COMPLETED_REVIEW_REQUEST
When a Job becomes COMPLETED:
- create one due automation instance;
- if WEB conversation is still valid/AI_ACTIVE, append a concise deterministic review-request message;
- otherwise surface an owner attention item instead of pretending delivery happened;
- never use WhatsApp in Phase 6.

3. READY_FOR_QUOTE_OWNER_ATTENTION
When a Job reaches READY_FOR_QUOTE:
- create/refresh one owner attention item;
- do NOT create a quote, invoice, price, payment or Finance write.

4. NEW_CUSTOMER_ATTENTION (optional only if cleanly useful)
A new Customer may create one owner-visible attention/lead marker.
Do not build a full CRM segmentation/tag engine.

AUTOMATION CONFIG:
Use simple toggles + bounded settings per business only if needed, such as:
- enable/disable customer follow-up
- follow-up delay hours within a safe bounded range
- max follow-up attempts (small bounded integer)
- enable review request

Do not expose arbitrary conditions/actions.
Do not support custom code.
Do not support arbitrary URLs/webhooks.
Do not add third-party integrations.

SCHEDULER / EXECUTION:
Inspect existing cron/scheduler patterns before implementation.

Preferred rule:
- use a deterministic due-automation service with an explicit callable runner;
- use an idempotent claim/lease/operation key;
- safe to run repeatedly;
- no duplicate messages/actions;
- no long DB transaction around model/network calls;
- no model call is required for simple automation messages;
- if a cron route is added, secure it using an existing proven internal/cron pattern;
- do not deploy/schedule production cron in Phase 6.

WEB DELIVERY:
For Phase 6, automation delivery means adding a valid assistant/system business message to the existing WEB conversation store through a safe dedicated service path.

Do not:
- call WhatsApp send functions;
- call root bot send functions;
- fake phone identities;
- claim customer received a message if the durable WEB message write failed.

HUMAN MODE RULE:
If conversation is HUMAN_TAKEOVER:
- no AI inference action
- no AI Job update
- no automation-generated customer message
- owner can still manually edit Customer/Job and manually reply

Returning to AI is explicit owner action.

AUTOMATION / PLAYBOOK INTERACTION:
Phase 5 remains authoritative for interpretation and safe Job actions.
Phase 6 must not reimplement understanding/playbooks.

Phase 6 may consume deterministic events/state such as:
- Job READY_FOR_QUOTE
- Job COMPLETED
- conversation last customer activity
- conversation mode
- customer/job/conversation references

No LLM-based scheduling decisions.

HOME / OWNER DASHBOARD:
Add a compact Phase 6 attention section to the existing AI Admin owner Home where safe:
- count of open attention items
- top few items
- direct links to Inbox / Customer / Job
- clear reason/status
- "Lihat semua" if a dedicated attention list exists

Do not perform the full Phase 9 redesign now.

ADMIN DASHBOARD:
Do NOT broadly redesign the internal/admin dashboard in Phase 6.
Only expose minimal operational visibility if strictly necessary for QA/support.
The full owner + admin dashboard refresh is explicitly scheduled for Phase 9.

SECURITY / TENANCY:
- all attention/automation state scoped by business
- actor authorization for owner actions
- system-origin automated writes must use explicit SYSTEM/WEB_AUTOMATION audit identity, never impersonate an owner
- forged business/customer/job/conversation IDs rejected
- same-looking data across two businesses remains isolated
- Finance-only session/package cannot access AI Admin attention/automation pages
- subscription/package gates fail closed

FINANCE BOUNDARY:
STRICTLY NO:
- Finance customer writes
- Finance invoice creation
- payment recording
- balance/account changes
- receivables changes
- currency conversion
- Finance Bridge
- direct Finance SQL

READY_FOR_QUOTE only means owner attention in Phase 6.

WHATSAPP BOUNDARY:
STRICTLY NO:
- production WhatsApp cutover
- WhatsApp sends from new automation engine
- reuse of phone-shaped legacy state for WEB visitors
- changing root production bot behavior

Existing WhatsApp tenant follow-up code may be studied for cooldown/idempotency patterns, but must not be wired into WEB automations or modified unless required only for a regression guard. Prefer no modification.

MIGRATION:
Use minimal additive paired SQLite/PostgreSQL migration only if durable automation/attention state truly requires it.

Possible logical records:
- core_attention_items
- core_automations / core_automation_runs

Keep it smaller if one table can safely represent due/idempotent runs plus attention without mixing semantics.

Safeguards:
- tenant composite references
- unique source/event key for idempotency
- explicit status enum
- timestamps
- no destructive ALTER/DROP
- no Finance table changes
- no legacy data backfill guessing

REQUIRED TESTS:

HANDOVER
1. explicit customer request for human creates one attention/handover request
2. deterministic handover switches/surfaces correct WEB mode safely
3. duplicate handover request does not duplicate attention
4. HUMAN_TAKEOVER suppresses Phase 5 AI reply
5. HUMAN_TAKEOVER suppresses Phase 5 automatic Job write
6. HUMAN_TAKEOVER suppresses automation customer messages
7. owner manual reply still works
8. owner return-to-AI works
9. stale in-flight inference cannot append after takeover
10. stale automation cannot append after takeover

ATTENTION
11. READY_FOR_QUOTE creates one attention item
12. repeated state scans do not duplicate it
13. resolving attention is owner-authorized and tenant-scoped
14. foreign tenant cannot read/resolve
15. Home count/top items are tenant-scoped
16. links resolve to correct Inbox/Customer/Job

AUTOMATIONS
17. inactive WEB customer becomes due only after configured delay
18. follow-up writes once and respects cooldown/max attempts
19. repeated runner is idempotent
20. customer response cancels/resets pending inactivity behavior appropriately
21. Job COMPLETED review request occurs once
22. unavailable/human-mode conversation creates attention instead of false delivery
23. READY_FOR_QUOTE never creates price/quote/invoice
24. invalid automation config rejected
25. concurrent runners cannot double-send
26. failed durable message write does not mark automation delivered
27. automation runner does not call LLM for deterministic messages

SECURITY / REGRESSION
28. Phase 1 tests pass
29. Phase 2 tests pass
30. Phase 3 tests pass
31. Phase 4 tests pass
32. Phase 5 tests pass
33. PostgreSQL validation
34. mobile browser QA
35. no Finance writes
36. no WhatsApp sends/new root bot behavior
37. tenant isolation
38. subscription/package gates
39. git diff --check
40. exact changed-file review

BROWSER QA — SYNTHETIC ONLY:
At mobile width:

A. HUMAN ATTENTION
1. customer asks to speak to a human
2. owner Home shows attention
3. owner opens Inbox
4. takeover/manual reply works
5. customer sees human reply
6. return to AI works

B. READY FOR QUOTE
1. Phase 5 completes required Job data
2. Job becomes READY_FOR_QUOTE
3. owner Home shows one attention item
4. no invoice/price/payment is created

C. FOLLOW-UP
1. synthetic clock makes WEB conversation inactive
2. runner executes
3. one follow-up message appears
4. rerun produces no duplicate
5. HUMAN_TAKEOVER blocks follow-up

D. REVIEW REQUEST
1. owner completes Job
2. one review request appears in valid WEB conversation or owner attention fallback
3. rerun does not duplicate

E. TENANT ISOLATION
second business cannot access first business attention/automation state.

CHECKPOINT / RESUME PROTOCOL:
Create docs/KILAS_V2_PHASE6_STATUS.md before substantial edits.

Milestones:
1. inspect/reuse existing handover/follow-up/notification patterns + define contracts
2. attention state/service
3. automation rules/due runner
4. handover integration with Phase 5
5. Home attention UI
6. security/idempotency/concurrency/regression tests
7. PostgreSQL + mobile browser QA
8. exact scope review / COMPLETE

After each coherent milestone:
- run smallest relevant tests
- commit passing work
- update Phase 6 status with:
  - milestone
  - commit SHA
  - exact files
  - tests/results
  - remaining work
  - blockers
  - exact next action

If interrupted:
- keep a coherent checkpoint
- do not redo completed work
- commit valid changes
- update status
- state RESUME FROM STATUS FILE

FINAL COMPLETION:
Only when every Phase 6 gate passes:
- mark docs/KILAS_V2_PHASE6_STATUS.md COMPLETE
- verify Phase 1–6 regressions
- PostgreSQL validation
- mobile browser QA
- git diff --check
- exact changed-file review
- Finance untouched
- production WhatsApp untouched
- no production deployment
- STOP

Do NOT start Phase 7 automatically.
