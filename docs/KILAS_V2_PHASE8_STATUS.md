# Phase 8 — IN PROGRESS

Resume from this file. Base feature: `3b21f7c6990e20d7b30ff2c8cf79ce55f2c5f4d7`.
Remote main: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.
No production deployment, activation, environment changes or Phase 9.

## Required reading and prerequisite
All seven required specifications read completely. `docs/WHATSAPP_SELF_SERVICE.md`
does not exist; the authoritative existing file is root `WHATSAPP_SELF_SERVICE.md`.
Phase 7 COMPLETE at implementation df211580, final documentation 5659121. Latest
base-head Phase 2/3/4/5/6 runs 36061604261/270/228/269/274 SUCCESS; Phase 7
36061604243 pending when first inspected (previous 36061026443 SUCCESS).

## Existing channel reuse map
- Root `receive_webhook`: HMAC signature, batched entries/changes/messages, runtime
  lock and finally-cleaned channel credentials. Keep as provider ingress.
- `_resolve_tenant_or_unknown`: verified phone_number_id, ACTIVE business and paid
  subscription; unknown rejects. No chat-selected tenant.
- Legacy provider message claims precede business reasoning. New Core path must own
  its durable claim before this legacy claim to recover interrupted work safely.
- Root text transport uses official /messages, bounded timeout, accepted != delivered.
  Status callbacks currently acknowledge without persisting delivery state.
- `tenant_config_service`, root channel resolver and hub `inbox_service` permit
  absent credential reference to use platform runtime token. This historical shared
  provider assumption is NOT sufficient authority for the new adapter; require exact
  reviewed channel readiness and explicit tenant credential binding, no fallback.
- `public_chat.playbook_adapter`: current production Core orchestration invokes
  understanding, deterministic actions, Customer/Jobs and handover. Reuse this exact
  pipeline across channels, not a WhatsApp prompt/state machine.
- `kw_web_*`: existing durable conversations/events/messages/customer links are already
  referenced by Core Jobs/attention/Bridge. Extend their use through explicit channel
  metadata; preserve existing WEB visitor authentication. No fake visitor credentials.
- `wa_takeover_service`: existing legacy per-business/phone takeover; synchronize with
  Core fencing. Core owner replies require official transport plus durable send state.
- `routes_client` and `inbox_service`: existing manual/media/template surfaces. Keep
  legacy paths; Core conversations appear alongside WEB with channel labels.
- `wa_inbox_shared`: reuse phone/window and configured approved-template payloads.
- `tenant_followup_service`: retain legacy behavior; prevent an independent legacy
  AI follow-up from running on enabled Core customer conversations.
- `whatsapp_signup`, `routes_whatsapp`, `routes_meta_direct`: retain nonce/CSRF,
  customer grant, shared WABA, System User checks and explicit Coexistence path.
  Root self-service document predates current dedicated Coexistence implementation.
- Root `smb_message_echoes`: app/linked-device replies enable takeover, store bounded
  history, never AI. Keep provider contract; Core mirror must be idempotent.
- Existing media recording happens before legacy reasoning. Retain media for owner
  review; do not expand creative or multimodal AI.

## External blockers / claims
Official Meta permissions, Business App onboarding and smb_message_echoes reference
pages attempted 2026-09-24; all returned HTTP 429. No new provider contract claimed
verified. No real app permissions, approval, asset access or live sends certified.
General self-service requires Meta App Review/Advanced Access and relevant provider,
WABA and number capabilities. Test/reviewer access is not general availability.
Adapter remains default-off. Public WEB remains independent of optional WhatsApp.

## Current checkpoint / next action
Remote implementation checkpoint: `fc5dcb0ebaafaaa52cdd6bee34bea30d6dab77e5`.
Its Phase 8 run **36064123810 SUCCESS** includes PostgreSQL 18 and mobile owner Inbox.
Phase 7 **36064123684 SUCCESS**. Phase 2–6 caught one shared browser heading regression
("Percakapan web" changed). Fixed by retaining that heading for WEB-only Inbox; all
existing assertions retained. The next checkpoint includes this fix, optional signup
for active WEB businesses, live delivery-state polling and template owner UI.
Next: push verified refinements, require Phase 2–8 CI SUCCESS on the new implementation
SHA, inspect final mobile screenshots, then mark COMPLETE. No production activation.

## Implementation checkpoint (not completion)
- Shared orchestration moved without a second business brain to `kilas_core/conversation.py`;
  existing WEB entrypoint remains a compatibility adapter. WhatsApp uses that same pipeline.
- Additive explicit 0061 installer: provider bindings, per-channel inbound identity claims,
  outbound attempts. Shared historical kw_web_* tables retain Core FK relationships.
  WhatsApp rows use actual typed provider identity and expiry 0; no visitor credential is
  issued and public WEB authentication cannot read them. Identity type WHATSAPP_PHONE is
  tenant-scoped and never matches editable names/phone profile fields automatically.
- Root signature/batching/tenant resolution reused. Core-selected traffic never falls back
  to legacy reasoning on channel/config/runtime errors. Existing media recorder retained;
  unsupported Core media enters human handling, never fabricated interpretation.
- Dedicated token references plus reviewed per-business/phone readiness required. Existing
  provider-shared onboarding stays intact, but blank-reference platform-token fallback is
  deliberately insufficient for Core activation. No credentials or production flags changed.
- Shared Core takeover fences writes. Existing WA takeover state synchronized atomically;
  explicit owner resume, durable manual reply and configured approved template API included.
