# Kilas Brain: customer WhatsApp connection

## Readiness and credential architecture

This implements the **provider-shared WABA / provider System User** path, not an app-only
installation. Customer OAuth codes/business tokens are request-local and are never written to
DB, cookies, HTML, logs, files or environment. The final tenant channel records
`credentials_reference=None`; both services must resolve the same existing server-side
`WHATSAPP_ACCESS_TOKEN`. No per-tenant token store was added.

The previous assertion that persistent customer tokens are *always* required was too broad.
Meta's official collection documents shared client WABAs and assigning a provider System User
with an Admin System User token. However, availability of those operations is **not proof that
the particular Kilas Meta app/business has that access**. No code here manufactures asset sharing.
A customer-specific grant AND provider sharing AND verified runtime access must all succeed.
App-only installs, WABAs not shared with the provider, unapproved apps or insufficient permissions
fail closed. There is no fallback to storing a customer token or borrowing another tenant's token.

## Official references checked 2026-09-16

- [Meta Embedded Signup implementation](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation)
- [Meta versions](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/versions):
  v4 uses the selected products in the Login for Business configuration and an empty `extras`.
  Do not reuse a legacy config without verifying its v4 products/settings.
- [Meta Tech Provider onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider):
  exchange the code server-side; prepare the customer channel. This does not alone prove that a
  pre-existing provider token gains asset access.
