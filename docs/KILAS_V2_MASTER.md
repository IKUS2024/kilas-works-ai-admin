# KILAS V2 MASTER

Status: Product/architecture source of truth
Branch: feature/kilas-core-v2
Base main SHA at creation: 05d50a8bdf14ede2b1ec588f1fe78619f7387f0c
Production: https://app.kilasworks.id

## 1. Product direction

Kilas is evolving from separate experiments into one simple operating system for small businesses.

Core promise:

**Chat masuk -> customer dipahami -> pekerjaan/order dibuat -> diproses -> dibayar -> uang tercatat.**

Kilas must feel simple for non-technical business owners. Complex AI/automation concepts stay behind the scenes.

The product family remains modular:

- **Kilas AI Admin**: Inbox, customer handling, customer records, jobs/orders/bookings/shipments/projects, handover, follow-up, automations.
- **Kilas Finance**: existing finance product, preserved as a protected module.
- **Kilas Content**: service business, not part of the core SaaS implementation in this branch.

WhatsApp remains important, but Kilas must be usable and sellable without Meta App Review.

## 2. Non-negotiable rule: Finance is protected

Kilas Finance already contains substantial production work. New Kilas Core work must NOT destructively redesign or rewrite it.

DO NOT:
- reset or migrate customer finance data destructively;
- create replacement Finance businesses for testing;
- change account balance behavior;
- change opening balance behavior;
- change income/expense accounting logic;
- change invoices, partial payments, receivables, recurring bills, budgets, categories, cash flow, reports, branch behavior, multi-currency behavior, or existing Finance AI semantics unless a narrow integration explicitly requires it;
- merge AI Admin and Finance storage into a new replacement schema;
- rename or remove existing Finance functionality merely to fit Kilas V2;
- redesign Finance screens as part of Kilas Core work.

Finance integration must happen through a narrow **Finance Bridge**.

Examples of acceptable future bridge events:
- Job -> create invoice request
- Invoice/payment status -> linked Job
- Confirmed payment -> existing Finance transaction service
- Shared customer reference where safe

Finance stays authoritative for financial truth.

## 3. Current technical reality

Current repository is an existing production application, not a greenfield rewrite.

Observed stack:
- Python
- Flask
- PostgreSQL via psycopg2
- Gunicorn
- server-side/backend code already contains Inbox, AI, routing, tenant and finance work
- root app.py is large/monolithic
- client-hub contains substantial Finance and onboarding modules
- existing tests cover AI, sales, inbox, tenants, payments, media and production hardening

Therefore:
- DO NOT rewrite the application into a different framework.
- Refactor incrementally.
- Reuse existing services before creating replacements.
- New modules should reduce coupling with app.py over time rather than expand the monolith.

## 4. Target architecture

Channels are adapters, not business logic.

```
WhatsApp Adapter ----\
Public Web Chat ------> Unified Conversation Core
Internal Simulator --/            |
                                 Customer Resolver
                                      |
                                AI Understanding
                                      |
                              Business Playbook
                                      |
                                Action Engine
                                      |
                    Customers <-> Jobs <-> Automations
                                      |
                                Finance Bridge
                                      |
                           Existing Kilas Finance
```

The same core flow must work regardless of whether a message comes from WhatsApp, public web chat or simulator.

## 5. Sellable before Meta App Review

Kilas must support a real public customer chat independent of WhatsApp.

Target customer experience:

Business owner receives a public URL, conceptually:
`chat.kilasworks.id/<business-slug>`

The owner can share it via:
- Instagram bio
- TikTok bio
- website
- QR code
- ads
- Google Business
- direct link

A real end customer can open it without creating an account and chat with the business AI.

This is NOT merely a developer simulator. It is a sellable live channel.

The owner dashboard must also provide:
- **Open as customer**
- **Copy link**
- later: **Create QR**

WhatsApp can later plug into the same Conversation Core after approval.

## 6. Core navigation

Do not expose every module to every customer.

### AI Admin-only
Home | Inbox | Customers | Jobs | More

### Finance-only
Home | Finance | More

### Full Kilas
Home | Inbox | Customers | Jobs | Finance | More

Automations, Insights and Settings can live under More unless desktop space allows them cleanly.

AI should not require a separate isolated assistant page. "Tanya Kilas" may be available contextually across the product.

## 7. New-user onboarding

The onboarding goal is that a non-technical owner understands Kilas within five minutes.

Step 1:
"What do you want Kilas to help with?"
- Layani customer otomatis
- Kelola keuangan
- Keduanya

Step 2: minimal business setup
- business name
- business type
- primary city/branch

Step 3: simple setup checklist
- Business created
- Add products/services
- Try AI Admin
- Connect WhatsApp (optional / can skip)

The most important first wow moment:
**Try as customer**

New accounts should not land on an empty analytics dashboard full of zeros.

## 8. Customers

A conversation should resolve to one customer identity when possible.

