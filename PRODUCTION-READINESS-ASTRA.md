# Kilas Works — Astra production hardening

Verdict: code packaged for conditional deployment after offline regression verification. This is not approval to enable multi-tenant on unverified infrastructure. No live deployment or real messages/payments were performed.

## Bugs actually fixed

- Meta sends require HTTP 200 plus a returned message ID. Failed, partial and uncertain sends no longer become successful conversation history. Catalog/QR actions run before their confirmation, and failed booking/payment mutations produce failure wording. Unbacked owner send claims are replaced with truthful replies.
- New-customer notifications are marked only after accepted send; known failures remain retryable. These owner notifications remain allowed during human takeover, while customer AI replies are prohibited and inbound history/service-window timestamps are retained.
- Handoff notification state and correlation keys persist in the existing messages table and restore after restart. Failed handoffs cannot claim forwarding success. Owner relay clears the pending request only after accepted customer send.
- Hot lead/payment notification branches no longer suppress each other; notification markers follow actual acceptance. Durable outbound claims protect notification and scheduled-follow-up replay.
- Owner outbound freeform checks the known service window, cron skips human takeover, and configured approved notification templates are used only after definitive Meta window error 131047. Missing templates fail truthfully.
- Webhook signatures are verified; all messages in batched entries/changes are processed; internal failures return 503, and channel state is cleared after exceptions. Durable channel-scoped webhook claims survive restart.
- Platform owner search/prompts exclude tenant-prefixed customer data. Tenant channel resolution rejects ambiguous and disconnected mappings. Direct tenant AI calls cannot fall back to platform business facts/prices.
- Appointment/payment updates include business scope in SQL; payment proof ownership is validated. PostgreSQL write operations are not blindly replayed after a lost connection acknowledgment.
- Business creation used millisecond timestamps for unique tenant slugs; rapid creation could collide. New slugs use UUIDs without changing existing slugs.
- Dashboard now exposes the authenticated user's purchases made without a business; another user's standalone purchases remain hidden. Payment proof upload rejects invalid/already-submitted states before inserting another file.

## AI cost: evidence and architecture

The large input came mainly from the monolithic static customer prompt: core policy, examples, catalog/pricing, payment, scheduling, talent, links and operational instructions were sent together even for unrelated simple requests. It was compounded by all agreed facts, broad owner/customer summaries and redundant contextual modules. Full persisted conversation history was NOT the sole cause: the existing message window was already bounded to 20 turns. Previously a transport failure could also lead to an unnecessary stronger-model attempt.

Same empty-memory platform fixture: legacy builder 58,790 characters; focused builder 18,834 characters (18,700 stable + 134 dynamic), a 67.96% reduction. This compares prompt characters, not measured Anthropic tokens or dollars. The real initial greeting now bypasses this builder/API entirely.

Before: monolithic prompt + broad business/customer context + bounded history -> model, including simple requests.
After: safe deterministic router -> either exact code/DB result or cached stable core/canonical policy + scoped topic modules + relevant memory + bounded recent dialogue -> fast model. Older agreed facts remain stored; matching facts and the latest decisions are selected without truncating individual records, and explicit broad recaps retain all relevant-source records. Conversation-aware retrieval uses recent turns so short follow-ups retain context. No new lossy model-generated summary replaces the source records.

Implemented zero-LLM paths: initial greetings, unambiguous live fixed catalog price queries, platform catalog requests, canonical demo/Client Hub URLs, explicit handoff requests, and exact pending-payment-review counts. Existing deterministic owner commands remain available. Ambiguous, custom-price, contextual and reasoning requests retain the AI path; this is not a claim that every possible invoice/customer question is deterministic.

Stable text blocks carry Anthropic cache_control ephemeral; dynamic tenant/customer facts follow separately. Cached Python prompt components avoid repeated static construction. No prompt padding is added to force caching. Cache hits depend on model minimum size, exact prefix reuse, traffic and TTL. Ordinary text uses MODEL_FAST (Haiku); genuine explicit complex owner analysis can escalate. Existing vision capability still uses the primary model. Transient retry uses the same model, not an automatic expensive upgrade.

Observability records model, input/output tokens, cache read/write tokens and hit indicator, context type/tenant-scoped flag, prompt sizes, deterministic routing and escalation reason. These new telemetry records omit full messages, credentials and provider response bodies. Existing application operational logs still contain customer identifiers; configure access and retention accordingly.

Shared AI_ADMIN_CORE_BEHAVIOR, canonical PRICING_CONFIG and the uploaded static catalog are preserved. Relevant facts are selected rather than deleted; no invented CUSTOM_QUOTE amount is introduced. Numerical payment claims are checked against authorized source facts/canonical platform amounts before automated payment wording.

