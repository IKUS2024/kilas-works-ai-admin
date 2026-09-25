# ASTRA PHASE 5 — BUSINESS PLAYBOOKS + SAFE AI ACTION ENGINE

Repo: IKUS2024/kilas-works-ai-admin
Branch: feature/kilas-core-v2

PRECONDITION:
- Phase 1 COMPLETE.
- Phase 2 COMPLETE.
- Phase 3 COMPLETE.
- Phase 4 COMPLETE.
- Current Phase 2/3/4 CI on the feature branch must be inspected before edits.
- Do not assume an old SHA; inspect current remote feature head and remote main.

READ FIRST, COMPLETELY:
1. docs/KILAS_V2_MASTER.md
2. docs/KILAS_V2_AUDIT.md
3. docs/KILAS_V2_EXECUTION_ROADMAP.md
4. docs/KILAS_V2_PHASE1_STATUS.md
5. docs/KILAS_V2_PHASE2_STATUS.md
6. docs/KILAS_V2_PHASE3_STATUS.md
7. docs/KILAS_V2_PHASE4_STATUS.md
8. docs/ASTRA_PHASE4_JOBS.md
9. current git diff/log and current CI

PRODUCT DIRECTION:
Kilas AI is BUSINESS-FIRST and TEXT-FIRST.

Primary product flow after this phase:
Conversation -> Customer -> Job -> gather only missing information -> safe Job update

The AI is NOT a general-purpose chatbot.
It exists to help the connected business handle customers and operational work.

DO NOT ADD:
- AI image generation
- AI video generation
- creative studio
- photo/video editing
- general-purpose personal assistant features
- unrelated content creation
- Finance Bridge
- payment/accounting writes
- WhatsApp production cutover
- production deployment

PHASE 5 GOAL:
Connect the tested Conversation Core, durable Customers and deterministic Jobs engine through:
1. structured business understanding;
2. deterministic Business Playbooks;
3. a strict safe Action Engine;
4. natural business replies.

The AI should understand what the customer already said, persist only validated operational facts,
ask only for missing information, and create/update the correct Job through deterministic services.

ARCHITECTURE — NON-NEGOTIABLE SEPARATION:

A. UNDERSTANDING
LLM converts natural Indonesian / imperfect spelling / conversation context into a constrained
structured interpretation.

B. PLAYBOOK / STATE
Pure deterministic code decides:
- which playbook applies;
- known validated fields;
- required missing fields;
- whether enough information exists to advance state;
- which actions are allowed.

C. ACTION ENGINE
Deterministic code performs authoritative writes by calling existing safe Customer/Job services.
The LLM must never directly write SQL or fabricate action success.

D. RESPONSE
LLM or deterministic formatter turns the approved action result / missing-field request into concise,
natural customer-facing Indonesian.

Do not merge these responsibilities into one giant prompt/agent.

INITIAL PLAYBOOKS:
Implement only these few high-quality playbooks:

1. GENERIC_SERVICE
Examples: cleaning, repair, local service, simple service businesses.
Suggested fields:
- service
- need / description
- preferred_date_or_time if relevant
- location if relevant
Only require fields that are actually useful for a generic service request.

2. LOGISTICS
Fields:
- item
- weight
- volume_cbm OR dimensions where relevant
- origin
- destination
- transport_preference optional
Example:
"Mau kirim 20 kg baju dari Guangzhou ke Tangerang"
must retain:
item=baju
weight=20 kg
origin=Guangzhou
destination=Tangerang
and ask only for still-required information such as volume/dimensions if needed.

3. SIMPLE_ORDER
For restaurant/retail simple ordering.
Fields:
- items
- quantity
- notes/options
- fulfillment method if relevant
- delivery/pickup location when required
Do not invent catalog availability or price.

4. BOOKING_SERVICE
For salon/clinic/appointment-style service.
Fields:
- service
- preferred_date
- preferred_time or time_window
- customer note optional
Do not claim a slot is available unless a deterministic availability service actually says so.
Phase 5 may collect the requested time; it must not invent confirmed availability.

5. AGENCY_PROJECT
For agency/videography/project-based service.
Fields:
- requested_service
- project_need / brief
- preferred_date/deadline if stated
- location if relevant
- budget only if customer voluntarily states it
Do not invent quotation/price.

PLAYBOOK SELECTION:
Use deterministic business category/type mapping first.
Use LLM classification only when truly needed inside an allowed bounded set.
Never allow the model to invent a new playbook name.
Fallback = GENERIC_SERVICE.

