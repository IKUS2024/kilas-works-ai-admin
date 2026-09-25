# Phase 8 — COMPLETE

Branch: `feature/kilas-core-v2`.
Certified implementation/test SHA: `09bb73d9f4f39e55524737b94c1956eee821e67e`.
Application code final at `ce917d94dde2fa2255767b92798e085689de5b49`;
09bb73d adds only lifecycle test fixtures, the CI invocation and checkpoint documentation.
Initial feature head: `3b21f7c6990e20d7b30ff2c8cf79ce55f2c5f4d7`.
Remote main inspected and unchanged: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.
No production deployment, activation, environment change, customer-number migration or Phase 9.
The final certification commit changes this status document only; all results below apply to
the exact certified implementation/test SHA above. Completion recorded 2026-09-24 UTC.

## Final result and boundary
WhatsApp is a channel adapter into the SAME business Core as Public Web Chat:
verified root webhook -> phone_number_id tenant binding -> normalized channel envelope ->
shared Customer resolver -> shared Playbook/Action Engine -> existing Customer/Job/Handover ->
Core-approved response -> bounded official Cloud API transport. No second business brain,
customer/order/finance system or creative/general chatbot was introduced.

WhatsApp remains optional. Onboarding exposes a Web Chat skip path and a truthful Meta
readiness limitation. Active paid WEB businesses can use the supported official signup flow
when legitimately eligible. Provider-shared/Coexistence signup checks remain intact; neither
payment nor a CONNECTED legacy record is itself proof of Core production readiness.
Public Web Chat, Inbox, Customers, Jobs, Takeover and package-authorized Finance remain independent.

Live general-customer WhatsApp activation: **EXTERNALLY BLOCKED / NOT VERIFIED**.
No legitimate live test credentials/assets with verified current app/asset grants were supplied
or used for this validation. App Review/Advanced Access, relevant provider/System User grants,
WABA/number binding and Coexistence capability must be verified externally before activation.
This does not assert the app was rejected or that its current dashboard status was inspected.
No live Meta send or live Coexistence capability is claimed tested. Test/reviewer assets are
not general production availability. Production selection is default-off, per tenant/channel.

## QA certification
All Phase 2–8 workflows at 09bb73d are **SUCCESS**. Phase 1 is included in the regression gates.
Final Finance baseline job 107855911520: **1018 PASS / 39 files**. PostgreSQL 18,
concurrency/rollback, owner mobile Inbox and Finance Bridge gates all PASS.

| Gate | Final checkpoint run | Result |
| --- | --- | --- |
| Phase 2, including Phase 1 and WEB regression | 36066040480 | SUCCESS |
| Phase 3 Customers | 36066040447 | SUCCESS |
| Phase 4 Jobs | 36066040440 | SUCCESS |
| Phase 5 Playbooks | 36066040433 | SUCCESS |
| Phase 6 Operations/Handover | 36066040404 | SUCCESS |
| Phase 7 Bridge, full Finance, PostgreSQL, mobile | 36066040450 | SUCCESS |
| Phase 8 WhatsApp adapter, PostgreSQL 18, mobile | 36066040492 | SUCCESS |

Evidence on final application code ce917d9: Phase 2–8 runs 36065483715 / 36065483725 /
36065483709 / 36065483741 / 36065483728 / 36065483753 / 36065483727 all SUCCESS.
Finance job 107854124256 reports 1018 PASS across 39 files. Phase 8 mobile artifact
10836480249 (390x844 Chromium) inspected: known item/weight/origin/destination retained;
only missing volume requested; owner takeover, manual text, approved template, explicit resume,
Job update, tenant denial, correct hidden/disabled controls, no horizontal overflow or JS error.
Final checkpoint Phase 8 artifact: 10837250130. Its runtime log confirms all offline
test suites, PostgreSQL and mobile PASS. No application code differs from the
visually inspected ce917d9 artifact.
Provider IO and model extraction in QA are deterministic stubs; database/Core/UI are real.

Coverage and executed commands:
- `python scripts/run_offline_tests.py --only test_kilas_whatsapp`: 21 tests, 3 files,
  real root valid/invalid HMAC, batches, unknown phone ID, channel no-fallback, identity isolation,
  Customer reuse, Job create/update, five-playbook WEB/WA parity, known/missing fields,
  takeover during inference, manual/template/resume, Coexistence echo dedupe, delivery state,
  rejection/timeout, no duplicate attempt, owner CSRF/scope, entitlement and Finance protection.
- `python client-hub/tests/kilas_whatsapp_postgres_qa.py`: 5 identical runtime cases on
  PostgreSQL 18 (also SQLite): concurrent identity creation, provider-event conflicts,
  atomic rollback, shared Core Job writes, concurrent send retries, abandoned attempt safety,
  repeat additive installer. Explicit disposable loopback database guards required.
- Phase 8 CI also runs existing signup/Coexistence (41 tests), multi-tenant runtime safety,
  media webhook, Inbox unification, platform takeover, and subscription lifecycle (31 tests).
  Lifecycle proves elapsed period -> GRACE -> SUSPENDED, preserved data and owner renewal.
  Existing grace policy is authoritative; the adapter does not invent its own billing policy.
- Phase 2–6 workflows exercise Phase 1 Core/Simulator, WEB/Customers/Jobs/Playbooks/Operations,
  SQLite, PostgreSQL and mobile. Phase 7 runs complete isolated Finance baseline, Bridge
  services/routes, PostgreSQL migration/concurrency, and standalone/connected/read-only mobile.
