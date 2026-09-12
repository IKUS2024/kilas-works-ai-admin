# Targeted production upgrade — delta only

Apply the ZIP at the existing repository root (the directory containing app.py and client-hub/), over the current Astra working tree/previous full production package. Paths below are repository-relative. This archive is not a complete repository.

## Exact fixes

- Owner intent distinguishes GLOBAL_ANALYZE, LOOKUP, QUERY, ACTION and SEND before stale active-customer/pending-action fallback. Read requests cannot execute model-generated forwarding. Explicit named lookups retain their named conversational target; unrelated queries discard stale clarification state. Natural reverse-order action wording remains supported.
- Global analysis uses scoped summaries of at most 25 customers, four bounded snippets per customer, with a 22,000-character dynamic ceiling and an explicit subset/uncertainty warning. Unnamed customers with scoped conversation history are included. Ordinary ranking remains on the fast model; explicit complex multi-factor reasoning can escalate. No full per-customer histories are injected for global ranking.
- SMTP delivery exceptions, bad configuration and timeouts do not change the generic forgot-password response. Production SMTP runs through a bounded background queue to remove SMTP latency from the HTTP request. Tokens/recipients/provider error bodies are not logged. Production mode is shared across APP_ENV, CLIENT_HUB_ENV and Render; production wins conflicting flags. Session cookies are Secure and a real SECRET_KEY is required. Production reset links require the configured HTTPS PUBLIC_APP_BASE_URL.
- Tenant-owned /business/<id>/memory supports live description/knowledge, services, FAQ, tone/language/salutation and operating information after APPROVED/ACTIVE. Membership authorization and a field whitelist protect access. Existing profile/service/FAQ rows and their live tenant-config snapshot update atomically, without onboarding restart or LLM normalization. No global settings access is added.
- Basic-to-Pro entitlement requires a scoped verified Pro receipt; applied upgrade receipts cannot be reused after downgrade. Package, subscription plan and stored feature flags update together. Runtime features intersect package and subscription entitlements and enforce expiry even before cron, respecting the existing configured grace period. Existing ACTIVE legacy Basic/Pro tiers remain unchanged.
- Existing checkout supports an explicit Pro-upgrade request without granting Pro beforehand, using the existing canonical Pro catalog item and payment flow. After verified payment, the admin applies the package upgrade. This does not invent prorated prices or a new billing period.
- Unavailable appointment/payment/owner settings are gated server-side, including direct writing-helper requests for restricted fields. Basic settings/onboarding forms hide these unavailable controls. Public wording directly touched uses Kilas Brain; internal ai_admin keys stay unchanged.

## Exact test results

New focused tests: 7 owner routing + 19 Client Hub = 26/26 PASS.
One relevant regression pass only: 11 test files; initially 8 PASS / 3 FAIL.
Focused repair runs: 3/5 PASS, then 3/3 PASS. Latest result for all 11 relevant files: PASS; no unresolved failures. The complete unrelated regression universe was not run.
The existing debug-mode source assertion was updated to require the stronger production guard. Other existing assertions remain intact. All provider connections were blocked by the existing offline test runner; no real email, WhatsApp or payment action was performed. Source files were frozen after final verification.

Relevant files tested:
- test_owner_intent_target_resolution.py
- test_owner_nlu.py
- test_pro_tenant_parity.py
- test_tenant_owner_media_and_isolation.py
- test_targeted_owner_upgrade.py
- client-hub/tests/test_business_hub_v2_phase_a.py
- client-hub/tests/test_production_foundation.py
- client-hub/tests/test_subscription_lifecycle.py
- client-hub/tests/test_client_hub_v1.py
- client-hub/tests/test_ai_admin_single_purchase_path.py
- client-hub/tests/test_targeted_production_upgrade.py

## Migration requirement

None new. Reuses existing business_profiles, business_services, business_faqs, tenant_configs, tenant_features, subscriptions, payments and audit_log structures. Apply on the already-migrated current working tree. No schema, price or historical billing backfill is fabricated.

## ENV requirement