KNOWN VS MISSING:
The Playbook engine must merge:
- existing Job structured_fields
- current customer message extraction
- safe relevant conversation context

Rules:
- previously known facts must not be asked again unless explicitly corrected/contradicted;
- a new explicit correction from the customer may replace an older value after validation;
- ambiguity must remain missing/uncertain instead of guessed;
- contradictions that cannot be safely resolved should trigger a concise clarification;
- missing fields are deterministic output from playbook rules.

STRUCTURED UNDERSTANDING CONTRACT:
Use a strict validated schema, conceptually:
- intent / workflow intent from a closed enum
- extracted fields from an allowlisted schema
- corrections / explicit replacements
- confidence / ambiguity flags where useful
- requested human help / unsupported intent flag
- no arbitrary executable action strings from the model

Reject malformed, oversized or unknown structured output.
One provider call per inbound message is preferred where practical.
No hidden retries that double usage without a bounded explicit policy.

SAFE ACTION ENGINE:
Allowed Phase 5 actions should be small and explicit, such as:
- ensure_customer_from_conversation (reuse Phase 3; no duplicate)
- create_job via existing Phase 4 service
- update_job validated fields
- transition_job only when deterministic playbook conditions permit
- request_missing_information as a response decision, not a DB write
- mark/record unsupported_or_needs_human state only if a minimal safe Core field/state exists

Do NOT add:
- Finance transaction/invoice/payment actions
- actual quotation pricing
- payment-state writes
- bank/account/balance changes
- WhatsApp sends
- arbitrary HTTP/tool calls
- shell/exec actions
- generic plugin execution

JOB CREATION RULE:
For a WEB conversation:
- resolve linked Customer server-side;
- if no active Job exists for that conversation/workflow, Action Engine may create one automatically
  using a stable idempotency/operation key derived server-side;
- if an active linked Job exists, update that same Job instead of duplicating;
- never accept a customer-supplied job_id to override tenant scope;
- multiple genuinely separate requests in one long conversation should NOT be split into multiple Jobs
  unless deterministically clear; otherwise continue the active Job and/or ask clarification.

JOB STATUS RULES:
Use Phase 4 lifecycle and transition service.
Suggested behavior:
- new request -> NEW
- required information missing -> NEEDS_INFORMATION
- all required non-price fields collected -> READY_FOR_QUOTE (when playbook uses quotation)
- simple order/booking may remain READY_FOR_QUOTE / appropriate existing safe state until later phases
  if no deterministic confirmation/price engine exists
- do not auto-approve, auto-complete, or claim payment

Do not bypass Phase 4 transition validation.

BUSINESS KNOWLEDGE:
Understanding/response may use existing business knowledge/context for:
- business name
- services/products described by owner
- policies
- operating information
- tone/context

But:
- knowledge is context, not authoritative proof of transactional state;
- never invent price, stock, availability, confirmed booking, payment, balance or delivery result;
- if price/availability is not deterministically known, say it needs confirmation or handover.

BUSINESS-ONLY CONVERSATION POLICY:
If customer asks unrelated general questions:
- do not become a general ChatGPT;
- gently redirect to what this business can help with.

If customer requests something unsafe/unsupported/complex:
- do not fabricate;
- use a concise clarification or human-help path.
Actual automation/handover orchestration beyond existing manual takeover belongs to Phase 6.

RESPONSE STYLE:
- concise natural Indonesian;
- do not expose internal words such as entity, classifier, state machine, JSON, LLM;
- avoid repeating facts customer already provided;
- ask one compact group of missing questions when practical;
- no long robotic checklists unless the workflow genuinely needs them;
- never claim an action succeeded until deterministic Action Engine returns success.

INBOX EXPERIENCE:
Enhance WEB Inbox minimally so the owner can see:
- linked Customer
- linked Job
- customer need / Job title
- known operational details
- missing required details
- current Job status
- AI/Human handling mode

Keep it concise and scannable.
Do not redesign the whole app shell.

JOB DETAIL:
Where useful, show:
- playbook/workflow type
- known fields
- missing fields
- source conversation
- customer
- current status
Do not expose raw LLM output or hidden prompts.

SCHEMA / PERSISTENCE:
Prefer reusing Phase 4 bounded structured_fields and operation records.
Only add an additive paired SQLite/PostgreSQL migration if truly needed for durable playbook/action state.

