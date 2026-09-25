# ASTRA PHASE 7 — FINANCE BRIDGE WITH STANDALONE FINANCE PRESERVED

Repo: IKUS2024/kilas-works-ai-admin
Branch: feature/kilas-core-v2

PRECONDITION:
- Phase 1–6 COMPLETE.
- Inspect current remote feature head, remote main and latest Phase 2–6 CI before edits.
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
9. docs/KILAS_V2_PHASE6_STATUS.md
10. current Finance service/routes/entitlements/invoice/customer/branch code
11. current git log/diff and CI

PRODUCT DECISION — NON-NEGOTIABLE:
Kilas Finance is ONE Finance engine with TWO commercial/use modes.

A. STANDALONE FINANCE
- A customer can buy/use Finance without AI Admin.
- Full existing Finance feature set remains available.
- No Inbox/Customer/Job dependency is required.
- Standalone Finance must not be degraded, hidden, or forced to connect to AI Admin.

B. CONNECTED FINANCE
- A customer with AI Admin + Finance uses the SAME Finance engine/data model.
- The optional Bridge links Core Customer/Job to Finance objects.
- Do NOT create a second ledger, second invoice engine, or duplicate Finance product code.
- Bridge availability is additive and entitlement-dependent.
- Finance remains authoritative for all financial truth.

Commercially, users may have:
- AI Admin only
- Finance only
- AI Admin + Finance
The third option unlocks bridge capabilities. It must not change the underlying Finance feature set.

PHASE 7 GOAL:
Implement a narrow, audited, explicit Finance Bridge so an owner can safely connect:
Core Business -> owned Finance Business/Branch
Core Customer -> Finance Customer
Core Job -> Finance Invoice

and then view linked invoice/payment/receivable status back from the Job/Customer side.

Also complete a FINANCE SELLABILITY GATE for the existing Standalone Finance product.
Phase 7 must leave Standalone Finance functionally sellable to normal small-business users even if they never buy AI Admin.

DO NOT REDESIGN FINANCE IN PHASE 7.
Finance UX/accountant-facing polish is Phase 9.
Do not alter accounting semantics.

FINANCE SELLABILITY GATE — REQUIRED:
Audit and verify the existing Finance product as a standalone paid product.

At minimum, a normal owner must be able to:
- start/use Finance without AI Admin;
- create/select a Finance business/workspace;
- use Business and Personal modes where currently supported;
- create/manage branches;
- create/manage financial accounts;
- record income and expenses;
- move money between supported accounts without treating transfers as operating income/expense;
- preserve opening-balance semantics;
- use categories/subcategories;
- create/edit/issue invoices through existing safe flows;
- record partial/full invoice payments through existing Finance flows;
- see receivables/outstanding/overdue status;
- use recurring bills/expenses;
- use budgets;
- use cash-flow/reporting views;
- use supported multi-currency accounts/conversion flows according to current product rules;
- export/report through existing supported outputs;
- use existing Finance AI/assistant capabilities under their current entitlement/safety gates;
- safely edit/archive/delete only where existing accounting rules permit;
- use the product on mobile without critical blockers;
- understand empty/error/read-only states without dead ends.

Phase 7 MAY fix critical functional blockers, broken navigation, validation gaps, entitlement mistakes,
or sellability defects discovered by these flows, provided the fix:
- preserves existing accounting semantics and customer data;
- does not introduce a broad visual redesign;
- has regression coverage;
- remains inside Finance's reviewed service boundaries.

Phase 7 must NOT invent missing professional-accounting semantics merely to satisfy this gate.
Features such as double-entry general ledger, chart of accounts, trial balance, P&L, balance sheet,
bank reconciliation, journal adjustments and period close belong to a separate Professional Readiness
assessment/workstream in Phase 9 if they are not already implemented.

Completion must distinguish:
1. "sellable operational Finance for normal business owners" from
2. "full accountant-grade accounting suite".
Do not claim the second unless the repo actually supports it.