## Multi-tenant verdict

Application isolation is hardened and adversarial regressions pass locally. ENABLE_MULTI_TENANT is not enabled by this package. Activation remains blocked unless the bridge is available, the bot has PostgreSQL configured, WHATSAPP_APP_SECRET exists and KILAS_SINGLE_RUNTIME_CONFIRMED=true. Operators must independently verify that bot and Client Hub point to the SAME production database, that existing migrations are applied, and that each active connected WhatsApp mapping and credentials reference belongs to the intended business.

The shipped Gunicorn config requires one sync worker/thread. There must also be exactly one bot replica; the confirmation flag is an operator assertion, not infrastructure discovery. Multiple workers/replicas remain unsupported because some conversation/owner selection and negotiation state is process-local. Existing scoped payment/subscription/memory/cron safeguards are retained; SQLite development fixtures do not certify production DB grants/RLS or infrastructure ownership.

## Targeted Client Hub UI/UX pass

Preserved the dark/orange premium visual identity. Updated customer-facing Kilas Brain names while retaining internal ai_admin keys. Improved onboarding step labels, optional-business explanation, missing-field wording and purchase/payment state clarity. Removed duplicated hardcoded package prices in the business selector. Verified/reviewing invoices no longer invite another transfer/upload. Added accessible upload labels, friendly 413 handling, 10 MB per-file and 11 MB total selection guidance, busy/double-submit protection, focus states, narrow-screen wrapping, 44 px touch targets and 16 px mobile inputs. Customer/admin navigation remains separate; technical setup details are retained only where operationally needed. Tests render templates/routes; no physical-device/browser screenshot certification is claimed.

## Exact regression results

Full existing discovery ran ONCE: 67 test files, initially 48 PASS / 19 FAIL.
Focused repair verification: 16/19 PASS, then 1/3 PASS, then final 4/4 PASS (the two remaining failures plus both newly added Astra test files).
Final latest result: all 67 discovered test files PASS; no unresolved test-file failures. This is not a second clean full-suite run. New behavioral tests: 24 backend + 5 UI = 29, all pass in final verification.

All external network connections were blocked, including child processes. Real SQLite repositories and mocked provider responses were exercised. PostgreSQL ledger SQL was exercised using a SQLite adapter, not a live PostgreSQL server. Existing runner and test discovery were preserved.

Updated existing expectations follow intentional contracts: cache text blocks are flattened before the SAME tenant-data assertions; greetings no longer test the model path; takeover permits ONLY owner-destination notifications while still banning AI/customer sends; foreign channels cannot fall through to platform; production startup without prerequisites must fail; approved public branding/catalog text reflects the attached current assets. File types, authentication, scoped visibility, prices and action outcomes remain asserted. The missing-driver test now explicitly simulates a missing driver instead of assuming the environment lacks an installed dependency. No tests were skipped.

After final targeted verification passed, source code was frozen before packaging.

## Migration requirements

No new tables, columns, data backfill or destructive migration. One new partial unique index on existing messages(number, mode), restricted to _webhook_claim and _outbound_claim: scripts/production_runtime_claims.sql. app.init_db() applies it idempotently too. Existing production messages must exist for the standalone SQL; a fresh bot database gets the table/index through initialization. Ensure the deployment role can create the index, or have a database administrator apply it. Existing Client Hub migrations remain required on a fresh/outdated DB: python client-hub/scripts/run_migrations.py.

## Environment requirements

- DATABASE_URL: required for production bot durability; use the same PostgreSQL database for bot and Client Hub.
- APP_ENV=production: set outside Render to enforce production DB/signature requirements. Render already activates these through RENDER.
- WHATSAPP_APP_SECRET: required for signed production webhooks; use the Meta app's real secret.
- ENABLE_MULTI_TENANT: leave false until infrastructure verification is complete.
- KILAS_SINGLE_RUNTIME_CONFIRMED=true: new required assertion ONLY when enabling multi-tenant after verifying one sync worker/thread and one replica.
- Optional approved owner-notification fallback: WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_NAME and WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_LANGUAGE (default id). For each tenant use the corresponding names with __TENANT_<business_id> suffix. The template must accept the configured one body-text parameter; no cross-tenant fallback to the global template.
- Existing scheduled follow-up template configuration, tenant credential-reference variables and MODEL_FAST/MODEL_PRIMARY/MODEL_FALLBACK remain compatible. Ordinary failures no longer trigger MODEL_FALLBACK automatically. No new AI API dependency or pricing environment override is required.
- Preserve existing ANTHROPIC_API_KEY, WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, OWNER_WHATSAPP_NUMBER, VERIFY_TOKEN, DASHBOARD_KEY, CRON_SECRET, INTERNAL_SERVICE_SECRET and Client Hub session/storage/integration configuration. Use real non-default secrets; none are supplied in this archive.

