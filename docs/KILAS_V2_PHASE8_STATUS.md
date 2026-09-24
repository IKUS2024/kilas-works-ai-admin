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

## Next action
Implement bounded channel boundary, shared Core orchestration, durable outbound
at-most-once attempt records, explicit optional readiness and regression coverage.
All Phase 8 test/PG/mobile completion gates currently PENDING.

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
  passed. Existing multi-tenant legacy test fails missing_whatsapp_business_phone; identical
  failure reproduced at unmodified base. Existing signup suite has 7 failures/3 errors on
  both base and current (39 tests); not hidden or certified green, requires triage.
- PostgreSQL/mobile CI added; not yet certified. Remote browser loopback blocked with
  ERR_BLOCKED_BY_CLIENT; repository CI mobile test uses synthetic local Chromium only.
- Next: run dedicated Phase 8 CI + all prior phase gates, inspect mobile artifact, close
  remaining readiness/status/retry review findings and legacy baseline triage; then certify.
