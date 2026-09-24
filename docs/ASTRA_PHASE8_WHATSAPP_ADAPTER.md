# ASTRA PHASE 8 — OFFICIAL WHATSAPP ADAPTER

Status: execution specification
Branch: feature/kilas-core-v2
Prerequisite: Phase 7 COMPLETE and all Phase 2–7 CI green

## Goal

Plug official WhatsApp into the already-tested Kilas V2 Conversation Core as a CHANNEL ADAPTER.

WhatsApp must not remain a separate AI/business-logic brain for Kilas V2 tenant conversations.

Target flow:

Meta WhatsApp webhook
-> verified tenant/channel resolution
-> normalized Kilas Core inbound message
-> same Customer resolver / Playbook / Action Engine / Handover used by WEB
-> Core-approved response
-> official WhatsApp outbound transport
-> same Inbox / Customer / Job / Finance Bridge visibility

Public Web Chat and Simulator must continue to use the same Core and remain unchanged.

## Commercial mode before Meta App Review

Phase 8 must preserve a sellable path even when Meta App Review / Advanced Access is not yet approved.

Do NOT claim that arbitrary paying customers can self-connect WhatsApp before Meta grants the
required official permissions/capabilities. Development/test assets, app-role users or reviewer
assets are not equivalent to general customer self-service.

Before approval:
- Kilas AI Admin remains commercially usable through Public Web Chat + Inbox + Customers + Jobs.
- Signup/onboarding must not dead-end just because WhatsApp is unavailable.
- "Connect WhatsApp" is optional and must expose a truthful readiness/pending state.
- Existing official test/reviewer or legitimately permitted Meta assets may be used only within
  their allowed scope.
- No unofficial browser automation, QR scraping, reverse-engineered WhatsApp Web, token borrowing,
  or cross-tenant credential reuse.
- Do not migrate/deregister a real customer number to bypass approval.
- If a user's account legitimately has the required official permissions, allow the supported
  official connection path after all server-side checks pass.
- Otherwise record the exact external Meta blocker and let the business continue with Web Chat.

Commercial definition before review:
A paying customer can create their business, use Public Web Chat, receive conversations in Inbox,
create/reuse Customers, create/update Jobs, use Human Takeover, and use Finance/Bridge according to
their package. WhatsApp becomes an additional official channel when Meta permits it; WhatsApp is
not required for Kilas to be sellable.

## Existing implementation to reuse, not rewrite

Audit these first:
- root app.py official Meta webhook and transport
- client-hub/routes_whatsapp.py
- client-hub/routes_meta_direct.py
- client-hub/whatsapp_signup.py
- client-hub/wa_inbox_shared.py
- client-hub/platform_inbox_service.py
- client-hub/tenant_followup_service.py
- tenant_config_service / provisioning / takeover services
- existing WhatsApp/self-service/coexistence migrations and tests
- docs/WHATSAPP_SELF_SERVICE.md
- current Meta-related environment/runbook assumptions

The repository already contains official Cloud API webhook, signature validation, tenant resolution,
outbound transport, manual Inbox reply bridges, template handling, Embedded Signup work and some
Coexistence handling. Phase 8 must reuse proven pieces and remove duplicate business reasoning,
not throw them away.

## Non-negotiable architecture

Channels are adapters.

WEB, Simulator and WhatsApp must feed the same Kilas V2 Core contract.

Do not build a second WhatsApp-specific Customer/Job/Playbook/AI state machine.

For tenant customer conversations:
- WhatsApp extracts provider/channel metadata only.
- Core owns business understanding and deterministic actions.
- Customer/Job/Attention/Finance Bridge state stays in their existing authoritative services.
- WhatsApp transport sends only a response/action already approved by Core.

Kilas Works platform-owner legacy behavior that is outside the tenant Core must be preserved unless
an explicit tested migration is required.

## Phase 8 milestones

### 1. Current-channel audit and contract map

Inspect current official WhatsApp behavior end-to-end before production edits:
- webhook verification and X-Hub-Signature-256
- payload batching
- message id dedupe
- phone_number_id -> tenant resolution
- credential/channel resolution
- outbound send
- delivery/status callbacks
- Human Takeover
- owner/manual Inbox reply
- approved template path
- follow-up path
- media paths
- current Cloud API vs Coexistence behavior
- failure/retry handling

Write the exact reuse map into docs/KILAS_V2_PHASE8_STATUS.md.

Verify current official Meta documentation for any Graph/API assumptions before changing provider
calls. Do not rely solely on old comments or old version numbers.

### 2. WhatsApp -> Kilas Core adapter

Create a narrow adapter/service boundary instead of extending the root app.py monolith.

Normalize a supported inbound customer text message into the same Core input semantics already
used by WEB/Simulator, including at minimum:
- channel = WHATSAPP
- tenant/business id resolved ONLY from verified phone_number_id
- provider message id
- customer external identity / normalized verified phone
- text
- timestamp/provider metadata needed for idempotency/audit

Do not manufacture WEB visitor ids or fake phone numbers.

The same phone contacting different businesses must remain separate tenant-scoped customer context.

### 3. Durable conversation + Customer identity

WhatsApp inbound must create/reuse the correct Core Customer using verified phone identity under
the existing Customer resolver rules.

Never merge by name alone.
Never merge across tenants.
Never silently merge an unverified contact.
Retries of the same provider event must not create duplicate customers/conversations/jobs.

The owner Inbox must show the WhatsApp conversation through the same product surface as WEB where
the current architecture permits it, with an explicit channel indicator rather than a separate
business workflow.

### 4. Same Playbook / Action Engine

A normal tenant WhatsApp customer message must pass through the Phase 5 Core:
- understanding
- deterministic playbook/state
- safe action engine
- response

