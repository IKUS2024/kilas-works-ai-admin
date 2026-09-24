# Kilas V2 Phase 2 status

Status: CHECKPOINT — milestones 1–6 complete; milestone 7 BLOCKED/PARTIAL. NOT COMPLETE.
Branch: `feature/kilas-core-v2`.
Starting remote SHA: `2849db26b184763d2f5404dbd0758e88b857c4b0`.
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

## Remaining / exact next action
RESUME FROM STATUS FILE. Do not redo milestones 1–6 or Phase 1.
1. Obtain a disposable non-root PostgreSQL test environment. Apply only additive 0055 on a
   schema-only fixture, then verify tenant FKs, concurrent claims/rate limits, retry fencing and
   human takeover. Do not use production credentials or run the legacy migration chain.
2. Run existing Inbox/tenant regressions against a reviewed schema-only test fixture. The stock
   tests invoke `db.init_schema()` and replay destructive legacy migrations, so they were not
   executed. Do not weaken assertions or present the new focused tests as those existing suites.
   Relevant files: `client-hub/tests/test_inbox_unification.py`, `test_inbox_media_webhook.py`,
   `test_multi_tenant_runtime_safety.py`, `test_tenant_owner_media_and_isolation.py`.
3. Use a safely reachable dev environment for the eight-step mobile browser QA in
   ASTRA_PHASE2_PUBLIC_CHAT.md. The disposable harness is ready at
   `client-hub/tests/public_chat_dev.py`; no live AI credentials/outbound channels are used.
4. Rerun Phase 1/2 tests, review the exact scope diff, then mark COMPLETE only when the remaining
   required gates pass. Stop before Phase 3. No production deployment.

## Availability / blockers
- PostgreSQL binary installed outside the repo but cannot initialize as UID 0. Standard UID switch
  fails (`setpriv: setresuid failed: Invalid argument`). No PostgreSQL pass claimed.
- Browser skill/API setup succeeded. Local Flask dev server started on 127.0.0.1:8765;
  cloud browser navigation was denied with `net::ERR_BLOCKED_BY_CLIENT`. No browser/mobile QA
  pass or screenshots claimed, and no tunnel/public deployment attempted. Dev server stopped.
- Existing regression suites need a safe schema-only fixture because their bootstrap replays the
  legacy migration chain. That prohibition was preserved.
- Known baseline Finance FX failure (`50 != 1`) remains protected and unchanged; see Phase 1 status.
- No production deployment/database access, Render setting changes or WhatsApp sends.

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

## Milestone 7 passing partial checkpoint
Current preceding commit: `f13e3b04793a11ffbc84bd04d14c26e4d7a49591`.
Current status-bearing commit: obtain with `git log -1 -- docs/KILAS_V2_PHASE2_STATUS.md`.
Added separate paid AI subscription gate using existing read-only subscription_service, fail-closed
on missing/suspended subscription or lookup failure. No subscription/billing/Finance code changed.
Fenced an expired older event before a new message starts so a late older worker cannot append
an out-of-order answer. Added race and negative side-effect tests, with SQL authorizers on both
hub and dedicated WEB connections plus Finance/WhatsApp spies. Moved Assist share controls outside
its two-column primary-action grid. Added loopback-only disposable QA harness, never production-imported.

Validation at this checkpoint:
- `PYTHONPATH=/tmp/kilas-phase1-deps python scripts/run_offline_tests.py --only test_kilas_core`:
  PASS, 30 tests across 2 isolated files; Phase 1 remains COMPLETE and unchanged except additive WEB contract.
- `PYTHONPATH=/tmp/kilas-phase1-deps python scripts/run_offline_tests.py --only test_public_chat`:
  PASS, 27 tests (18 routes/security/integration + 9 durable SQLite store).
- `node --check client-hub/static/public_web_chat.js`, `web_share.js`, `web_inbox.js`: PASS.
- `python -m compileall -q client-hub/public_chat client-hub/tests/public_chat_dev.py`: PASS.
- Disposable harness Flask test-client smoke: PASS, actual `/dashboard?product=brain` redirect
  to Assist dashboard, owner share action, public chat page; this is HTTP/template validation,
  not browser/mobile/live-provider QA. External model transport and unrelated dashboard reads stubbed.
- `git diff --check`: PASS. Browser/PostgreSQL/existing migration-based regression gates: BLOCKED above.

Schema rationale: legacy Inbox identity is phone-based; new WEB tables avoid fake phone keys and
WhatsApp side effects. Paired additive 0055 creates only channel, conversation, event, message and
rate-limit tables with tenant composite FKs. Explicit installer reads only 0055; no auto-boot migration.
Only disposable SQLite fixtures have had this schema applied. PostgreSQL file is not yet runtime-certified.
Rollout remains default-off. Requires both Core gate/allowlist, WEB gate, eligible AI package,
ACTIVE/GRACE subscription, business knowledge and server-created enabled channel. Rollback is disable
`KILAS_WEB_CHAT_ENABLED`; retain data. No production configuration changes performed.

## Exact Phase 2 changed files at checkpoint
Baseline: `2849db26b184763d2f5404dbd0758e88b857c4b0`.
- `client-hub/app.py`
- `client-hub/kilas_core/contracts.py`
- `client-hub/migrations/0055_public_web_chat_postgres.sql`
- `client-hub/migrations/0055_public_web_chat_sqlite.sql`
- `client-hub/public_chat/__init__.py`
- `client-hub/public_chat/adapter.py`
- `client-hub/public_chat/owner.py`
- `client-hub/public_chat/routes.py`
- `client-hub/public_chat/schema.py`
- `client-hub/public_chat/security.py`
- `client-hub/public_chat/store.py`
- `client-hub/routes_client.py`
- `client-hub/static/public_web_chat.js`
- `client-hub/static/web_chat.css`
- `client-hub/static/web_inbox.js`
- `client-hub/static/web_share.js`
- `client-hub/templates/_web_share.html`
- `client-hub/templates/assist_entry.html`
- `client-hub/templates/client_dashboard.html`
- `client-hub/templates/inbox.html`
- `client-hub/templates/product_dashboard.html`
- `client-hub/templates/public_web_chat.html`
- `client-hub/templates/web_inbox.html`
- `client-hub/tests/public_chat_dev.py`
- `client-hub/tests/test_public_chat_routes.py`
- `client-hub/tests/test_public_chat_store.py`
- `docs/KILAS_V2_PHASE2_STATUS.md`

Scope review: only the listed 27 files changed. Existing Finance files, accounting services,
DB helpers, legacy migrations, root bot and WhatsApp services remain byte-for-byte unchanged.
Default Inbox still dispatches to the original WhatsApp handler (tested). The only existing
Finance-session hook addition exempts public_web endpoints; the original simulator Finance lock
still returns 303 (tested). No Customers, Jobs, Playbooks, Finance Bridge or cutover implementation.

Milestones committed/published only on `feature/kilas-core-v2`:
1. Schema/storage: `164bfbd74654724feb4ecc17cbacc93b83871a8a`
2. Visitor routes: `7eb786a935638aadb362c14b7a2b687727da0239`
3. Core adapter: `29d6ad151bcba395a394ba980437193437ace984`
4. Inbox read: `9dba0ed348de4dc2a18e40f40c1360653a3dbe49`
5. Human replies: `8cf04cebde51155320450d0e1ac3bdc9529aa914`
6. Owner share/UI: `f13e3b04793a11ffbc84bd04d14c26e4d7a49591`
7. Passing partial QA checkpoint: `git log -1 -- docs/KILAS_V2_PHASE2_STATUS.md`.
