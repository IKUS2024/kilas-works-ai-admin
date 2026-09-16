# Self-service WhatsApp patch — final report

Baseline: `e1c46c9ca0a7747e90a7f7a293044ac97dc3b93f`
Branch: `feat/whatsapp-self-service` (continued existing isolated worktree).
One local commit; no push or deploy. Exact commit SHA is provided with delivery.

## Result

Code/test readiness: PASS for the provider-shared standard Cloud API flow.
Production release readiness: BLOCKED until the Meta/environment prerequisites below are verified.
No claim of real Meta approval, live registration or production activation.

Customer OAuth token is transient. The server validates customer grant, provider-shared WABA,
phone membership, configured System User identity/scopes, assignment and actual shared-token access.
App subscription and required phone registration/confirmation precede tenant binding.
Ongoing runtime uses `credentials_reference=None` and existing `WHATSAPP_ACCESS_TOKEN`.
No plaintext/encrypted per-tenant token store was created.

Nonce hash + user + exact business + expiry + atomic single-use consumption prevent replay across
requests, workers and restarts. Final binding uses a shared DB lock, duplicate protection, current
business checks and the existing validator. Existing activation gates are reused with the actual
customer actor, never an impersonated admin. Unsuccessful Meta steps cannot create CONNECTED/ACTIVE.
Subscription/activation failure remains connected/pending when appropriate, with explicit retry.

## Tests (all offline; no paid AI or real Meta)

- `client-hub/tests/test_whatsapp_self_service.py`: 35 passed.
- `client-hub/tests/test_whatsapp_signup_ui.cjs`: 8 passed.
- Existing `test_business_hub_v2_phase_bcd.py`: 32 passed.
- Existing `test_production_foundation.py`: 26 passed.
- Existing `test_single_plan_release.py`: 23 passed.
- Existing root `test_multi_tenant_runtime_safety.py`: 28 passed.
- Total: **152 passed, 0 failed**.

HTTP mocked, with process-level network denial for regressions. Includes two independent SQLite
connections racing for the same phone, nested-write rollback, late gate changes, replay, CSRF,
wrong owner, phone/WABA mismatch, Meta HTTP/timeout failure, secret non-persistence, manual admin
validation, payment gate and runtime tenant isolation. No local PostgreSQL/container executable was
available, so real PostgreSQL migration/concurrency was NOT executed. Shared SQL migrations were
checked for common syntax and SQLite idempotence; PostgreSQL deployment validation remains required.

## Migration

YES: additive `0027_whatsapp_signup_sqlite.sql` and `0027_whatsapp_signup_postgres.sql`, registered
in db.py. Stores only hashed signup nonce metadata and a non-secret serialization row. Required
for restart-safe replay protection and cross-tenant binding serialization. No existing records
rewritten/deleted. Apply before this Client Hub code serves traffic, including manual fallback.

## New environment names

Client Hub: `META_APP_ID`, `META_EMBEDDED_SIGNUP_CONFIG_ID`, `META_PROVIDER_BUSINESS_ID`,
`META_PROVIDER_SYSTEM_USER_ID`, `META_PROVIDER_ADMIN_ACCESS_TOKEN`, `META_REGISTRATION_PIN_KEY`.
Existing names required in Hub too: `WHATSAPP_APP_SECRET`, `WHATSAPP_ACCESS_TOKEN`,
`WHATSAPP_PHONE_NUMBER_ID`. Existing `META_GRAPH_API_VERSION` honored; default v21.0 unchanged.
Never enter secrets in customer forms or commit them. App/config IDs alone are public SDK settings.

## Pending Meta / production prerequisites

- Business Verification, Tech Provider/access verification, appropriate App Review/Advanced Access,
  Live app and Facebook Login for Business v4 configuration: status unverified.
- Provider must actually receive shared client WABAs and have Admin System User assignment rights.
  App-only/BISU-only onboarding without provider sharing is NOT silently treated as compatible.
- Runtime System User must match the configured app/user and have management/messaging permissions;
  both Hub and bot must resolve the same shared credential.
- HTTPS/JS domains, login configuration, existing app webhook + messages subscription, customer
  Meta billing and a supported tested Graph version require operator verification.
- Standard Cloud API signup only; WhatsApp Business App/coexistence/migration requires support and
  is intentionally rejected rather than accidentally re-registering a live app number.
- Keep registration PIN derivation key stable and backed up; existing PIN issues need support.
- Controlled real Meta signup + inbound/outbound + second-tenant smoke test still required after
  approvals. No real Meta HTTP request was performed by this task.

See `WHATSAPP_SELF_SERVICE.md` for official source links, exact sequence and deployment order.

## Final flows

Customer: setup -> pay Rp499.000 -> wait for human verification + admin review/approve/provision ->
Hubungkan WhatsApp -> own Meta login/OTP/selection -> verified connection -> automatic activation
only through existing gates. No WABA/Phone ID/token/password entry in Kilas UI.

Admin: verify payment -> review/approve/provision. Inspect existing connection/audit information.
Manual connection remains support fallback; activation pending can be retried without new signup.

Unchanged: Rp499.000 pricing, 2,000-response monitoring, AI usage dashboard, catalog, landing page,
bot prompts/behavior, payment verification rules, runtime tenant resolution. No AI calls added.
