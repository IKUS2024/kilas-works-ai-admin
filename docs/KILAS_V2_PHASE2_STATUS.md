# Kilas V2 Phase 2 status

Status: IN PROGRESS — milestones 1–6 complete; final regression/QA gates pending.
Branch: `feature/kilas-core-v2`.
Starting/current remote SHA: `2849db26b184763d2f5404dbd0758e88b857c4b0`.
Remote main inspected: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.
All five requested documents and Phase 1 execution instructions read completely.
Phase 1 status is COMPLETE; its 30 tests passed before Phase 2 edits.

## Proposed file impact (recorded before code edits)
- Existing `client-hub/kilas_core/contracts.py`: additive WEB envelope; simulator validation retained.
- New `client-hub/public_chat/` package: additive schema installer, scoped storage/transactions,
  visitor security, web core adapter/provider, routes and rollout gate. Separate from simulator-only package guards.
- New paired `client-hub/migrations/0055_public_web_chat_{sqlite,postgres}.sql`: only new WEB tables.
  Apply only these files through an explicit installer; do not register/replay the destructive legacy chain.
- Existing `client-hub/app.py`: blueprint registration, anonymous WEB CSRF/session hook exception
  restricted to public endpoints with their own independent visitor authorization and same-origin checks.
- Existing `client-hub/routes_client.py`: WEB inbox branch only; default WhatsApp handler unchanged.
- Existing `client-hub/templates/inbox.html`, `product_dashboard.html`, `assist_entry.html`, `client_dashboard.html`: additive WEB tab/share controls only.
- New public/owner WEB templates, scoped CSS/JS, and tests `client-hub/tests/test_public_chat_*.py`.
- Update `client-hub/tests/test_kilas_core_contract.py` only to reflect additive WEB channel support,
  retaining invalid-channel/actor cases and simulator protection. Phase 1 implementation not redone.
- This status file and optional dev QA harness under `client-hub/tests/`.
No Finance, root bot, WhatsApp services, accounting, Customers, Jobs, Playbooks, or Finance Bridge edits.

## Checkpoint / test protocol
Use the existing offline subprocess runner. Dependencies are already at `/tmp/kilas-phase1-deps`.
`PYTHONPATH=/tmp/kilas-phase1-deps:/workspace/scratch/2b27258f2497/kilas-works-ai-admin/client-hub python scripts/run_offline_tests.py --only test_kilas_core`: PASS (30 tests).
After each passing milestone update this file and commit to the feature branch only.
Status-bearing commit SHA: `git log -1 -- docs/KILAS_V2_PHASE2_STATUS.md`.

## Milestone plan (1–6 completed; exact next action: step 7)
1. Implement paired additive schema and scoped durable store; run storage tests and checkpoint.
2. Add public routes/opaque visitor credentials and same-origin security; checkpoint.
3. Add injected WEB adapter with durable event claims, safe failures/retry and bounded AI cost; checkpoint.
4. Add WEB Inbox read path; checkpoint.
5. Add WEB-only takeover/reply with in-flight AI fencing; checkpoint.
6. Add minimal owner link controls and mobile public UI; checkpoint.
7. Run Phase 1/2 and applicable existing regressions; safely available dev/browser QA; review scope.

## Availability / limitations
No production deployment, database, or Render changes authorized or attempted.
Browser skill read; advertised Node browser execution tool not currently exposed by tool registry.
No browser QA claim until real browser interaction succeeds. Local PostgreSQL binaries initially absent.
Known baseline Finance FX regression (`50 != 1`) remains protected and outside scope.

## Milestone 1 checkpoint
Completed additive paired 0055 schema, explicit-only installer, tenant-scoped durable store,
hashed visitor identity, atomic event claims/leases, two-attempt interrupted-request recovery,
terminal provider failure, durable rate limits and in-flight takeover fencing.
Files: public_chat/{__init__,schema,store}.py, paired 0055 migrations, test_public_chat_store.py.
PASS: `PYTHONPATH=/tmp/kilas-phase1-deps python scripts/run_offline_tests.py --only test_public_chat_store` (8 tests).
No old migrations executed. Next: implement public visitor routes and security.
PostgreSQL packaged binaries installed under /tmp/kilas-phase2-pg for later isolated validation.
Browser execution tool became available on a later discovery; QA setup remains pending.