- [Meta official Shared WABAs request](https://www.postman.com/meta/whatsapp-business-platform/request/63s87ze/shared-wabas):
  GET `/{provider-business-id}/client_whatsapp_business_accounts` verifies actual provider sharing.
- [Meta official Add System User request](https://www.postman.com/meta/whatsapp-business-platform/request/g07y08h/add-system-user-to-waba):
  POST `/{waba-id}/assigned_users`, `user` and `tasks`, authenticated by an Admin System User token.
  This release uses the documented MANAGE task and separately checks runtime access.
- [Meta manage accounts](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/manage-accounts/):
  Debug Token discovers granted WABA targets. This patch requires a matching customer grant;
  absent granular target evidence is a safe failure, not permission to trust browser IDs.
- [Meta official app subscription](https://www.postman.com/meta/whatsapp-business-platform/request/ju40fld/subscribe-app-to-waba-s-webhooks):
  POST `/{waba-id}/subscribed_apps`.
- [Meta phone registration](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration):
  POST `/{phone-id}/register` with `messaging_product` and six-digit PIN when registration is needed.
- [Meta business phone numbers](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers):
  connected status is required for messaging.
- [Meta Business App onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users):
  coexistence has additional requirements. This release rejects Business App/coexistence and
  unsupported completion variants and never registers them as an ordinary Cloud API number.
- [Meta app-only install](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/app-only-install):
  app-only configuration restricts credentials differently; it is not the supported provider-shared path.
- [Meta permissions](https://developers.facebook.com/documentation/business-messaging/whatsapp/permissions)

Some developer-document full pages returned HTTP 429 in the research browser; official indexed
extracts and Meta's official Postman endpoints were available. Tests are contracts against those
APIs, not evidence of a real Meta account being approved or a live signup working.

## Server sequence

1. Authenticated business access, supported Kilas Brain package, APPROVED, human VERIFIED
   payment and provisioned tenant config are required before issuing a ten-minute random nonce.
2. Nonce hash is stored with user/business; completion atomically consumes it. A second tab/load
   replaces it. Replay, expiry, wrong user and wrong business are rejected, including across workers.
3. SDK returns an OAuth code plus asset selectors, posted with CSRF. No credential in callback URL.
4. GET `/oauth/access_token`; Debug Token checks valid token, app ID and granted WABA target.
5. Customer-token phone listing proves phone belongs to WABA. Provider client-WABA listing
   independently proves the WABA is shared with Kilas.
6. Debug the configured runtime token: same app, expected System User, management + messaging
   scopes. Assign that System User with the separate provider Admin System User credential.
7. Confirm phone membership with the shared runtime token. Subscribe this app to WABA.
8. Inspect phone identity/status/Business App flag; refuse unsupported Business App numbers.
   Register ordinary Cloud API phone only if not connected; confirm CONNECTED afterward.
9. Serialized DB binding rechecks current ownership/payment/approval/config and duplicate phone.
   Reuse existing live validator, bind only this business, merge only WhatsApp config fields.
10. Attempt the existing activation core: existing payment, approval, config, connection and
    subscription gates remain. Audit uses the actual customer actor, never a fake admin.
    Subscription/activation failure keeps connection pending activation; retry is explicit.

Graph calls have bounded timeouts, no redirects and no automatic retries. Pagination uses bounded
cursors against a fixed Graph host, never response-supplied URLs. Unknown/error response data is
not rendered or logged. Explicit retry uses a fresh signup nonce/code after failure. Assignment
and subscription are idempotent; an already connected phone is not re-registered. No message is sent.

Registration PINs are deterministically derived per phone from `META_REGISTRATION_PIN_KEY`.
Keep this secret stable and backed up in the operator secret system; losing/rotating it does not
rotate existing phone PINs. Never print PINs. Existing PIN/migration issues require admin support;
there is no PIN-guessing loop. Do not enable the Business App/coexistence product for this release.

## Environment names (no values)

New Client Hub configuration:
- `META_APP_ID`
- `META_EMBEDDED_SIGNUP_CONFIG_ID`
- `META_PROVIDER_BUSINESS_ID`
- `META_PROVIDER_SYSTEM_USER_ID`
- `META_PROVIDER_ADMIN_ACCESS_TOKEN` (server-only Admin System User credential able to assign shared WABAs)
- `META_REGISTRATION_PIN_KEY` (server-only random secret, at least 32 characters)

Existing/reused:
- `WHATSAPP_APP_SECRET` (must now also be available in Client Hub for code exchange/debug)
- `WHATSAPP_ACCESS_TOKEN` (same provider runtime System User credential in Hub and bot)
- `WHATSAPP_PHONE_NUMBER_ID` (platform number reserved; configure in Hub too)
- `META_GRAPH_API_VERSION` (existing convention; default remains v21.0; explicitly select a
  supported app-tested version before production rather than relying on the default)
- `PUBLIC_APP_BASE_URL`, `SECRET_KEY`, `DATABASE_URL`, existing internal/runtime safety environment
  remain unchanged. `META_EMBEDDED_SIGNUP_URL` is no longer the self-service launch mechanism;
  old callback is retained as a safe informational redirect.

## Additive migration and deployment order

Migration 0027 creates only a hashed nonce table and one non-secret serialization lock row.
No credential, payment, historical record or knowledge data is rewritten. Both SQLite and
PostgreSQL scripts are idempotent and registered in db.py. The global lock is shared with the
manual admin validator, then the self-service path locks its business row. Nested config writes
cannot commit/release the outer transaction. SQLite concurrency is tested; live PostgreSQL was
not available locally and must not be claimed as tested.

Before deploying Client Hub, back up normally and run `python3 scripts/run_migrations.py` from
`client-hub` against the intended database. Apply 0027 before code handles requests (including
manual connection, which uses the shared lock). Then configure the env names above and deploy
Client Hub. Bot code is unchanged; verify matching runtime credentials on both services.
No migration/deployment was run against production by this task.

## Meta production release blockers / manual validation

Unverified externally: Kilas Business Verification, Tech Provider/access verification, app Live
mode, App Review/Advanced Access for the selected permissions, approved Login for Business v4
configuration, provider shared-WABA/assignment eligibility and real runtime System User access.
Provider management requires appropriate business_management/whatsapp_business_management access;
runtime must have whatsapp_business_management + whatsapp_business_messaging. Meta decides access.
If the app's current onboarding mode only grants a customer business token and does NOT share
WABAs with the provider, this release fails safely and requires Meta/provider configuration
resolution; it must not be advertised as universal Tech Provider readiness.

Configure HTTPS app/JS domains and login settings in Meta, existing verified webhook callback,
and app-level messages webhook subscription. WABA subscription here does not replace app webhook
setup. Customer Meta billing/payment method requirements still apply separately from Kilas's
Rp499.000 subscription; no credit-line or Meta billing changes are made by this patch.

After these prerequisites are approved, perform a controlled live signup and verify inbound +
outbound on the correct tenant, then a second tenant isolation check. No real Meta API test,
message send, or production activation was performed here. Manual admin connection remains fallback.

## Customer / admin flow

Customer: existing setup/payment -> human verification + approval -> Hubungkan WhatsApp ->
Meta login/OTP/asset selection -> server verification -> connected -> automatic gated activation.
No WABA ID, Phone ID, token, credential-reference or Meta password input fields in Kilas UI.
If blocked, reload for signup retry or use explicit activation retry / contact Kilas Works.

Admin: human payment verification -> business review/approve/provision -> inspect connection
and activation status. Manual connection form remains labeled support fallback. Safe signup
failure categories are recorded in the existing audit trail. No tokens are shown.

No price, monitoring threshold, AI/API model call, bot behavior, payment rule, catalog, landing
page, AI usage dashboard or tenant runtime credential resolution was changed.
