# Kilas Assist + Finance master completion

FINAL STATUS: IN PROGRESS — NOT COMPLETE. No master-task deployment yet.

## Current baseline (2026-09-27)
- Current remote main: `4344748c439597744806ad8ccb6a5ad7a8a0e54f` (fresh ls-remote and clone).
- Working branch: `feature/kilas-master-completion-20260927` from current main.
- Repository: IKUS2024/kilas-works-ai-admin.
- Production kilas-works-client-hub: LIVE at the same SHA (fresh Render deploy readback).
- Production kilas-works-ai-admin: LIVE at the same SHA (fresh Render deploy readback).
- Both services on main, auto deploy OFF (preserved).
- Production PostgreSQL 18: available. Infrastructure IDs intentionally omitted from this public checkpoint.

## Source of truth / implementation map
Read all 30 master pages, all 31 detailed blueprint pages, and all 14 pricing pages once.
Precedence: user's MASTER TASK and FINAL OVERRIDES > Master Blueprint > detailed Blueprint > repo legacy docs. Pricing PDF is supplementary only.
- Signup FIRST, existing six onboarding parts, seven-day free demo, conversational training/test/ready, real prospect-private demo WhatsApp, paid activation, assisted connection.
- Exactly two products: Assist and protected separate Finance. No Coexistence, Worker, content/video or website service in the requested product UI.
- Exactly four owner Job statuses: Perlu tindakan, Dikerjakan, Selesai, Batal. Meetings/deals remain NEW; only invoice/payment intent advances IN_PROGRESS; completion requires authoritative Finance posting.
- Finance invoice/payment/ledger stays authoritative. Screenshots are candidates only; human confirmation required; no second ledger and no production Finance QA writes.
- Pricing: Demo 7 days; launch first paid month 99,000 (either selected paid plan, per final prompt); Starter 299,000; Pro 799,000 IDR/month. Auditable rule; bundle Finance entitlement.
- Customer usage no provider/model/token/cost jargon; configurable inexpensive provider route, structured same-call explanation; internal cost attribution.
- Platform SaaS admin separated from customer CRM; auditable support banner; assisted WA queue; fail-closed WABA/Phone ID routing.

## DONE
- Fresh main and both live deployment identities verified.
- Source PDFs fully read and extracted into scratch only.
- Production DB table/column inventory read-only (no secrets selected).
- Production existing authorized customer session inspected: Assist Home and More load, bottom destinations already Home/Inbox/Customers/Jobs/More.
- No applicable AGENTS.md found in repository or workspace ancestors.

## IN PROGRESS
Checkpoints 1–6 have substantial implementation, still not complete. Four-state Jobs, atomic payment completion and auditable pricing now tested. Next: complete demo/manual media, Finance bundle entitlement, production runtime/connection flow, and SaaS Admin; then full QA/deploy.

## Checkpoint 1–2 local implementation (not deployed)
- Existing account creation preserved; returning Google users now enter their existing workspace.
- Product picker shows only Assist/Finance; Assist More removes Services/Content/Talent.
- Home shows readiness/WhatsApp/usage and separate Finance link; Inbox navigation defaults to WhatsApp.
- New assist_journey lifecycle uses existing onboarding_sessions events; trial starts after all six parts and cannot restart on retries.
- New owner-only /business/<id>/train teaches and corrects one canonical FAQ through existing versioned knowledge service, with conflict checks.
- Test AI uses current scoped business facts. Successful test fingerprint must match before owner confirms readiness; failed inference never establishes ready.
- Training normalization preserves current business status. Knowledge stays in existing business/FAQ/config authorities.
- Demo CTA requires readiness and active demo/paid entitlement; connected businesses redirect to production Inbox.
- Additive migration 0066 introduces private demo bindings and explicit event-to-message membership. No Finance services/templates/calculations edited.
- Demo webhook intercept resolves the bound tenant before knowledge/inference; raw message remains in platform Inbox, and only explicit session messages appear in tenant workspace. Duplicate claims precede AI/send; ambiguous sends are not retried.
- Shared sender rebind deactivates old binding without moving old messages. Demo CRM uses tenant WhatsApp identity and same-inference structured facts; actionable leads promote in all tenants.
- Demo reply uses bounded relevant knowledge + recent messages, same-call safe explanation, and configurable OpenAI economical route / Claude escalation. Existing configured Claude path remains available. Provider errors are sanitized.
- Text human replies include an independently verified explicit demo scope on the internal bridge and are linked to that session. Takeover is checked before and after AI.
- Router scopes now include customer_insight, follow_up and assist_demo in the existing usage ledger. Provider dimension and profitability UI still pending.