FINANCE PROTECTED BOUNDARY:
Finance business logic is authoritative and protected.

Bridge code MUST call reviewed existing Finance service APIs.
Do NOT issue direct SQL writes into:
- finance_accounts
- finance_transactions
- finance_customers
- finance_invoices
- finance_invoice_items
- finance_invoice_payments
- finance_branches
- finance_categories
- finance_entitlements
or other protected Finance accounting tables.

Existing Finance service calls identified in current repo include safe boundaries such as:
- finance_service.create_customer(...)
- finance_service.create_finance_invoice(...)
- finance_service.issue_finance_invoice(...)
- finance_service.get_finance_invoice(...)
- finance_service.get_invoice_totals(...)
- finance_service.list_invoice_items(...)
- finance_service.list_invoice_payments(...)
- finance_service.record_invoice_payment(...)

Phase 7 should use only the minimum required reviewed subset.
Do not call record_invoice_payment from the Bridge unless a separately confirmed owner flow is explicitly implemented and fully justified. Preferred Phase 7 behavior: payments remain recorded through the existing Finance UI/service flow, while Bridge reads linked payment/outstanding state.

STANDALONE FINANCE REQUIREMENTS:
Regression-test that Finance-only users can still:
- enter Finance without AI Admin setup;
- create/use businesses and branches per existing entitlement behavior;
- use accounts, transactions, categories, invoices, payments, recurring/bills, budgets, reports and existing Finance AI features according to existing gates;
- remain completely usable with no Bridge mapping rows.

Do not add a Bridge prerequisite to existing Finance routes/services.

BRIDGE CONNECTION / MAPPING:
Do not assume an AI Admin business and a Finance business are automatically the same logical workspace.

Add an explicit owner-controlled connection:
- source Core/AI Admin business
- target Finance business
- one selected Finance branch for Bridge writes
- enabled/disabled state
- created/updated audit metadata

Rules:
- owner must have authorized access to both businesses;
- target Finance entitlement must permit the requested write;
- target branch must belong to target Finance business and be write-capable;
- connection is explicit, never inferred by business name;
- no silent business merge;
- changing/disabling mapping must not delete Finance data or historical links;
- one active default connection per Core business unless a broader requirement is proven necessary.

CORE CUSTOMER -> FINANCE CUSTOMER:
Do not auto-merge by name, unverified email, or phone.

Safe first version:
- if no link exists, owner explicitly confirms "Buat/Hubungkan Customer Finance";
- owner may select an existing Finance customer or create a new one through finance_service.create_customer;
- copying Core name/phone/email into a new Finance customer requires owner confirmation;
- persist a Core-side link record between Core Customer and Finance Customer;
- unique/idempotent operation key;
- foreign/ambiguous/mismatched links fail closed;
- Finance customer remains a Finance entity; Core customer remains the cross-channel CRM entity.

CORE JOB -> FINANCE INVOICE:
Add an explicit owner action from eligible Job detail:
"Buat Invoice di Finance"

Preferred safe flow:
1. validate AI Admin business + Job + Customer;
2. validate active Bridge mapping;
3. ensure/select linked Finance customer;
4. owner selects/enters:
   - invoice line items/description
   - quantity
   - unit price
   - currency
   - issue date
   - due date
   - optional notes
5. call finance_service.create_finance_invoice through the mapped Finance business/branch context;
6. create Core-side immutable link to the Finance invoice;
7. return authoritative Finance invoice number/status/totals.

Do NOT let the LLM invent:
- unit price
- invoice total
- due date
- paid state
- account
- category
- currency conversion
- payment confirmation

Phase 5/6 AI may say the Job is ready for owner action, but Phase 7 Bridge financial writes require explicit owner confirmation.

INVOICE ISSUE:
Safe default:
- Bridge creates a Finance DRAFT invoice.
- Owner reviews it.
- Issuing uses the existing Finance service and requires explicit owner confirmation.
If current Finance UX makes review inside Finance safer, link directly to the draft and issue there.
Do not auto-issue from a customer chat.