## Deployment steps

1. Back up the production DB and retain the previous deployment for rollback. Unzip preserving kilas-works-ai-admin-main/ and configure secrets in the host environment.
2. Install both requirements files. Apply existing Client Hub migrations if needed; apply the runtime-claims index to an existing bot messages table, or allow bot init to create it. Confirm bot/Hub DB identity.
3. Deploy bot from repository root using gunicorn -c gunicorn.conf.py app:app with ONE replica. Deploy Client Hub separately from client-hub/ using its existing app:app entrypoint and existing secure environment.
4. Keep multi-tenant disabled until connected WABA mappings, signature secret, shared Postgres, credential authorization and single-runtime requirements are verified. Configure approved templates before relying on out-of-window notifications/follow-ups.
5. Before customer traffic, perform controlled provider smoke checks for signed inbound, new customer, failed/successful handoff, template rejection/acceptance, proof review, follow-up opt-out and restart. Inspect AI_USAGE cache/model counters and durable claim states. Do not use a live payment or message merely to test without an authorized recipient.

## Remaining production risks

No live Anthropic/Meta/PostgreSQL, approved-template, actual mobile-device or host topology verification was possible here. Cache savings and intelligence quality require representative real traffic evaluation; lexical memory retrieval is conservative but cannot guarantee semantic recall for every paraphrase. Some owner selection/negotiation state remains volatile after restart, requiring explicit target clarification.

Durable claims use at-most-once safety for uncertain outcomes. A crash after claiming, transport timeout or partial bubble delivery may leave a pending/uncertain operation requiring operator reconciliation; it is deliberately not blindly resent. This prevents duplicates but does not provide transactional exactly-once external delivery. Meta acceptance is not delivered/read confirmation. Do not delete/reset pending claims until checking the provider outcome.

The catalog PDF in the original upload is preserved; runtime live catalog generation remains separate. Existing public/admin flows outside the targeted pass were not redesigned.

## Exact changed files

Modified (37):

- `app.py`
- `client-hub/app.py`
- `client-hub/appointments_repo.py`
- `client-hub/db.py`
- `client-hub/display_labels.py`
- `client-hub/payment_reviews_repo.py`
- `client-hub/projects_repo.py`
- `client-hub/repo.py`
- `client-hub/routes_client.py`
- `client-hub/routes_payments.py`
- `client-hub/templates/base.html`
- `client-hub/templates/business_settings.html`
- `client-hub/templates/checkout.html`
- `client-hub/templates/client_dashboard.html`
- `client-hub/templates/invoice.html`
- `client-hub/templates/review.html`
- `client-hub/templates/service_catalog.html`
- `client-hub/templates/wizard.html`
- `client-hub/tenant_config_service.py`
- `client-hub/tests/test_absolute_final_production_patch.py`
- `client-hub/tests/test_ai_admin_single_purchase_path.py`
- `client-hub/tests/test_business_hub_v2_phase_i.py`
- `client-hub/tests/test_catalog_editor_removed.py`
- `client-hub/tests/test_k7_kopi_legacy_payment_and_ui_cleanup.py`
- `client-hub/tests/test_production_foundation.py`
- `client-hub/tests/test_service_selection_purchase_flow.py`
- `client-hub/tests/test_subscription_lifecycle.py`
- `client-hub/tests/test_talent_photo_upload_ux.py`
- `test_adversarial_audit.py`
- `test_business_hub_v2_whatsapp_integration.py`
- `test_platform_takeover.py`
- `test_pro_tenant_parity.py`
- `test_production_hardening.py`
- `test_sales_brain_v2.py`
- `test_sales_engine.py`
- `test_tenant_persistence_and_payment_review.py`
- `test_unified_ai_brain_v2.py`

New code/tests/config (8):

- `client-hub/templates/upload_too_large.html`
- `client-hub/tests/test_astra_ui_production.py`
- `context_engine.py`
- `gunicorn.conf.py`
- `scripts/offline_tests/sitecustomize.py`
- `scripts/production_runtime_claims.sql`
- `scripts/run_offline_tests.py`
- `test_astra_production_fix.py`

New deployment documentation: `PRODUCTION-READINESS-ASTRA.md`. No original source files deleted.