Requirements:
- auto-create customer from a new conversation;
- avoid duplicates across channels when reliable identity data matches;
- customer detail includes conversation history, jobs, invoices/payment references, notes and relevant profile data;
- do not expose technical concepts such as "entity extraction" to the user.

## 9. Jobs engine

"Job" is an internal generic concept. The customer-facing label changes by business type.

Examples:
- Restaurant -> Orders
- Salon -> Bookings
- Logistics -> Shipments
- Agency/Videography -> Projects
- Workshop -> Service Jobs
- Retail -> Orders

A Job is the structured operational work created from a customer conversation.

Common lifecycle can support:
New -> Needs Information -> Ready for Quote -> Quoted -> Approved -> In Progress -> Completed / Cancelled

Business-specific playbooks may customize labels and required fields.

Existing Kilas Order work should be reused where useful. Do not discard it solely because the product name changes.

## 10. Business Playbooks

Playbooks tell Kilas what information is required for a given business workflow.

Example: Logistics / Shipment
- item type
- photo if relevant
- weight
- volume / CBM
- origin
- destination
- transport preference if relevant

If the customer writes:
"Mau kirim 20 kg baju dari Guangzhou ke Tangerang"

Kilas should already extract:
- item = baju
- weight = 20 kg
- origin = Guangzhou
- destination = Tangerang

It must NOT ask those questions again.
It should ask only for missing required information, for example CBM / dimensions.

Initial playbooks should be few and high quality, not dozens:
- generic service business
- logistics
- restaurant / simple order
- booking-based service
- agency/project

## 11. AI architecture

Do not make one unrestricted chatbot responsible for everything.

Separate responsibilities:

### Understanding
Interpret natural Indonesian, typos and context.
Produce structured data.

### State / Playbook
Deterministically determine known data, missing data and next allowed step.

### Action Engine
Code executes business writes.

Initial action concepts:
- create_customer
- update_customer
- create_job
- update_job
- request_missing_information
- handover_to_human
- create_quote_request
- schedule_followup

### Response
AI turns the approved next action/result into natural customer-facing Indonesian.

For sensitive or financial writes, deterministic services remain authoritative.

The AI must not invent prices, payment state, balances or successful writes.

## 12. Inbox

Inbox remains the center of AI Admin.

A conversation view should eventually show concise structured context near the chat:
- Customer
- Customer need
- Known details
- Missing details
- Current operational status
- AI / Human handling state
- linked Job

The admin should not need to read an entire long conversation to understand what is happening.

Human handover remains first-class.

## 13. Home

Home is an attention dashboard, not an analytics dump.

Example:
"3 hal perlu perhatian"

- 2 conversations waiting for human response
- 1 shipment waiting for quote
- 2 overdue invoices (only if Finance active)

For a new customer, Home should primarily show setup progress and next action.

## 14. Automations

Keep automations human-readable.

Examples:
- Lead tidak membalas 24 jam -> follow-up
- Job selesai -> minta review
- Invoice overdue 3 hari -> send reminder (only through allowed/connected channel)
- New customer -> tag New Lead

Do not expose a complex Zapier-like workflow builder in the first release.

## 15. Public Web Chat / Simulator priority

First development milestone after audit:

1. Unified message input contract
2. Internal simulator
3. Public customer web chat using the SAME core
4. Inbox receives those conversations
5. Customer auto-create/match
6. Job creation and missing-info updates

The simulator is for QA.
The public web chat is a real sellable channel.

## 16. WhatsApp strategy

Do not bypass Meta review using unofficial browser automation or unsupported WhatsApp access.

WhatsApp is implemented as an adapter to the same core.

While approval is pending:
- public web chat works;
- simulator works;
- owner can continue using normal WhatsApp manually where necessary;
- product development does not stop.

When official WhatsApp is available, connect it to the same core instead of duplicating business logic.

## 17. Finance product modes + Bridge

Kilas Finance is ONE Finance engine with TWO commercial/use modes, not two duplicated accounting systems.

### Standalone Finance
For customers who only want Finance.
- Finance can be purchased and used without AI Admin.
- Full Finance capabilities remain available.
- No Customer/Job/Inbox dependency is required.
- Finance data, accounting semantics, entitlements and UI remain independently usable.

### Connected Finance
For customers who use AI Admin + Finance together.
- Uses the SAME Finance engine and the SAME Finance data model as Standalone Finance.
- Adds an optional Finance Bridge from Core Customer/Job into Finance.
- The bridge must not fork, copy or create a second Finance ledger.
- AI Admin can reference/link Finance objects only through reviewed Finance service APIs.
- Finance remains the authoritative source for financial truth.

Commercially, the user may buy Finance-only, AI Admin-only, or both. Buying both unlocks bridge features; it must not change the underlying Finance feature set or degrade Standalone Finance.

Only begin Finance Bridge implementation after Customers + Jobs + core message flow are stable.