## Milestone 2 checkpoint
Current preceding commit: `164bfbd74654724feb4ecc17cbacc93b83871a8a`.
Added public routes, strict Origin/custom-header protection, scoped HttpOnly/SameSite cookie,
visitor CSRF secret, no-store/CSP headers, rollout and per-business channel checks.
Hub exceptions affect only new public_web endpoints; existing Finance owner-session redirect still tested.
Files: public_chat/{security,routes}.py, templates/public_web_chat.html, app.py, test_public_chat_routes.py.
PASS: offline `--only test_public_chat_routes` (6 tests); Phase 1 `--only test_kilas_core` (30 tests).
Next: wire WEB events to the shared processing entry point and actual business knowledge provider.

## Milestone 3 checkpoint
Current preceding commit: `7eb786a935638aadb362c14b7a2b687727da0239`.
Added WEB/visitor contract support without loosening simulator actors; public_chat/adapter.py
uses the same process_message and existing bounded model transport with business-scoped knowledge.
Durable duplicate delivery returns stored terminal state; provider failures are sanitized and do not
spend another call on retry. Forged payload scope and media rejected before model calls.
Files: contracts.py, public_chat/{adapter,routes}.py, test_public_chat_routes.py.
PASS offline `--only test_public_chat` (17 tests) and `--only test_kilas_core` (30 tests).
Next: WEB Inbox read view; then human replies and share controls.

## Milestone 4 checkpoint
Current preceding commit: `29d6ad151bcba395a394ba980437193437ace984`.
WEB tab and paginated WEB conversation view added to existing Inbox. Default WhatsApp route/service
remains unchanged. Owner read APIs require existing membership and never read WhatsApp storage.
Files: public_chat/{owner,store}.py, app.py, routes_client.py, templates/{inbox,web_inbox}.html,
static/{web_chat.css,web_inbox.js}, tests/test_public_chat_routes.py.
PASS offline `--only test_public_chat_routes` (11 tests), including foreign-business rejection
and default WhatsApp service routing. Next: WEB-only takeover/reply and in-flight race tests.

## Milestone 5 checkpoint
Current preceding commit: `9dba0ed348de4dc2a18e40f40c1360653a3dbe49`.
WEB takeover/return and manual replies use scoped short transactions, existing audit_log,
version fencing, and duplicate-safe human reply IDs. Taking over closes pending AI events;
returning to AI cannot resurrect an old reply. UI enables replies only during human handling.
Files: public_chat/{store,owner}.py, web_inbox.html, web_inbox.js, test_public_chat_routes.py.
PASS offline `--only test_public_chat` (21 tests). Next: owner share/open controls and public UI.

## Milestone 6 checkpoint
Current preceding commit: `8cf04cebde51155320450d0e1ac3bdc9529aa914`.
Added owner-authorized, CSRF-protected stable public-link generation and minimal open/copy controls
in existing AI product areas/Inbox. Added standalone responsive customer chat with polling,
safe text rendering, session continuity and persisted pending event IDs for transport retries.
Files: public_chat/owner.py; templates/{_web_share,public_web_chat,web_inbox,inbox,
product_dashboard,assist_entry,client_dashboard}.html; static/{public_web_chat,web_share}.js,
web_chat.css; test_public_chat_routes.py.
PASS offline `--only test_public_chat` (24 tests); Node syntax checks for both new scripts.
Next: final Phase 1/2 regression runs, isolated dev/browser QA and scope review.
PostgreSQL validation blocker: packaged PostgreSQL refuses UID 0; the sandbox cannot change
UID (`setpriv: setresuid failed: Invalid argument`). No PostgreSQL concurrency pass claimed.
No production database, deployment, root bot, Finance or WhatsApp handler modifications.