- Local Finance baseline: 1018 PASS / 39 files / no skips/errors. Local Phase 1–7 focused
  regressions and Phase 8 tests PASS. Exact full diff reviewed; `git diff --check` PASS.
  Finance production services, Bridge production code, and prior migrations are unchanged.

## Architecture decisions
- Shared orchestration lives in `kilas_core/conversation.py`; WEB's previous module is a
  compatibility entrypoint. Understanding, deterministic decisions and action writes are shared.
- Existing `kw_web_*` conversation/event/history tables retain all Core FK relationships.
  WhatsApp has explicit provider metadata, actual typed provider identity and expiry 0;
  no WEB visitor credential or fake phone is issued. Anonymous WEB authentication cannot read it.
- Verified phone identity is tenant-scoped `WHATSAPP_PHONE`, separate from WEB visitor identity;
  editable names/profile phones cannot silently merge customers. Provider ID binding precedes
  customer/action processing; conflicting provider retries cannot create another identity.
- 0061 is additive transport metadata only, with SQLite/PostgreSQL installers. Business then
  conversation lock order protects identity, action transactions, takeover and outbound attempts.
- Selected Core traffic never falls back to legacy reasoning on error. Existing root signature,
  batches, authoritative tenant resolver, media persistence and final channel cleanup are reused.
  Unsupported Core media becomes a durable human-review input; no fabricated media understanding.
- Takeover uses existing services/state plus shared Core fencing. App/linked-device echoes enter
  durable human history once and suppress AI; API-send echoes do not create human duplicate replies.
- Manual replies and configured approved templates use official transport and durable attempt IDs.
  Acceptance is distinct from delivered/read; status callbacks are tenant/recipient-scoped and
  monotonic, and owner polling updates previously displayed messages. Customer inbound bubbles
  are never labeled as outbound sends.
- No Finance writes originate in WhatsApp. Valid unsupported payment claims request a human;
  invoice creation/issuance/payment/transaction entrypoints and Bridge draft creation are not
  called. Existing owner-confirmed Phase 7 services remain the only authority.

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


## Meta documentation verification limits
Current official references were attempted on 2026-09-24. Full pages for permissions,
Coexistence onboarding and echoes returned HTTP 429. Follow-up current official service-message
and status pages also returned 429; Message API returned 500. Search snippets corroborated
existing endpoint/status/template concepts but do not certify live grants or all current rules.
Existing provider API shape/version configurability was preserved; no new provider contract
was invented based on inaccessible documentation.
- https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages
- https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status
- https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-phone-number/message-api
- https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users

## Audit and checkpoint history
All seven requested specifications read completely. Requested `docs/WHATSAPP_SELF_SERVICE.md`
is absent; existing authoritative root `WHATSAPP_SELF_SERVICE.md` was read completely instead.
Phase 7 prerequisite was COMPLETE (implementation df211580, documentation 5659121).
Initial Phase 2–6 CI green; Phase 7 initially running with prior successful run available.
- fc5dcb0: first shared adapter checkpoint; Phase 8 PostgreSQL/mobile and Phase 7 PASS.
  Phase 2–6 mobile caught a WEB-only heading regression. Restored its original heading,
  retaining old test assertions; all later Phase 2–6 gates PASS.
- 468fceb: optional signup, delivery polling, template UI; Phase 2–8 PASS. Screenshot review
  found inherited CSS overriding hidden owner buttons. Corrected at ce917d9 and verified visually.
- Existing signup/isolation/lifecycle fixtures also failed on the untouched initial base.
  Updated synthetic required business-phone/profile/trusted-owner inputs and obsolete validator
  stub signature, plus lifecycle's obsolete card-title check and missing renewal CSRF token.
  No production checks were weakened; security/data assertions preserved, signup and lifecycle
  suites now green and included in Phase 8 CI. No unrelated runtime lifecycle change.
- Remote interactive browser could not reach loopback (ERR_BLOCKED_BY_CLIENT). Used the
  repository's isolated CI Playwright/Chromium harness and inspected its screenshots; no bypass
  of that browser restriction and no claim of live Meta browser testing.

## Exact changed files against initial feature head
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
- `client-hub/static/web_chat.css`
- `client-hub/static/web_inbox.js`
- `client-hub/templates/web_inbox.html`
- `client-hub/templates/whatsapp_connect.html`
- `client-hub/tests/kilas_whatsapp_browser_qa.py`
- `client-hub/tests/kilas_whatsapp_dev.py`
- `client-hub/tests/kilas_whatsapp_postgres_qa.py`
- `client-hub/tests/kilas_whatsapp_runtime_cases.py`
- `client-hub/tests/test_kilas_whatsapp.py`
- `client-hub/tests/test_kilas_whatsapp_runtime.py`
- `client-hub/tests/test_subscription_lifecycle.py`
- `client-hub/tests/test_whatsapp_self_service.py`
- `client-hub/wa_takeover_service.py`
- `client-hub/whatsapp_signup.py`
- `docs/KILAS_V2_PHASE8_STATUS.md`
- `inbox_service.py`
- `test_kilas_whatsapp_webhook.py`
- `test_multi_tenant_runtime_safety.py`

## Exact next action
**STOP. Phase 8 is technically COMPLETE.** No further implementation action remains in this phase.
Live general-customer activation remains externally blocked until official permissions, asset
access and separately approved rollout are verified. Public WEB remains the usable commercial
channel. No production deployment/cutover or Phase 9 is authorized by this completion.