No new variable names. APP_ENV=production OR CLIENT_HUB_ENV=production (or Render) activates production safety; production overrides a conflicting development value. SECRET_KEY must be set. For production email configure PUBLIC_APP_BASE_URL=https://app.kilasworks.id, SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD; SMTP_PORT defaults to 587 with verified STARTTLS. RESET_EMAIL_FROM defaults to SMTP_USERNAME if omitted. Missing/invalid production mail configuration fails with the same generic user response and a safe operational log.

## Remaining operational limitations

Live SMTP delivery and production PostgreSQL/host behavior still need deployment smoke verification. The bounded email queue is process-local/best-effort, so a restart can discard queued mail; users can request a fresh reset link. Legacy ACTIVE tenants without a subscription row retain their current tier as required; dated expiry needs their real existing billing-period record/backfill, not an invented date. No new horizontal-runtime or tenant-infrastructure approval is granted by this delta.

## Token architecture confirmation

Normal customer prompt caching, relevant-memory retrieval, deterministic customer routing and fast-model defaults are unchanged. No extra LLM call or global context block was added to ordinary messages. Memory edits are deterministic DB/config updates; owner global analysis has its own bounded read-only context.

## Archive manifest

18 added/changed source/template/test files, plus this newly added manifest. No unchanged files, secrets, local databases, caches or generated test artifacts are included.

- `app.py` — SHA256 `82742f4b72f999cb9ed691d07d2e939a214f7def5027dd1b76e857f74e12853e`
- `client-hub/app.py` — SHA256 `77eebe22ddb03e9f9764cb212261987b4c2312b56a129030416aaa6b8e513449`
- `client-hub/email_utils.py` — SHA256 `8c873bec52ea0a9947fd3a04e88d9fb8a1c69e38b0edc91ae0b1210f4fd55a28`
- `client-hub/provisioning.py` — SHA256 `ef257739e35d80c50766b3dcb60807fae28fde7ca79a76d1e7ebb86db9239192`
- `client-hub/repo.py` — SHA256 `9ac525edd0e3a15f43aee8b1b7cfd3f28b16c1364287acd0f452ae9173b33f89`
- `client-hub/routes_admin.py` — SHA256 `a36fc822b72d80d8b0fd4a5e3a9a5795a1fb9778c290ae68f62236ec5e10119a`
- `client-hub/routes_auth.py` — SHA256 `36b5a152df494b796093dad85f8696447c925e344e393170eb37882c4f1c103f`
- `client-hub/routes_client.py` — SHA256 `9c542bf83c40d6b5e391b4564cc40a8144bf5d71e8433481f7c26c5c2ddba8a9`
- `client-hub/runtime_environment.py` — SHA256 `2ab73931c5ac76f01e5e1e1c94567396035d3b6f6eebf6a59f772c4824246b44`
- `client-hub/subscription_service.py` — SHA256 `be662c0655b3786bfbb72783f49a0eab9a35978364a14cf44fa8619eef0edd2b`
- `client-hub/templates/business_memory.html` — SHA256 `c8793cc7e1aa13abfe0da2a0ff8380d225dbccd39bc639189655f369c3b1cb55`
- `client-hub/templates/business_settings.html` — SHA256 `bbb509f517c9a94e02e1c3180e72e4049138da6a05cd0d66ceb076d73890009d`
- `client-hub/templates/client_dashboard.html` — SHA256 `360dd0c229b589362bebefe1649f8460df311d340a390be09326152cf004e951`
- `client-hub/templates/wizard.html` — SHA256 `c84c3a0dc5cec049f9595a728253caf061085bc99c7e60cde0ef59428c620454`
- `client-hub/tests/test_production_foundation.py` — SHA256 `c4653566c64ebc326fc9388f1dde28d00818322a9ea4aad98e65ea5fb94335c4`
- `client-hub/tests/test_targeted_production_upgrade.py` — SHA256 `af88c0321b397464f64f983c9303ad28e6aa66f9d5512f2eba8d39572e4573f2`
- `owner_intent_routing.py` — SHA256 `985944b7e158424c4090b6e3ab22c33eab06783335dff54a73908e779f703178`
- `test_targeted_owner_upgrade.py` — SHA256 `6e29dc7b50ddd956be4230b6f8c0246e56f2380eef9eb95ace09c1a8e03c70c3`
- `TARGETED-UPGRADE-MANIFEST.md`