## Findings / bugs / diagnosis
- `kilas_core/jobs.py` exposes only three owner states and groups COMPLETED into IN_PROGRESS: stale relative to final four-state requirement.
- Home currently promotes demo before training, omits readiness/usage/Finance shortcut; More advertises content/project/talent outside scope.
- Canonical Assist catalog still prices 499,000 and retired Pro 999,000; subscription lifecycle must be reused, not replaced.
- Existing Finance workspaces, entitlements, branches, bridge, invoice/payment services exist: preserve their accounting contracts.
- Demo binding exists in routes_client audit/session state. Found a gap: shared-number messages currently use platform knowledge, not prospect-trained knowledge; rebinding one sender across businesses needs a bounded session history to avoid cross-session exposure. Must fix before certification.

## NEXT (one task; internal checkpoints)
0. Finish current schema/WA/AI/payment/admin inspection and relevant test baseline.
1. Signup-first flow, naming and navigation.
2. Conversational training/Test AI/ready and real prospect-private demo.
3. Inbox/media/safe explanation/CRM.
4. Four-status deterministic Jobs.
5. Authoritative Finance bridge invoice/payment/receipt.
6. Pricing/usage/configurable AI router/cost.
7. Platform Admin.
8. Assisted production WhatsApp connection.
9. Full QA, additive migration rehearsal if needed, merge/deploy/live smoke.

## Tests passed
Fresh protected Finance baseline: 39 files, 1018 tests, 0 skipped, all PASS (logs in scratch /tmp/kilas-master-finance-baseline).
Workspace baseline and post-change suite PASS. New master journey suite: 5 tests PASS (six-part gate, seven-day retry safety, knowledge correction, tenant isolation, current-version successful test required, GETs without model/writes).
New demo suite: 7 PASS (binding, cross-tenant rebind, replay, takeover/media, lead→customer→job, ambiguous delivery, expiry). New router suite: 3 PASS (cheap route, bounded fallback/error redaction, no hidden reasoning/ungrounded action). Journey suite rerun PASS.
## Tests still failing
New isolation test initially expected 403; existing security deliberately returns 404 to conceal tenant existence. Test corrected to exact 404; no authorization weakened. Broader suites not yet run. GitHub commit-workflow wrapper returns no PR-triggered runs for merge main; not evidence of green CI.
## Migration/schema notes
Production contains kw_core_* Jobs/CRM/bridge/WhatsApp and existing subscriptions, ai_usage_ledger, knowledge revisions, Finance tables. Migration 0066 is local only; migration rehearsal and production apply pending. No production data modification performed.
## PR/merge status
Remote checkpoint branch exists; signup/training checkpoint committed as 37246ec. Demo/router checkpoint committed as 540753cb. Finance/Jobs/pricing/cost checkpoint is being published. No PR/merge yet. CLI push has no GitHub credential; authenticated GitHub connector can publish changes.
## Deploy status
No changes deployed in this run.
## Production verification
Read-only Home/More baseline only; master journey not verified.
## Remaining external blockers
None established yet. Real production WhatsApp OTP and test messages may need owner involvement; do independent implementation first.
## Resume
Read this checkpoint, inspect working diff/current main only as needed, and continue NEXT without rereading unchanged PDFs or restarting completed work. Keep status IN PROGRESS until all definition-of-done gates are verified.

## Remaining implementation risks at this checkpoint
- Legacy audit-bound demo tests must be migrated to explicit session fixture and preserve isolation assertions; old production demo users will need a fresh binding (knowledge/data stay intact).
- Demo human template/media outgoing attribution still needs the same scope contract as text replies.
- Demo voice/document vision and payment evidence extraction are not yet integrated; original inbound media remains visible.
- Jobs now show four states and Finance bridge atomically completes paid Jobs. Receipt uses existing idempotent transport; real delivery verification pending.
- New pricing is integrated with the existing payment/subscription lifecycle. Finance included entitlement integration, SaaS Admin, production WABA queue, and full production runtime routing still require completion.