Bridge principles:
- additive integration;
- explicit Customer/Job <-> Finance object links;
- explicit business/branch mapping;
- idempotent writes;
- audit trail;
- Finance remains authoritative;
- no silent auto-posting of uncertain AI interpretations;
- no automatic customer merge by name;
- no duplicate Finance data;
- no direct SQL from Kilas Core into protected Finance tables.

A first safe version requires explicit owner confirmation before creating Finance-side customers/invoices/transactions where appropriate. AI may prepare context, but deterministic Finance services execute authoritative writes.

Finance UX/accountant-facing polish belongs to the later UX/hardening phases. UI may be improved substantially while preserving accounting semantics and existing customer data.

## 18. UX language

Use normal Indonesian business language.

Prefer:
- Percakapan
- Customer
- Kebutuhan customer
- Status
- Pesanan / Booking / Shipment / Project
- Buat otomatisasi

Avoid customer-facing technical labels:
- entity extraction
- intent classifier
- workflow node
- pipeline entity
- LLM state machine

## 19. Business-first AI scope

Kilas V2 AI must prioritize business operations, not creative media generation.

Near-term AI priorities:
- understand customer intent in natural Indonesian;
- collect only missing business information;
- use business knowledge, products/services, pricing rules and policies;
- create/update customer and operational state through deterministic actions in later phases;
- support Order / Booking / Shipment / Project / Service workflows;
- summarize conversations and surface next actions;
- hand over to a human when uncertain or outside business scope.

Deferred until after the business operating system is stable:
- AI image generation;
- AI video generation;
- creative-content studio features;
- image/video editing workflows;
- rich media understanding unless a specific business workflow truly requires it.

Public Web Chat and early Kilas Core should be text-first. Attachments/media may be added later as bounded business inputs (for example a receipt, product photo or shipping-item photo), but media must not expand the product into a creative AI platform.

The AI should politely keep customer conversations relevant to the connected business. It should not behave as an unrestricted general-purpose chatbot.

## 20. Engineering guardrails

1. Inspect current remote main before every substantial task.
2. Never assume an old SHA.
3. Work on feature branches before production.
4. Preserve existing customer data.
5. Finance is a protected module.
6. No destructive DB migrations for Kilas V2.
7. Additive schema changes must be backward compatible.
8. WhatsApp is a channel adapter, not the core.
9. AI interprets; deterministic services execute authoritative writes.
10. All write actions need validation and useful auditability.
11. Reuse existing services before creating parallel replacements.
12. Add regression tests for existing behavior touched by refactors.
13. Test multi-tenant isolation.
14. Test duplicate/retry/idempotency paths.
15. Do not deploy just because code compiles.
16. Browser QA customer-side flows before production.
17. Do not create fake businesses or reset production data for QA.
18. Roll out new core features behind safe feature flags when appropriate.

## 21. Implementation sequence

### Phase 0 — Audit only
No production behavior changes.
Map existing:
- Inbox / WhatsApp path
- web/chat path if any
- customer storage
- Kilas Order/current order models
- AI routing
- tenant/business/branch architecture
- Finance boundaries
- auth
- deployment
- tests

Output a concrete reuse/refactor plan.

### Phase 1 — Conversation Core + Simulator
Normalize incoming messages.
Make simulator use the same processing path.

### Phase 2 — Public Web Chat
Real customer-facing public chat channel.
No login for end customer.
Tenant-safe business resolution.

### Phase 3 — Customers
Auto-create/match and customer detail.

### Phase 4 — Jobs
Generic backend job concept with business-specific presentation.

### Phase 5 — Playbooks + AI Actions
Structured extraction, missing-info logic, safe action execution.

### Phase 6 — Human Handover + Automations
Operational owner workflows.

### Phase 7 — Finance Bridge
Narrow integration only. Finance remains protected.

### Phase 8 — Official WhatsApp Adapter
Plug official channel into tested core after approval.

## 22. Release definition for first sellable Kilas Core

A business owner can:
1. create/setup a business;
2. receive a public customer chat URL;
3. open it as a customer;
4. have a real conversation with AI;
5. see the conversation in Inbox;
6. see Customer created/matched;
7. see a Job/Order/Booking/Shipment created or updated from the chat;
8. hand over to a human;
9. continue using existing Finance unchanged;
10. later connect official WhatsApp without replacing the core.

## 23. What NOT to do next

Do not:
- redesign Finance;
- rewrite the app in a new framework;
- build ten new product modules;
- build inventory/payroll/CRM as separate products now;
- make WhatsApp approval block development;
- create another AI assistant page just because AI exists;
- duplicate existing Inbox/order/customer logic without auditing first;
- deploy a broad refactor directly to main.

## 24. Immediate next task

Perform **Phase 0 Audit only** against the current real repository.

The audit must end with:
- current architecture map;
- reusable components;
- dangerous coupling;
- Finance protected boundary;
- proposed files/modules for Kilas Core;
- schema additions if truly necessary;
- migration risk;
- test plan;
- staged implementation plan.

Do not implement Kilas V2 during the audit task.
