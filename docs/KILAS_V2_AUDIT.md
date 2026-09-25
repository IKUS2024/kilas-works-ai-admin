# Kilas V2 — Phase 0 architecture audit

Date: 2026-09-24  
Repository: `IKUS2024/kilas-works-ai-admin`  
Working branch: `feature/kilas-core-v2`  
Audited feature head: `3c032e15a8acf12b114b6196fff67d5f64a188c9`  
Remote main inspected: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`

Both `docs/KILAS_V2_MASTER.md` and `docs/ASTRA_PHASE0_LOW_QUOTA.md` were read first. The feature branch was two documentation-only commits ahead of main, with no application divergence. This is a static source audit, not runtime certification. No app was started, tests executed, database accessed, migrations run, UI changed, or deployment requested. Git clone authentication was unavailable; source files and the complete, non-truncated repository tree were read through GitHub at the pinned feature SHA. No tracked AGENTS.md was present.

**Recommendation:** retain Flask and existing services. Phase 1 should add a small, injected Conversation Core and route the authenticated simulator through it behind a default-off gate. Do not import the root bot application into the hub, convert Kilas Order wholesale into Jobs, or merge Finance and AI Admin businesses. Public customer chat, durable customer identity, Jobs and Finance Bridge are later phases.

## A. Current architecture map

### Runtime and inbound paths

| Surface | Current path and evidence | Implication |
|---|---|---|
| WhatsApp bot | Root `app.py:receive_webhook` handles POST `/webhook`; checks HMAC signature; iterates incoming messages under `_runtime_lock`; invokes `_webhook_body_impl`; clears thread-local channel credentials in finally. GET `/webhook` handles verification. | Transport validation, routing, model calls, state changes and outbound delivery currently share one large application. |
| Tenant resolution | `app.py:_resolve_tenant_or_unknown` distinguishes configured platform number, active tenant, and unknown. `client-hub/tenant_config_service.py` resolves WhatsApp phone-number IDs through tenant configuration. Subscription checks gate tenant AI runtime. | Unknown/failed tenant resolution must remain fail-closed; never substitute the platform tenant. |
| Tenant Inbox | `client-hub/routes_client.py:inbox_page`, takeover, return-AI, reply, template and media routes under `/business/<business_id>/inbox`. `inbox_service.py` and its identical hub copy read shared bot messages. | It is a WhatsApp-oriented inbox, not a channel-neutral conversation repository. |
| Platform Inbox | Root and hub `platform_inbox_service.py`; bot `/internal/platform-cs-reply`, template and media bridges. Platform state uses unprefixed phone keys. | “Platform” means Kilas's own conversations, not a generic abstraction for every channel. Keep it isolated from tenant conversations. |
| Owner simulator | Hub `routes_client.py:simulate_message` checks business access/session, reserves quota, reads/writes `simulation_messages`, calls `ai_onboarding.simulate_customer_reply`, marks onboarding progress. | Shares prompt behavior, but does not execute the WhatsApp processing path or populate live Inbox. |
| Public demo | Root `/demo`, `/demo/api`: in-memory sessions, separate prompt/model calls, demo limits. | Not tenant public chat. Although isolated from normal conversation storage, its DEMO_LEAD handling can send a WhatsApp lead notification; do not reuse it as a supposedly side-effect-free simulator. |
| Kilas Order web flow | Hub `routes_products.py`: `/products/order`, request intake/detail/search routes; authenticated users; `order_intake_ai`, `order_service`, `order_search`. WhatsApp handoff URL helpers also exist. | This is shopping/request workflow, not anonymous end-customer chat into a business inbox. |
| Client application | `client-hub/app.py:create_app` registers auth, client, products, Finance, admin, project, quotation, payment, talent and WhatsApp blueprints. | Separate Flask entrypoint from root bot; retain the separation. |

No business-slug public chat channel satisfying the master document was found in the inspected route surfaces. The existing demo and simulator must not be presented as that sellable channel.

### Identity, tenancy and branches

- `app.py:_ck` scopes tenant conversation state as `T<business_id>:<phone>`; the platform uses the plain phone. `messages(number, mode, role, content)`, `customer_profiles(number PRIMARY KEY, name)`, `customer_facts` and platform follow-up/appointment tables are initialized by root `init_db`. Tenant inbox queries require the exact prefix or scoped key.
- Conversation existence is currently inferred from message history. Names are upserted by scoped number, including AI name-tag processing. This is not a durable cross-channel customer ID. A name alone must never trigger a customer merge.
- Hub `repo.py` owns users, businesses, memberships, profiles, knowledge, configuration and simulation persistence. `security.require_business_access` checks membership, returns 404 for unauthorized business IDs, and allows KILAS_ADMIN access. Anonymous chat cannot reuse owner authentication as its identity model.
- `wa_takeover_service.py` owns tenant human/AI state; the platform has separate state. Phone normalization, takeover state and delivery windows are WhatsApp-specific.
- Finance customer records live separately in `finance_customers`. `finance_service.create_customer` has optional draft idempotency, not automatic unique-phone/email matching. Do not treat Finance customers as a ready-made universal CRM.
- AI Admin is principally business-scoped. Finance additionally has branch and BUSINESS/PERSONAL workspace ownership enforced by `finance_branches.py`. “All branches” is a read scope, not a write destination.
- New product setup intentionally separates Finance and AI Admin business records: `routes_products._product_businesses`, `_finance_business_claimed`, `_start_finance_trial_now`, and `routes_client.dashboard`. Legacy combined records remain usable. Future cross-product links require an explicit, authorized mapping; equal owner or business name is insufficient.

### AI and authoritative writes

`ai_brain_shared.py` provides common behavior/prompt policy. `context_engine.py` provides relevance selection, compact history, prompt sections and image preparation. Neither is an action engine. Sales stages, prompts, routing and many tag handlers still live inside root `app.py` (including `call_claude`, `call_tenant_owner_ai`, `_exact_customer_route`, price/handoff guards and meeting/payment tags). Tests named sales_engine/sales_brain do not imply separate production engine modules.

Current flow is mixed: deterministic routing/context -> model text/tags -> application parsing -> existing appointment/payment-review/handover services -> outbound send. `wa_project_bridge.py` parses owner commands/offers and resolves targets. `order_intake_ai.analyze` is a useful alternative pattern: strict JSON validation, known/missing information, bounded history and no business writes. Its shopping-specific schema is not a generic playbook.

### Onboarding, entitlements and navigation

`product_flow.py` allowlists product intent and creates business setup idempotently. `repo.py`, wizard routes and `ai_onboarding.py` handle profile/services/FAQ normalization and simulation. `feature_flags.py` is a paid-feature entitlement matrix (AI_ADMIN plus legacy plans; NONE has no AI features), not a V2 rollout switch. `subscription_service.py` gates AI Admin operation separately from `finance_entitlements.py` / `finance_subscription.py`.

Visibility is spread across `routes_client.dashboard`, `routes_products.py`, `templates/product_dashboard.html` and `templates/base.html`. Hub `app.py:_lock_customer_to_selected_finance` also redirects sessions whose active_product is Finance. Finance has its own template/static shell. Therefore hiding menu links alone does not grant or revoke access, and changing shared navigation can affect Finance.

Auth is session-based email/password with hashed passwords, CSRF and business/project guards in `security.py`; `routes_auth.py` also implements Google OAuth, with persisted identities through `repo.py`. Keep owner/admin sessions separate from future public visitor tokens.

## B. Reusable components

| Component | Reuse decision |
|---|---|
| `ai_brain_shared.py`, `context_engine.py` | Consume existing policy/context helpers. Do not edit global prompt semantics in Phase 1. |
| `ai_onboarding.simulate_customer_reply` | Initial injected reply provider for the core; preserve quota/history/onboarding behavior in simulator adapter. Shared prompt does not establish full WhatsApp parity. |
| `repo.py`, `security.py`, `tenant_config_service.py` | Reuse membership checks, business knowledge/configuration and audit methods. Separate knowledge eligibility from WhatsApp-connected/ACTIVE channel eligibility. |
| Inbox and takeover services | Preserve existing WhatsApp reads, media and safe manual-send behavior; later add channel-aware integration alongside them. Never invent a phone number for a web visitor. |
| `order_intake_ai.py` | Reuse strict validation and “ask only missing information” design. Do not rename the shopping schema into a universal job schema. |
| `order_service.py` | Reuse request-code generation, bounded JSON and unique user/draft-token retry pattern. Existing requests are user-scoped, not business/customer-scoped. |
| `order_search.py`, `order_catalog_service.py` | Keep optional shopping capabilities. Search validates candidate URLs against observed evidence; catalog serves curated Kilas products. Neither belongs on every generic job path. |
| `projects_repo.py`, `quotation_service.py`, `payment_service.py` | Reuse narrowly after scope review: existing project statuses, explicit quote approval, checkout and verification. These sell Kilas services; do not reinterpret them as every tenant's financial ledger. |
| Finance public services | Only a later bridge may call the existing service API under existing access/branch/entitlement constraints. |

Order tables `kilas_order_requests`, `kilas_order_candidates` and `kilas_order_catalog` come from migrations 0051–0053. Requests are tied to users; candidates to requests; catalog is global. Search/purchase/shipping statuses are domain-specific. Mutation helpers such as `update_request_status(request_id, ...)` do not independently take business scope, so exposing them directly as generic tenant actions would be unsafe.

Quote approval sets an existing project's price/status and enables checkout. `payment_service` uses commerce `invoices`/`payments`; this is distinct from `finance_invoices`/`finance_invoice_payments`. No automatic Order -> tenant Job -> Finance chain was established by the inspected code.

## C. Dangerous coupling / technical debt

1. **Bot import has consequences.** Root application initializes state/schema and contains external-send functions. Core must not import `app.py` or invoke the full webhook from simulator/web.
2. **Duplicate module names.** Both roots contain app, routes and repository/service names. Tree hashes show identical inbox_service/wa_inbox_shared copies but divergent platform_inbox_service, projects_repo and route copies. Root bot prepends client-hub to sys.path; hub AI appends root for shared prompts. Prefer a uniquely named package and explicit dependencies; no cleanup sweep now.
3. **Shared prompts, separate execution.** Simulator, demo, tenant bot, owner bot and shopping intake do not have one orchestrator. Prompt reuse alone does not unify safety, actions or persistence.
4. **Phone-shaped storage.** Tenant-prefix encoding and phone normalization cannot safely model anonymous visitor IDs or cross-channel matching. Avoid writing fake phone keys into legacy tables.
5. **Process-local state.** Conversational dictionaries and runtime locks constrain scaling. Root Gunicorn config enforces one synchronous worker/thread and warns against replicas. Order background search also has process-local coordination. Do not introduce concurrency by increasing workers.
6. **Retry semantics are not a durable job queue.** `is_duplicate_event` claims channel/event hashes in messages with a partial unique index; interrupted claims require reconciliation. Preserve this protection; do not advertise it as exactly-once action completion.
7. **Financial domains differ.** Commerce checkout, tenant payment-proof reviews and Finance accounting are separate workflows. An uploaded proof, AI interpretation or order status is not verified ledger payment.
8. **Shared product/session hooks protect Finance.** A universal-business/nav refactor would conflict with current explicit product separation. Defer it.
9. **Schema comments are not guarantees.** Hub migration runner replays a registered SQL list rather than only newly numbered files. Existing 0053 seeds/updates catalog and 0054 deletes named initial seed products. Do not run the whole migration chain merely to experiment.
10. **Operational unknowns.** Source comments about deployment are partly historical. This audit did not verify live Render settings, databases, applied migrations, DNS, credentials or production behavior.

## D. Finance protected boundary

Protected ownership: `client-hub/routes_finance.py`; all `client-hub/finance_*.py`; Finance tables, migrations, templates and static files. Important services include finance_service, finance_branches, finance_entitlements, finance_subscription, finance_reports, finance_bank_service and the assistant/conversation modules. Finance persistence is largely SQL inside services through shared `db.py`; there is no need for a replacement repository layer.

The narrow future bridge may use:
- `finance_service.create_customer` only for explicitly approved Finance customer creation/linking.
- `create_finance_invoice` and `issue_finance_invoice` for confirmed invoice requests.
- `get_finance_invoice` / `get_invoice_totals` for authoritative linked status.
- `record_invoice_payment` for confirmed invoice payments. It validates outstanding amount/currency, handles idempotency, creates the associated ledger entry and updates invoice state. Do not also call create_transaction for the same payment.
- `create_transaction` only for a separate, validated non-invoice posting, with its actual supported source/idempotency rules reviewed first.

A future bridge must carry actor, mapped Finance business, one authorized branch, customer/invoice reference, currency/minor units and stable operation key. Retain current service transactions, audit and entitlement checks. No direct SQL into Finance from Core; no automatic posting from uncertain extraction; no opening-balance reinterpretation. Bridge metadata belongs outside protected Finance tables. Phase 1 must import/call none of these write APIs.

## E. Proposed Kilas Core module boundaries

All paths below are proposals, not existing implementation.

| Proposed boundary | Responsibility |
|---|---|
| `client-hub/kilas_core/contracts.py` | Validated inbound envelope/result. Business, channel, conversation, external message ID, actor type, text/media references and time; no Flask request or credentials inside. |
| `client-hub/kilas_core/service.py` | One processing entrypoint with injected knowledge, history, understanding, state/action and response dependencies. No channel send or SQL embedded. |
| `client-hub/kilas_core/adapters/simulator.py` | Authenticated simulator normalization and existing history/quota integration; no live operational writes. |
| `client-hub/kilas_core/adapters/web.py` (Phase 2) | Server-resolved public business/visitor identity, abuse limits and web delivery. |
| `client-hub/kilas_core/customers.py` (Phase 3) | Tenant-scoped identity resolution; verified matching and explicit ambiguous-link handling. |
| `client-hub/kilas_core/jobs.py`, `playbooks.py`, `actions.py` (Phases 4–5) | Operational state, required information, allowed transitions, validated/idempotent writes. |
| `client-hub/kilas_core/finance_bridge.py` (Phase 7) | Explicit authorized mapping and narrow calls to existing Finance services. |
| `client-hub/kilas_core/adapters/whatsapp.py` (Phase 8) | Signature/channel identity, media and official WhatsApp delivery; preserve existing runtime safety until tested cutover. |

The same core should support simulator and later web adapters through dependency injection. Simulator actions remain non-live even when later adapters support writes. Structured understanding, deterministic state and action execution must remain separate responsibilities. Do not introduce a new agent framework.

## F. Minimal additive schema proposal

**Phase 0: none. Phase 1: no schema migration required.** Reuse existing simulation_messages/history and quota reservation for the bounded simulator milestone. Pure contract/state behavior can be tested with in-memory doubles. Do not claim durable operational replay or live Inbox integration at this stage.

Later, only when the consuming phase is implemented:

| Phase | Minimal proposed storage | Required safeguards |
|---|---|---|
| 2 | Public channel configuration, conversations/messages, visitor sessions, inbound processing records (e.g. core_channels/core_conversations/core_messages/core_visitors/core_events). | Server-controlled slug -> business mapping; opaque expiring visitor credentials stored hashed; tenant/conversation binding; unique channel + external event per tenant; processing/result status and recoverable retries. Reuse existing audit_log instead of inventing another audit subsystem. |
| 3 | core_customers and core_customer_identities; optional customer link on new conversation rows. | Tenant-scoped identity uniqueness; verified channel identifiers; no automatic name-only, unverified-email or self-claimed-phone merge. Explicit conflict handling. |
| 4–5 | core_jobs and durable action/state records referencing conversations/customers. | Tenant-composite foreign keys, versioned transitions and idempotency keys; known/missing fields can initially be bounded JSON. Keep legacy Order rows intact. |
| 7 | core_finance_links / bridge operation records only if existing references are insufficient. | Explicit AI Admin business -> Finance business/branch mapping, authorization on both sides, stable operation key and referenced financial object. No silent business merge. |

These are logical proposals, not SQL or a commitment to six new tables at once; combine records where transaction/retry semantics permit. Later migrations must be paired for PostgreSQL and SQLite and reviewed against the actual current head.

Migration risk: low for this documentation-only audit; medium for later additive Core tables because tenant constraints, concurrency and legacy DB sharing need verification; high for changing legacy phone keys, replaying data-changing migrations or relinking Finance businesses. Use additive rollout, separate staging data and reversible flags. Never delete customer data for rollback.

## G. Exact files likely to change in Phase 1

Keep the initial allowlist small:

**Existing file**
- `client-hub/routes_client.py`: only simulator handler integration, preserving current auth, CSRF handling, quota, history and onboarding response contract.

**New files**
- `client-hub/kilas_core/__init__.py`
- `client-hub/kilas_core/contracts.py`
- `client-hub/kilas_core/service.py`
- `client-hub/kilas_core/flags.py`
- `client-hub/kilas_core/adapters/__init__.py`
- `client-hub/kilas_core/adapters/simulator.py`
- `client-hub/tests/test_kilas_core_contract.py`
- `client-hub/tests/test_kilas_core_simulator.py`

Consume existing ai_onboarding/repo/context helpers without modifying them initially. No root app change, UI/template change, new route registration or migration is needed for this bounded Phase 1. If extraction proves to require broader changes, revise the allowlist explicitly before implementation; do not expand it opportunistically.

## H. Exact files that should NOT be touched

For **this audit**, every repository file except `docs/KILAS_V2_AUDIT.md` is protected.

For **Phase 1**, everything outside section G remains unchanged, specifically:
- `app.py`, `gunicorn.conf.py`, `client-hub/gunicorn.conf.py`, `client-hub/app.py`.
- `client-hub/routes_finance.py`, `client-hub/finance_service.py`, `client-hub/finance_branches.py`, `client-hub/finance_entitlements.py`, `client-hub/finance_subscription.py`, and every other `client-hub/finance_*.py`.
- All `client-hub/migrations/` files, `client-hub/db.py`, `client-hub/scripts/run_migrations.py`, `scripts/production_runtime_claims.sql`.
- `client-hub/templates/base.html`, `client-hub/templates/product_dashboard.html`, every Finance template/static asset, and all other UI assets.
- `client-hub/routes_products.py`, `client-hub/product_flow.py`, `client-hub/routes_auth.py`, `client-hub/security.py`, `client-hub/feature_flags.py`.
- Both existing copies of `inbox_service.py`, `platform_inbox_service.py`, `wa_inbox_shared.py`, and existing Order/project/quotation/payment services.
- Existing Finance and legacy regression tests: run them when appropriate, do not weaken expectations.

## I. Regression test plan

No tests were executed in Phase 0; no pass/fail claims are made. The source/tree was inspected to select tests, not to certify existing coverage exhaustively.

| Area | Existing evidence / later gate |
|---|---|
| Simulator/prompt parity | `test_unified_ai_brain_v2.py`, `test_demo_cost_limits.py`, `client-hub/tests/test_ai_onboarding_features_enabled_fix.py`. Add contract tests plus flag-off legacy response/history/quota parity and flag-on simulator tests. |
| Inbox/handover/media | `client-hub/tests/test_inbox_unification.py`, `test_inbox_media_webhook.py`, `client-hub/tests/test_inbox_media.py`, `test_platform_takeover.py`. Existing inbox tests explicitly cover same phone across tenants and takeover suppression. |
| Tenant isolation/retry | `test_multi_tenant_runtime_safety.py`, `test_tenant_owner_media_and_isolation.py`, `test_tenant_persistence_and_payment_review.py`. New Core cases: forged business/conversation, absent actor, duplicate event and failure boundaries. |
| Sales/owner behavior | `test_sales_engine.py`, `test_sales_brain_v2.py`, `test_owner_intent_target_resolution.py`, `test_price_transport_uncertainty_guardrails.py`. Preserve current production behavior. |
| Commerce/payment | `client-hub/tests/test_payment_checkout_reliability.py`, `test_payment_verification_strengthening.py`, `test_wa_checkout.py` within client-hub/tests. Confirm no search/send/checkout/payment APIs called by simulator. |
| Product/auth | `client-hub/tests/test_final_product_flow.py`, `test_production_foundation.py` within client-hub/tests; preserve Finance-only session lock and unauthorized business 404 behavior. |
| Protected Finance | `client-hub/tests/test_finance_branches.py`, `test_finance_multibusiness.py`, `test_finance_fx_precision.py`, `test_finance_invoice_editor.py`, `test_finance_conversational_boundaries.py` within client-hub/tests. Cover balances/opening balances, partial payments, all-branch read-only and tenant/workspace isolation. |

No dedicated Order-named test file was found in the tracked tree; do not assume shopping retry/status coverage is complete. Add focused Order compatibility tests only when a later phase touches that code.

Use `scripts/run_offline_tests.py --only <substring>` and the subprocess runner in `run_all_tests.py`; it deliberately isolates duplicate module names and self-running test files. Do not replace it with broad in-process pytest discovery. Review bootstrap/env isolation first, use temporary SQLite or disposable PostgreSQL, stub network/AI calls and clear production credentials. Later durable schema/concurrency gates require PostgreSQL, not SQLite alone.

Phase 1 acceptance: invalid inputs rejected; authenticated business/session scopes retained; two businesses cannot share history; flag-off is unchanged; flag-on invokes the common core; simulator cannot send WhatsApp, create a Job, post Finance or start search; bounded model calls/errors; existing quota and history remain coherent. Later Phase 2 adds real public visitor/inbox/browser QA; do not claim that milestone from simulator tests.

## J. Recommended Phase 1 implementation sequence

1. Re-read current remote main and feature head; preserve the Finance boundary and small allowlist.
2. Add typed/validated input-result contracts and a pure injectable processing service. Start with text-only simulator support; reject unsupported media explicitly.
3. Add a proposed `KILAS_CORE_V2_ENABLED` default-off switch plus server-controlled test-business allowlist in the new flags module. Keep paid entitlements separate. Do not make flags user-selectable.
4. Wrap the existing simulator reply provider and persistence/quota methods. Retain login/business/session checks and current response shape. Do not call the bot webhook, demo endpoint or production action handlers.
5. Add focused core and simulator tests, including negative side-effect assertions; run selected offline regressions. Preserve exact legacy behavior when disabled.
6. Review documentation/source diff and run isolated staging QA only in a separately authorized implementation task. Staging must use its own DB and stubbed/disconnected outbound channels; do not copy production records or trigger migrations on production.
7. Stop Phase 1 at a reusable core plus working internal simulator. Phase 2 adds the real no-login business chat and Inbox integration; phases 3–6 add Customers, Jobs, playbooks/actions and automation; Phase 7 adds the narrow Finance Bridge; Phase 8 connects official WhatsApp to the tested core.

Deployment inventory: both Flask/Gunicorn entrypoints and migration script exist; no tracked render.yaml, Dockerfile, Procfile or GitHub Actions workflow was found in the complete tree. Root bot config requires one sync worker/thread; hub config extends timeout. Production PostgreSQL migration-on-boot defaults off in `db.should_run_migrations_on_boot`, while local SQLite defaults on. Live Render auto-deploy/branch/worker settings remain unverified. No deployment action is part of Phase 0.

Rollback for later gated work is to disable the new Core gate and retain all data; not to restore old databases, drop tables or redesign Finance.

### Audit output verification

The intended and only new file in this run is `docs/KILAS_V2_AUDIT.md`. Final verification must compare the audit commit against the pinned feature head above and confirm exactly that documentation addition, then compare against inspected main to confirm the whole feature branch remains documentation-only (the two input documents plus this audit). No implementation or migration is included.