If additional state is necessary:
- minimal only;
- tenant-scoped;
- versioned/idempotent where writes can race/retry;
- no destructive migration;
- no Finance table changes;
- no legacy Order rewrite.

AI COST / CALL DISCIPLINE:
- avoid multiple model calls for one customer message unless strictly required;
- use deterministic playbook logic after extraction;
- reuse bounded conversation context;
- no media generation calls;
- no background model loops;
- no unbounded retries.

TESTS — REQUIRED:
At minimum cover:

UNDERSTANDING / PLAYBOOK
1. logistics sentence extracts item/weight/origin/destination and does not ask them again
2. logistics asks only remaining required field(s)
3. typo/imperfect Indonesian still maps into bounded allowed fields
4. prior known fields survive later messages
5. explicit correction updates a field safely
6. ambiguous value remains missing / triggers clarification
7. unknown model keys/actions rejected
8. malformed model output fails safe
9. unrelated general-chat request is redirected to business scope

ACTION ENGINE
10. first eligible WEB request creates one linked Job
11. retry/duplicate inbound does not create duplicate Job
12. later message updates existing linked Job
13. foreign Customer/conversation/Job references rejected
14. same apparent data in another business remains isolated
15. Job status follows deterministic missing/ready rules
16. impossible status jump cannot be forced by model output
17. model cannot directly create Finance writes
18. model cannot send WhatsApp
19. model text claiming [CREATE_JOB]/[PAYMENT] etc. has no capability by itself
20. provider failure does not partially commit a Job/action
21. concurrent duplicate processing remains idempotent
22. one bounded provider call per normal message (unless explicitly documented fallback)

PLAYBOOK COVERAGE
23. GENERIC_SERVICE
24. LOGISTICS
25. SIMPLE_ORDER
26. BOOKING_SERVICE
27. AGENCY_PROJECT
28. deterministic business-category selection + fallback

INTEGRATION
29. Customer -> Job link remains correct
30. WEB Inbox shows known/missing/status context
31. owner manual Job edits remain compatible
32. human takeover still suppresses AI writes/replies as Phase 2 specifies
33. Phase 1 tests pass
34. Phase 2 tests pass
35. Phase 3 tests pass
36. Phase 4 tests pass
37. no Finance writes
38. no production WhatsApp behavior changes
39. SQLite migration/state tests if migration added
40. PostgreSQL runtime validation
41. mobile browser QA

BROWSER QA — DISPOSABLE/SYNTHETIC ONLY:
At mobile width verify representative flows:

A. LOGISTICS
1. customer: "Mau kirim 20 kg baju dari Guangzhou ke Tangerang"
2. AI acknowledges known facts and asks only what is missing
3. owner Inbox shows Customer + Pengiriman + known/missing details
4. next customer reply supplies missing detail
5. same Job updates; no duplicate

B. SIMPLE SERVICE / BOOKING
1. customer states service + requested date/time
2. AI does not re-ask known values
3. Job/Booking is linked and visible

C. HUMAN MODE
1. owner takes over
2. customer sends another message
3. AI does not perform new automatic Job write while human takeover rules suppress AI
4. owner can still edit the Job manually

D. TENANT ISOLATION
second business cannot see or mutate Customer/Job/conversation.

CHECKPOINT / RESUME PROTOCOL:
Create docs/KILAS_V2_PHASE5_STATUS.md before substantial edits.

Milestones:
1. understanding contracts + playbook definitions
2. deterministic playbook state/missing-field engine
3. safe Action Engine on Phase 3/4 services
4. Public Web Chat integration
5. Inbox/Job context UI
6. security/idempotency/provider-failure/concurrency tests
7. PostgreSQL + mobile browser QA
8. exact scope review / COMPLETE

After each coherent milestone:
- run smallest relevant tests;
- commit passing work;
- update Phase 5 status with:
  - milestone
  - commit SHA
  - exact files
  - test results
  - remaining work
  - blockers
  - exact next action

If interrupted:
- keep a coherent checkpoint
- do not redo completed work
- commit passing changes
- update status
- state RESUME FROM STATUS FILE

FINAL COMPLETION:
Only when every Phase 5 gate passes:
- mark docs/KILAS_V2_PHASE5_STATUS.md COMPLETE
- verify Phase 1–5 regressions
- verify PostgreSQL
- verify mobile browser QA
- git diff --check
- exact changed-file review
- confirm Finance untouched
- confirm production WhatsApp untouched
- confirm no production deployment
- STOP

Do NOT start Phase 6 automatically.