PAYMENT / RECEIVABLE VISIBILITY:
Bridge may read and show:
- Finance invoice number
- DRAFT / ISSUED / PARTIALLY_PAID / PAID / VOID
- total
- paid
- outstanding
- overdue
- linked Finance business/branch

Use Finance service reads, not duplicated calculations when a Finance service already owns the calculation.

Recording payment should remain in existing Finance flow in Phase 7 unless there is an explicit, owner-confirmed, fully tested Bridge payment form using finance_service.record_invoice_payment.
Never infer a payment from customer text or a claimed transfer.

JOB / CUSTOMER UI:
Minimal additive Bridge UI only:
- Customer detail: Finance link status / linked Finance customer
- Job detail: Finance card
  - Not connected
  - Finance connected
  - Create/open invoice
  - invoice status / outstanding
- direct link to existing Finance invoice/detail workspace
- Connection/settings page to choose Finance business + branch

Do not broadly redesign Finance shell, dashboard, navigation or reports now.

PACKAGE / ENTITLEMENTS:
- Finance-only remains independent.
- AI Admin-only sees Bridge unavailable, not broken Finance prompts.
- Connected Finance requires valid access to both sides.
- If Finance entitlement becomes read-only/expired:
  - existing links remain readable where existing Finance rules allow;
  - no new Bridge writes;
  - do not delete links/data.
- If AI Admin entitlement is inactive, Bridge actions fail closed.
- Finance emergency-disable must block Bridge writes.

BRIDGE DATA:
Prefer minimal additive Core-side tables, e.g.:
- kw_core_finance_connections
- kw_core_finance_customer_links
- kw_core_finance_invoice_links
- optional kw_core_finance_operations if needed for idempotency/retry audit

Do not add bridge metadata columns to protected Finance accounting tables unless absolutely unavoidable and explicitly justified.

Required safeguards:
- tenant/source business references
- target Finance business/branch references
- stable Core Customer/Job refs
- stable Finance object IDs
- unique link constraints
- idempotency operation key
- created/updated timestamps
- actor/system audit origin
- no destructive migration
- paired SQLite/PostgreSQL migration
- explicit installer only

TRANSACTION / FAILURE SEMANTICS:
Bridge operation must never claim success if Finance write failed.

For multi-step create/link:
- validate all references first;
- call authoritative Finance service;
- persist Bridge link atomically where transaction boundaries safely permit;
- if exact atomicity cannot span the current Finance service transaction plus Core link transaction, use a durable operation/reconciliation state and idempotent replay rather than guessing;
- retries must not create duplicate Finance customers/invoices;
- ambiguous partial failures must surface to owner, not silently repeat.

AUDIT:
Every Bridge write needs:
- owner actor
- Core business
- mapped Finance business/branch
- operation type
- Core Customer/Job reference
- resulting Finance object reference
- idempotency key
Do not log secrets or full sensitive payloads.

FINANCE AI:
Do not merge Kilas business-conversation AI and Finance AI into one unrestricted agent.
Existing Finance AI remains its own protected capability.
Bridge may provide links/context, not bypass Finance AI safety/confirmation rules.

ACCOUNTANT / PROFESSIONAL READINESS:
Phase 7 does NOT claim Kilas Finance is a full double-entry accounting suite.

Current Finance service describes itself as a tenant-scoped cash ledger and has substantial operational Finance features. Do not rename it "full accounting" without evidence.

For Phase 9, preserve a Finance Professional Readiness audit/polish track covering whether the product needs:
- chart of accounts
- double-entry journal/general ledger
- bank reconciliation
- journal adjustments
- trial balance
- profit & loss
- balance sheet
- period close/lock
- audit/export workflows for accountants
If these are missing, report them honestly and add them as bounded Finance work rather than faking them through UI.

No accounting-semantic redesign belongs in Phase 7.

REQUIRED TESTS:

STANDALONE
1. Finance-only user can use Finance with zero Bridge rows.
2. Existing Finance routes/features do not require AI Admin.
3. Existing Finance regression suite remains passing.
4. Finance entitlement/trial/read-only behavior unchanged.

CONNECTION
5. owner can connect own Core business to own Finance business/branch.
6. foreign Finance business rejected.
7. foreign branch rejected.
8. mapping by same name is never automatic.
9. disable/re-enable mapping preserves historical links.
10. duplicate connection operation is idempotent.

CUSTOMER LINK
11. explicit creation through finance_service.create_customer works.
12. existing Finance customer can be explicitly linked.
13. no name-only auto merge.
14. foreign Finance customer rejected.
15. duplicate/retry does not create second Finance customer/link.

INVOICE
16. owner can create one Finance draft from own Job.
17. mapped branch is used.
18. invoice items/currency/dates validated by existing Finance service.
19. retry does not create duplicate invoice.
20. foreign/mismatched Job/Customer rejected.
21. LLM/customer text cannot set price/payment state.
22. Bridge cannot auto-issue without explicit confirmation.
23. invoice read-back uses Finance-authoritative status/totals.
24. PARTIALLY_PAID / PAID state recorded in Finance is reflected back correctly.
25. Bridge does not duplicate payment calculations.

PROTECTED BOUNDARY
26. Bridge module contains no direct protected Finance INSERT/UPDATE/DELETE SQL.
27. no automatic payment recording.
28. no account/balance/category mutation.
29. no currency conversion write.
30. no Finance customer/invoice write without owner authorization.
31. Finance AI safety unaffected.
32. Phase 1–6 regressions pass.
33. PostgreSQL validation.
34. concurrency/idempotency validation.
35. mobile browser QA.
36. no WhatsApp send/cutover.
37. no production deployment.
38. git diff --check / exact changed-file review.

BROWSER QA — SYNTHETIC ONLY:
A. STANDALONE FINANCE
1. open Finance-only synthetic account/business
2. confirm Finance is usable without AI Admin/Bridge
3. confirm Bridge absence does not block Finance

B. CONNECTED FINANCE
1. open AI Admin Job
2. connect an owned synthetic Finance business/branch
3. explicitly link/create Finance customer
4. create draft invoice with owner-entered amount/items
5. open Finance draft
6. verify Job shows authoritative invoice status/totals
7. simulate/record payment using existing Finance test flow
8. verify Job read-back shows updated paid/outstanding state
9. second tenant cannot access mapping/invoice

C. EXPIRED/READ-ONLY
1. expire Finance entitlement in synthetic fixture
2. existing link remains visible
3. new Bridge write is blocked

CHECKPOINT / RESUME PROTOCOL:
Create docs/KILAS_V2_PHASE7_STATUS.md before substantial edits.

Milestones:
1. Finance boundary audit + standalone regression baseline
2. Bridge connection schema/service
3. Core Customer <-> Finance Customer link
4. Job <-> Finance Invoice draft link
5. authoritative invoice/read-back UI
6. security/idempotency/concurrency/protected-boundary tests
7. PostgreSQL + mobile browser QA
8. exact scope review / COMPLETE

After each coherent milestone:
- run smallest relevant tests
- commit passing work
- update Phase 7 status with:
  - milestone
  - commit SHA
  - exact files
  - tests/results
  - remaining work
  - blockers
  - exact next action

If interrupted:
- preserve coherent passing checkpoint
- do not redo completed work
- commit valid changes
- update status
- state RESUME FROM STATUS FILE

FINAL COMPLETION:
Only when every Phase 7 gate passes:
- mark docs/KILAS_V2_PHASE7_STATUS.md COMPLETE
- verify Phase 1–7 regressions
- verify Standalone Finance regression
- PostgreSQL validation
- mobile browser QA
- exact diff
- Finance accounting semantics unchanged
- production WhatsApp unchanged
- no production deployment
- STOP

Do NOT start Phase 8 automatically.
