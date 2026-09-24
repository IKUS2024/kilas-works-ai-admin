# Phase 6 status — IN PROGRESS

## Baseline / prerequisites
- Branch `feature/kilas-core-v2`; baseline `3b870393a11d14705ad7b8630f3b674efee363a8`.
- Remote main inspected: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c` (unchanged).
- All ten requested documents read completely. Previous Phase 1–5 implementations retained.
- Current baseline CI SUCCESS: Phase 2 `36019666766`, Phase 3 `36019666607`, Phase 4 `36019666614`, Phase 5 `36019666603`. Phase 5 workflow includes Phase 1–5 regressions, PostgreSQL and mobile QA. Historical Phase 2 blocker prose is superseded by these results and Phase 3's accepted prerequisite.
- Upstream since Phase 5 completion changes only roadmap (dashboard refresh belongs to Phase 9) and Phase 6 instructions. Exact GitHub objects restored locally after Git fetch stalled; verified tree hashes. No user changes discarded.

## Scope / reuse decisions
- Existing WEB takeover, claim/version fence and durable message store remain authoritative.
- Studied `tenant_followup_service.py` cooldown/count/activity rules and root cron authorization pattern; no imports or edits to legacy WhatsApp follow-up.
- Studied `owner_notifications.py`: its helper immediately attempts WhatsApp delivery. It must NOT be reused for WEB-only attention.
- New default-off `KILAS_OPERATIONS_V2_ENABLED`, existing Core/WEB/Customers/Jobs + tenant package/subscription gates.
- Minimal paired additive 0058 planned: Attention items (resolution history), automation config (bounded toggles), automation runs (idempotency/delivery history). Tenant composite references; explicit installer only, no boot/legacy migration replay.
- Runner is a callable + explicit CLI/owner-CSRF action; no new cron HTTP secret/route, no production cron setup. Deterministic messages only. Short DB locks and operation keys suffice because delivery is a local transactional WEB append, with no network/model call.
- Business -> conversation lock order; recheck mode/version, latest customer activity, valid session/channel, current config/entitlement before delivery. Message + delivered state + audit commit together. Failed delivery rolls back and surfaces attention.
- Human request uses closed Phase 5 signal through deterministic handover service; no model SQL/state setter. Return to AI remains explicit owner action.
- Compact Attention panel in existing AI owner Home, list/resolve and simple automation settings only. No global shell/admin redesign.
- No Finance, invoice/payment/accounting, WhatsApp send/cutover, media AI, production deployment, or Phase 7.

## Milestones
1. Existing patterns + contracts: PASS.
2. Attention state/service: PASS on SQLite.
3. Automation rules/due runner: PASS on SQLite.
4. Phase 5 handover integration: PASS on SQLite.
5. Home Attention UI: PASS on SQLite.
6. Security/idempotency/concurrency/regressions: PASS on SQLite.
7. PostgreSQL/mobile browser QA: pending.
8. Exact scope / COMPLETE: pending.

## Verification / next action
Milestones 1–6 implemented and verified on isolated SQLite. Continue milestone 7 only: paired 0058 PostgreSQL runtime/concurrency and real 390px browser A–E, then final scope review. Phase 6 is NOT COMPLETE until these gates pass.

## Blockers
None outstanding. Use disposable GitHub Actions PostgreSQL/Chromium as in previous phases; never production data/services.

## Milestone 1 checkpoint
- Files: `client-hub/kilas_core/operation_contracts.py`, `test_kilas_operations_contract.py`, this status.
- 2 offline contract tests PASS: closed config, exact booleans, delay 1–168 hours, max 1–3 attempts, closed messages/reasons, unknown actions/URLs rejected.
- Next: implement minimal 0058 pair and tenant-scoped Attention resolution/history.

## Milestone 2 checkpoint
- Milestone 1 local commit: `8dd15e3` (published IDs recorded after synchronization).
- Files: paired `client-hub/migrations/0058_kilas_operations_{sqlite,postgres}.sql`; `client-hub/kilas_core/operation_schema.py`, `operation_access.py`, `attention.py`; `client-hub/tests/test_kilas_operations_store.py`; this status.
- 2 isolated SQLite tests PASS: explicit installer twice preserves Attention; tenant FK rejection; linked Customer resolution; dedupe; owner resolution history; cross-tenant resolution denied; disabled/suspended gates.
- Attention resolution changes only Attention + audit. System writes have NULL actor and WEB_AUTOMATION origin. No automatic schema install. PostgreSQL not yet claimed.
- Next: implement deterministic due scan + atomic WEB delivery runner and bounded config updates.

## Milestone 3 checkpoint
- Milestone 2 local commit: `6b97412`.
- Files: `client-hub/kilas_core/automations.py`, `client-hub/tests/kilas_operations_cases.py`, `client-hub/tests/test_kilas_operations_store.py`, this status.
- 10 SQLite tests PASS (2 Attention/schema + 8 shared automation cases): due delay, cooldown/max attempts, new-customer-message reset/cancel, stale mode generation, four concurrent runners, review once, human fallback, failed-write rollback, READY_FOR_QUOTE dedupe/resolution, tenant/config gates.
- Runner scans 100 conversations/100 Jobs per page and returns explicit cursors; executes at most 100 pending deliveries. Repeated calls drain pending work. CLI accepts explicit business + scan cursors; no cron route or deployment.
- Delivery rechecks entitlement/config/channel/expiry/mode/version/current customer event and foreground processing; terminal message/state/audit are atomic. Failed writes become FAILED + Attention, with no unbounded retries. Defaults send nothing.
- Next: wire closed Phase 5 HUMAN/UNSUPPORTED signals, existing takeover transaction helper, and Job state observer; test before owner UI.

## Milestone 4 checkpoint
- Milestone 3 local commit: `891ed3a`.
- Files: `client-hub/kilas_core/handover.py`, `jobs.py`; `client-hub/public_chat/store.py`, `playbook_adapter.py`; `client-hub/tests/test_kilas_operations_routes.py`, `test_kilas_operations_store.py`; this status.
- Phase 6 store 10 + real routes 3 PASS; Phase 2 store 9 + Phase 5 routes 11 PASS.
- Closed HUMAN/UNSUPPORTED signal creates one Attention request and invokes the original takeover/version/event invalidation logic in the already-fenced completion transaction. No model-generated reply/Job write accompanies takeover. Manual owner reply and explicit return remain functional; return resolves related human Attention only.
- Job state observer runs in the existing Job transaction for immediate ready/completed attention. Phase 5 unresolved field conflicts surface operational Attention without reimplementing extraction.
- Next: compact Home panel, paginated owner list/resolve, and bounded automation settings/run controls.

## Milestone 5 checkpoint
- Milestone 4 local commit: `79b07aa`.
- Files: `client-hub/kilas_core/operation_routes.py`; `client-hub/app.py`; new templates `_attention_home.html`, `_attention_items.html`, `attention.html`, `automations.html`; tiny include additions to `assist_entry.html` and AI-only branch of `product_dashboard.html`; `client-hub/tests/test_kilas_operations_routes.py`; this status.
- Phase 6 routes 6 PASS: Home count/links, owner resolution, cross-tenant GET/POST, CSRF, strict config payload, stale/replayed config, flags/package/subscription and Finance-session isolation. Phase 5 route regression 11 PASS.
- Home reads only, shows count/top 3/direct links. Full list has 10-row pagination and resolved history. Owner resolution does not switch mode or change Job/Finance state. Settings default disabled; manual runner is authenticated/CSRF-protected with bounded pagination cursors.
- A real 404 error-handler issue found by tests was fixed to return a 404 response (no assertions weakened).
- Next: remaining protected-write/failure/security cases, Phase 1–5 regression rerun, then PG/mobile gates.

## Milestone 6 checkpoint
- Milestone 5 local commit: `634a1af`.
- Files: `client-hub/tests/kilas_operations_cases.py`, `client-hub/tests/test_kilas_operations_routes.py`, this status.
- Phase 6 contracts 2, SQLite store 14, owner/WEB routes 7 PASS.
- Added post-message terminal failure rollback, missing WEB review fallback, disabled channel/session expiry, human-mode suppression/system audit identity. SQL authorizer permits only Core/WEB/audit writes; Finance API, legacy send and model spies remain untouched during real runner delivery/retry.
- Phase 1–5 isolated regression PASS: Core 30, WEB routes 18/store 9, Customers 9, Jobs schema 1/store 15/routes 8, Playbooks 12/actions 9/routes 11. Every test file ran in a fresh process.
- No PG/browser pass claimed yet. Next: dedicated loopback PG test runner and synthetic browser harness, publish QA-only workflow, inspect CI and screenshots. No production deployment or scheduling.

## Milestone 7 QA preparation checkpoint
- Milestone 6 local commit: `465b3d5`.
- Files: new `.github/workflows/kilas-v2-phase6-qa.yml`, `client-hub/tests/test_kilas_operations_postgres.py`, `kilas_operations_browser_qa.py`; test-only changes to `public_chat_dev.py`, `playbook_qa_provider.py`; this status.
- QA scripts compile; Phase 6 routes remain 7 PASS; `git diff --check` PASS. Runtime PostgreSQL/browser results pending, not claimed.
- PG runner refuses non-loopback/non-disposable database; validates paired 0058 twice, tenant FKs, legacy row preservation and all shared atomic runner cases.
- Separate loopback-only Phase 6 browser fixture exposes a CSRF/owner-protected synthetic clock, never imported by production. Existing Phase 2–5 harness modes unchanged. New QA workflow also reruns every prior SQLite/PG/mobile gate.
- Next: publish these feature-only checkpoints and inspect Phase 6 Actions execution; fix only demonstrated Phase 6 defects, then inspect screenshots and exact baseline diff.
