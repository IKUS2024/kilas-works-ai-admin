# KILAS V2 EXECUTION ROADMAP

Source of truth:
- docs/KILAS_V2_MASTER.md
- docs/KILAS_V2_AUDIT.md

Execution rule:
Never ask one agent to build all Kilas V2 in one run. Complete, test, review, and commit one bounded phase at a time. This prevents partial refactors, scope drift, and Finance regressions.

Model guidance:
- Architecture/audit/docs: GPT-6 Astra Light
- Implementation/refactor: GPT-6 Astra Medium
- Difficult regression/debug only: GPT-6 Astra High
- Do not use High by default.

Phase order:
0. Audit — complete
1. Conversation Core + safe Simulator
2. Public Web Chat + live Inbox integration
3. Durable Customers / identity resolution
4. Generic Jobs engine with business-specific labels
5. Playbooks + safe AI Action Engine
6. Human handover + simple Automations
7. Finance Bridge only, using existing Finance services; preserve full Standalone Finance and add optional Connected Finance links
8. Official WhatsApp adapter into the tested Core
9. UX polish / onboarding simplification / package visibility / owner + admin dashboard refresh / Finance UX and accountant-readiness polish
10. Production hardening, browser QA, staged rollout

Business-first scope:
- Kilas AI is a business operator/assistant, not a general chatbot.
- Text-first customer operations come before media.
- AI image/video generation and creative studio features are deferred until the business workflow is stable.
- Media inputs are added later only when required by a concrete business workflow.

Finance policy:
Finance business logic, balances, invoices, payments, branches, multi-currency, reports and existing AI Finance behavior are protected. Integration is additive. UI/onboarding cleanup may happen only after regression coverage and must not change accounting semantics.

Definition of first sellable milestone:
Phase 2 complete and stable:
- public customer chat link
- AI conversation
- Inbox visibility
- human takeover
- tenant safety
- no Meta App Review dependency

Definition of strong commercial V2:
Phases 1-7 complete:
- chat -> customer -> job/order/booking/shipment/project -> quote/invoice bridge -> finance visibility

At the start of each phase:
1. inspect current remote main and feature branch
2. read master + audit + prior phase report
3. verify prior phase tests
4. create/continue a dedicated phase branch or worktree if needed
5. implement only that phase
6. run targeted regressions
7. inspect diff
8. stop and report

Never:
- rewrite framework
- reset DB
- merge AI Admin and Finance storage
- deploy broad refactor without browser QA
- expand scope because an agent notices unrelated cleanup