- Attempt reservation commits before bounded official send. Send is serialized with takeover;
  timeout/process interruption remains unknown/attempting and never auto-retries. Provider
  acceptance is separate from status callbacks. Owner history displays transport state.
- SQLite shared Core/identity/outbound/concurrency and actual root HMAC/batching tests added.
  Five playbooks compare WEB/WA Job fields, lifecycle and response, including missing logistics.
- Full Finance baseline on this implementation: 1018 PASS / 39 files / no skips/errors.
  Phase 1–7 focused local regressions passed. Legacy media, Inbox unification, platform takeover
  passed. Legacy multi-tenant/signup suites initially failed identically on the unmodified
  base: missing declared business-phone fixture and obsolete validator stub signature.
  Corrected test fixture inputs only, retained all assertions; both suites now PASS.
  Added two optional-onboarding assertions (signup suite now 41 tests).
- PostgreSQL/mobile CI passed at the checkpoint above; refinements require revalidation. Remote browser loopback blocked with
  ERR_BLOCKED_BY_CLIENT; repository CI mobile test uses synthetic local Chromium only.
- Next: run dedicated Phase 8 CI + all prior phase gates, inspect mobile artifact, close
  remaining readiness/status/retry review findings and legacy baseline triage; then certify.

## Operational boundary (documentation only; no activation performed)
- Apply existing Phase 2–7 schema prerequisites and the existing official WhatsApp/takeover
  migrations before explicitly running `python -m kilas_core.whatsapp_schema --apply`
  from `client-hub`. The 0061 installer is additive/idempotent; never runs on app startup.
- Production remains default-off: `KILAS_WHATSAPP_CORE_ENABLED` is absent/false. Selection
  additionally needs server-controlled `KILAS_WHATSAPP_CORE_CHANNELS` with each business's
  exact `phone_number_id` and `official_access_verified: true`. This flag records an
  externally reviewed grant; it does not obtain Meta approval or prove live capability.
- Each selected channel needs its own `WHATSAPP_TOKEN__TENANT_<business_id>` credential
  reference, CONNECTED binding, matching business phone ID and active Core entitlement.
  Platform tokens, blank reference fallback and duplicate tenant token values are rejected.
  Existing provider-shared signup is preserved, but does not by itself satisfy this
  stricter Core credential boundary. Separate authorization is required for any rollout.
- Cloud API version remains the existing configurable `META_GRAPH_API_VERSION` (fallback
  v21.0); no new provider endpoint or capability invented. Production operators must verify
  currently supported version, app permissions and asset grants before any live activation.
- Free-text sends use a conservative 23-hour inbound window. Outside it, the owner can use
  the existing configured, Meta-approved template under takeover. This does not resume AI.
  Legacy autonomous AI follow-up is skipped for Core-selected tenants; no second business
  brain sends independently. Existing nonselected follow-up/media paths remain intact.
- Outbound attempts are at-most-once, not a claim of exactly-once provider delivery.
  Timeout/crash/ambiguous provider response remains unknown/attempting, requiring owner
  inspection; webhook or browser retries never automatically send that event again.
  Business/conversation locks serialize the bounded network send with takeover and status
  callbacks. This can delay same-business operations for the provider timeout interval.
- Provider acceptance is distinct from delivered/read. Status callbacks update scoped
  records; owner polling refreshes them without labeling inbound customer messages sent.
- Finance services and Phase 7 Bridge production code are unchanged. Customer claims have
  no invoice/payment authority; existing owner confirmation and entitlements remain required.

## Exact changed-file manifest against initial feature head
- `.github/workflows/kilas-v2-phase8-qa.yml`
- `app.py`
- `client-hub/inbox_service.py`
- `client-hub/kilas_core/actions.py`
- `client-hub/kilas_core/adapters/whatsapp.py`
- `client-hub/kilas_core/contracts.py`
- `client-hub/kilas_core/conversation.py`
- `client-hub/kilas_core/customers.py`
- `client-hub/kilas_core/handover.py`
- `client-hub/kilas_core/jobs.py`
- `client-hub/kilas_core/whatsapp_access.py`
- `client-hub/kilas_core/whatsapp_schema.py`
- `client-hub/kilas_core/whatsapp_transport.py`
- `client-hub/migrations/0061_kilas_whatsapp_postgres.sql`
- `client-hub/migrations/0061_kilas_whatsapp_sqlite.sql`
- `client-hub/public_chat/owner.py`
- `client-hub/public_chat/playbook_adapter.py`
- `client-hub/routes_client.py`
- `client-hub/routes_whatsapp.py`
- `client-hub/static/web_inbox.js`
- `client-hub/templates/web_inbox.html`
- `client-hub/templates/whatsapp_connect.html`
- `client-hub/tests/kilas_whatsapp_browser_qa.py`
- `client-hub/tests/kilas_whatsapp_dev.py`
- `client-hub/tests/kilas_whatsapp_postgres_qa.py`
- `client-hub/tests/kilas_whatsapp_runtime_cases.py`
- `client-hub/tests/test_kilas_whatsapp.py`
- `client-hub/tests/test_kilas_whatsapp_runtime.py`
- `client-hub/tests/test_whatsapp_self_service.py`
- `client-hub/wa_takeover_service.py`
- `client-hub/whatsapp_signup.py`
- `docs/KILAS_V2_PHASE8_STATUS.md`
- `inbox_service.py`
- `test_kilas_whatsapp_webhook.py`
- `test_multi_tenant_runtime_safety.py`