Verify parity with WEB for representative flows:
- generic service
- simple order
- booking
- logistics
- agency/project

WhatsApp must not ask again for fields already known by Core.

No provider payload or legacy WhatsApp prompt may override deterministic Core state.

### 5. Human Takeover

Reuse existing takeover services.

When HUMAN_TAKEOVER is active:
- AI must not send automatic replies
- Core financial/job writes triggered by new AI interpretation must be suppressed according to
  existing handover rules
- owner manual reply uses official WhatsApp transport
- replies appear in the same durable conversation history
- resume/return-to-AI must be explicit and tested

For Coexistence message echoes, a human message sent from the WhatsApp Business App / linked device
must not cause a duplicate AI reply. Reuse current safe echo/takeover behavior if still compatible
with the official supported Meta event contract.

### 6. Outbound official transport

Create/reuse a bounded outbound adapter.

Requirements:
- exact tenant phone_number_id/channel only
- never fall back to Kilas Works' platform credentials for a tenant
- bounded timeout
- sanitized provider errors
- do not log tokens or full customer payloads
- provider acceptance is not called delivered/read
- status callbacks remain authoritative for provider delivery state where supported
- retry/idempotency must not duplicate customer sends

Approved templates/re-engagement must continue to use the existing official template path and
current Meta rules. Do not invent a template name or bypass provider policy.

### 7. Coexistence and Embedded Signup

Do NOT redesign onboarding unless required for the adapter.

The repository contains both Embedded Signup/provider-shared work and dedicated Coexistence work.
Audit their current contracts before enabling anything.

If the current Meta app/account is not approved or the necessary official permission/capability is
unavailable:
- keep the adapter default-off for production
- complete deterministic local/CI coverage
- document the exact external blocker
- do not bypass Meta with unofficial browser automation
- do not migrate/deregister a production number merely to make QA pass
- do not claim live Coexistence is verified

If official Coexistence is supported and credentials/permissions are legitimately available,
preserve WhatsApp Business App + Cloud API behavior and prove no duplicate reply between app echo
and API automation.

### 8. Message types

Phase 8 is TEXT-FIRST.

Required:
- inbound text
- outbound text
- human manual text reply
- approved template path where already supported
- provider status events
- Coexistence echoes only where officially supported/currently implemented

Existing bounded media behavior must not regress, but Phase 8 must not expand into a general
multimodal/creative AI project.

Unsupported message types should fail safely or create an owner-attention/handover path; do not
hallucinate media contents.

### 9. Finance safety

WhatsApp does not get direct Finance write authority.

If a WhatsApp conversation leads to Customer/Job state, any Finance behavior must continue through
the Phase 7 Bridge.

Do not let a WhatsApp message:
- auto-issue an invoice
- post a claimed payment
- invent amount/currency/due date/balance/status
- bypass owner confirmation

### 10. Feature flags / rollout

Phase 8 production adapter must remain default-off until all QA gates and external Meta prerequisites
are satisfied.

Prefer explicit per-business/channel readiness over one broad unsafe global cutover.

Unknown phone_number_id must never fall back to another tenant or the Kilas Works platform channel.

Do not change production Render flags/env or deploy production in this phase.

## Mandatory tests

At minimum:
- existing Phase 1–7 regressions stay green
- WEB and Simulator parity remain green
- valid webhook signature / invalid signature
- unknown phone_number_id safe handling
- cross-tenant isolation
- same customer phone across two businesses remains isolated
- provider message-id duplicate/retry
- batched webhook events
- tenant channel credential resolution with no platform fallback
- outbound accepted/error/timeout behavior
- no duplicate outbound on webhook retry
- Customer reuse
- Job create/update parity with WEB
- missing-information flow
- Human Takeover suppression
- manual reply
- takeover resume
- template/re-engagement existing path
- Coexistence echo does not duplicate AI response where supported
- entitlement/subscription disabled or expired state
- Bridge remains owner-confirmed only
- SQLite where applicable
- PostgreSQL runtime
- concurrency/rollback
- mobile owner Inbox QA
- exact diff review
- git diff --check

Add a dedicated Phase 8 CI workflow/gate if existing workflows do not exercise the new adapter.

## Live Meta validation

Automated local/CI tests are not proof that Meta has approved the real app or that a live number is
connected.

If legitimate current credentials and approved permissions are available, a controlled non-production
or explicitly authorized live test may verify:
1. customer sends WhatsApp text
2. correct tenant resolves
3. Core creates/reuses Customer
4. same Core creates/updates Job as WEB
5. AI response sends through official API
6. owner sees it in Inbox
7. Human Takeover stops AI
8. owner manual reply sends once
9. retry does not duplicate
10. second tenant isolation

If those external prerequisites are absent, document BLOCKED EXTERNALLY rather than weakening code.

## Completion gate

Phase 8 is COMPLETE only when:
- official WhatsApp tenant path is a thin adapter into Kilas V2 Core
- WEB/Simulator remain unchanged and green
- tenant/customer/job behavior is equivalent across supported text channels
- dedupe, isolation, takeover and outbound safety pass
- PostgreSQL and mobile Inbox QA pass
- existing approved template/coexistence behavior is preserved or explicitly documented as
  external/not enabled
- no production cutover occurred without explicit user authorization
- Finance remains protected
- no Phase 9 work started

Keep docs/KILAS_V2_PHASE8_STATUS.md current.

If interrupted, commit a coherent passing checkpoint and state:
RESUME FROM STATUS FILE

When complete, mark docs/KILAS_V2_PHASE8_STATUS.md COMPLETE and STOP.
Do not start Phase 9 automatically.
