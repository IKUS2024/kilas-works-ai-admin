# ASTRA PHASE 2 — PUBLIC WEB CHAT + LIVE INBOX INTEGRATION

Repo: IKUS2024/kilas-works-ai-admin
Branch: feature/kilas-core-v2

READ FIRST:
1. docs/KILAS_V2_MASTER.md
2. docs/KILAS_V2_AUDIT.md
3. docs/ASTRA_PHASE1_CORE.md
4. current git diff / current branch implementation state

PRECONDITION:
Phase 1 must already be implemented and tests passing.
If Phase 1 is incomplete, STOP and complete only Phase 1 first.

GOAL:
Implement the first SELLABLE Kilas V2 channel without waiting for Meta App Review:
a real public customer web chat per business that routes through the same Conversation Core and appears in the owner Inbox.

NON-NEGOTIABLE:
- Finance remains protected. No Finance redesign, migration, accounting changes, or direct SQL.
- Do not change WhatsApp production behavior.
- Do not deploy production until staging/browser QA passes.
- Do not fake phone numbers for web visitors.
- Tenant isolation must fail closed.

REQUIRED CUSTOMER EXPERIENCE:
Owner can get a public link conceptually:
  /chat/<business-slug>
End customer can open it without creating an account.
The chat must:
- resolve the correct business server-side
- create a safe visitor/session identity
- send text messages through Kilas Conversation Core
- receive AI replies
- persist conversations/messages durably
- appear in owner Inbox as WEB channel
- allow human takeover/reply without pretending it is WhatsApp
- preserve channel identity in all replies

OWNER EXPERIENCE:
In the existing owner product area, add minimal controls only:
- Open as customer
- Copy public chat link
No redesign of Finance.

SCHEMA:
Use minimal additive schema only if required by the audit.
Migrations must be additive/backward-compatible and reviewed carefully.
Never alter or replay destructive legacy migrations.

SAFETY:
- slug->business mapping is server-controlled
- opaque visitor token/session; do not trust arbitrary business_id from client
- rate limit / abuse controls
- CSRF model appropriate for public anonymous chat
- strict tenant scoping on every read/write
- duplicate/retry/idempotency handling
- no platform-tenant fallback
- no outbound WhatsApp side effects

INBOX:
Integrate web conversations into owner Inbox without breaking existing WhatsApp inbox behavior.
If existing Inbox storage cannot safely model web identity, add a channel-neutral core conversation store instead of writing fake phone keys into legacy tables.
Existing WhatsApp views must keep working.

TESTS:
Add focused tests for:
- valid business slug
- invalid/disabled slug
- anonymous visitor session creation
- same visitor conversation continuity
- two businesses isolated
- forged conversation/business blocked
- duplicate inbound message
- provider failure
- owner sees only own web conversations
- human takeover/reply for WEB channel
- no WhatsApp send triggered from web channel
- no Finance writes
- existing Inbox/tenant regressions remain passing

BROWSER QA:
Use a staging/dev environment only.
Test actual mobile-width flow:
1. owner opens dashboard
2. copies/opens public link
3. customer sends message
4. AI replies
5. owner sees conversation
6. owner takes over and replies
7. customer receives reply
8. second business cannot access conversation

OUTPUT:
- exact files changed
- migrations added (if any) with rationale
- test commands/results
- browser QA evidence/results
- confirm Finance untouched
- confirm WhatsApp behavior untouched
- confirm production not deployed until explicit approval

STOP after Phase 2.
Do not implement Customers, Jobs, Playbooks, Finance Bridge, or WhatsApp cutover in this same run.
