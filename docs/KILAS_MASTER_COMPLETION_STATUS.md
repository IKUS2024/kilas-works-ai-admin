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
- Pricing: Demo 7 days; launch Starter first month 99,000; Starter 299,000; Pro 799,000 IDR/month. Auditable rule; bundle Finance entitlement.
- Customer usage no provider/model/token/cost jargon; configurable inexpensive provider route, structured same-call explanation; internal cost attribution.
- Platform SaaS admin separated from customer CRM; auditable support banner; assisted WA queue; fail-closed WABA/Phone ID routing.

## DONE
- Fresh main and both live deployment identities verified.
- Source PDFs fully read and extracted into scratch only.
- Production DB table/column inventory read-only (no secrets selected).
- Production existing authorized customer session inspected: Assist Home and More load, bottom destinations already Home/Inbox/Customers/Jobs/More.
- No applicable AGENTS.md found in repository or workspace ancestors.

## IN PROGRESS
Checkpoint 0: targeted implementation inventory and test baseline.

## Findings / bugs / diagnosis
- `kilas_core/jobs.py` exposes only three owner states and groups COMPLETED into IN_PROGRESS: stale relative to final four-state requirement.
- Home currently promotes demo before training, omits readiness/usage/Finance shortcut; More advertises content/project/talent outside scope.
- Canonical Assist catalog still prices 499,000 and retired Pro 999,000; subscription lifecycle must be reused, not replaced.
- Existing Finance workspaces, entitlements, branches, bridge, invoice/payment services exist: preserve their accounting contracts.
- Demo binding exists in routes_client audit/session state; must inspect tenant isolation and production suppression before reuse.

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
None executed for this master run yet. Historical checkpoint test claims are not current certification.
## Tests still failing
Not yet assessed. GitHub commit-workflow wrapper returns no PR-triggered runs for merge main; not evidence of green CI.
## Migration/schema notes
Production contains kw_core_* Jobs/CRM/bridge/WhatsApp and existing subscriptions, ai_usage_ledger, knowledge revisions, Finance tables. No migration or data modification performed.
## PR/merge status
New local branch only; no PR/merge yet.
## Deploy status
No changes deployed in this run.
## Production verification
Read-only Home/More baseline only; master journey not verified.
## Remaining external blockers
None established yet. Real production WhatsApp OTP and test messages may need owner involvement; do independent implementation first.
## Resume
Read this checkpoint, inspect working diff/current main only as needed, and continue NEXT without rereading unchanged PDFs or restarting completed work. Keep status IN PROGRESS until all definition-of-done gates are verified.
