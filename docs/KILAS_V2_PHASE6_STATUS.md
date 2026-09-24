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
2. Attention state/service: pending.
3. Automation rules/due runner: pending.
4. Phase 5 handover integration: pending.
5. Home Attention UI: pending.
6. Security/idempotency/concurrency/regressions: pending.
7. PostgreSQL/mobile browser QA: pending.
8. Exact scope / COMPLETE: pending.

## Verification / next action
Implement closed reasons/rules and config validation, run focused tests and commit milestone 1. Then implement additive state and Attention service. No Phase 6 runtime pass claimed yet.

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
