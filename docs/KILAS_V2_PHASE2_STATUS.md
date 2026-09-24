# Kilas V2 Phase 2 status

Status: IN PROGRESS — milestone 2 public visitor routes complete; core AI path next.
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
- Existing `client-hub/templates/inbox.html`, `product_dashboard.html`: additive WEB tab/share controls only.
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

## Remaining / exact next action
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