## Checkpoints 4–6 implementation update (not deployed)
- Owner Jobs now expose exactly NEW / IN_PROGRESS / COMPLETED / CANCELLED with required Indonesian labels. Ordinary owner/AI updates cannot set COMPLETED; only the private Finance payment actor can.
- Finance bridge calls the unchanged authoritative record_invoice_payment service, verifies PAID/zero outstanding and posted income references, then updates Job in the SAME Finance compound transaction. Job/audit failure rolls back payment and income. External receipt send runs after commit with stable invoice identity; UI/network retry does not add income or another invoice.
- Assist invoice panel shows completed paid invoice and Konfirmasi Pembayaran. Meeting/deal without payment remains Perlu tindakan through existing deterministic gate (additional negation/evidence hardening still pending).
- Launch pricing is an auditable rule with immutable snapshot in existing project requirements + audit. First paid month 99,000, normal Starter 299,000 / Pro 799,000; promo eligibility checks verified Assist invoices across plans. Per-business transaction reuses existing unpaid checkout. Historical locked invoice amounts preserved.
- Verified new-format order applies one existing subscription period per unique invoice and supports idempotent renewal/plan change. Legacy orders keep existing lifecycle.
- Public landing now starts with registration/login and pricing; pricing included on active Demo Home, training conversion and Paket & Penggunaan. Finance remains separate.
- Migration 0067 adds provider attribution to existing ai_usage_ledger (historical default Anthropic). New OpenAI calls explicitly attribute provider; no new cost or Finance ledger.
- Customer counters expose reply/media/follow-up counts and Normal/Tinggi/Hampir capacity status only. Starter/Pro thresholds configurable; high usage never blocks a call.
- assist_costs platform read model provides provider/feature/business costs, projected monthly cost, actual verified subscription revenue, ratio, largest feature and configurable 15%/25% guardrails. Dashboard wiring pending.
- Expired demo sender no longer falls back to platform knowledge. A paid user may request a fresh binding after old session expiry. Journey respects configured subscription grace period.

## Validation at this update
- Assist suites: journey 5, demo 7, router 3, billing 4, costs 2 tests PASS (21 tests across five suites; earlier four-suite aggregate then new cost suite).
- Jobs store and route suites PASS; Finance bridge service and route suites PASS. Bridge shared tests augmented with completion and transaction rollback assertions; financial assertions not weakened.
- Finance protected baseline rerun: 39 files / 1018 tests, one Home navigation-gate regression identified; other 38 files PASS. Fixed Assist Home to respect Finance visibility and selected owned Finance business. Entire affected Finance phase1b suite then PASS (16 tests); protected test unchanged. Final full rerun still required at release gate.
- AI usage diagnostics/monthly diagnostics/monthly query PASS. FX suite initially exposed pre-existing template/test wording mismatch (same mismatch verified on baseline SHA) plus stale 499k price. Restored explicit USD/IDR labels in Admin costs and updated only the reference price expectation to 299k; FX suite PASS with all calculation assertions unchanged.
- Legacy Jobs fixture lacked onboarding/demo schema; added additive fixture tables instead of hiding production errors. Former manual-COMPLETED test expectation was stale against final master rule; now asserts rejection, and bridge tests prove successful authoritative completion.
- Outstanding broad regressions not yet audited: old demo audit-range fixtures, retired-single-plan UI assumptions, old Web labels and public channel behavior. Preserve security/accounting contracts while updating only proven stale expectations.

## Resume priority
1. Finish required Finance bundle entitlement without changing Finance accounting or multi-business/branch semantics; preserve existing explicit bridge mapping.
2. Assisted WhatsApp queue + authoritative WABA/Phone ID mapping and test gates; SaaS Admin/support banner and audit.
3. Full production Assist inference/media/payment evidence/follow-up integration and demo manual media/template scope.
4. Upgrade final regression fixtures, rehearse additive migrations, review complete diff, merge/deploy both services, verify live. Do not certify before these gates.
