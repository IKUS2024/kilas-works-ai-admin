# Phase 5 status — IN PROGRESS

## Baseline and scope
- Branch: `feature/kilas-core-v2`.
- Baseline: `a013954956c5aecac4a803a1cb68371abad460a6` (Phase 5 instructions only).
- Remote main inspected: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.
- All nine requested documents read completely before implementation.
- Phase 1–4 complete; current baseline CI: Phase 2 `36015409758`, Phase 3 `36015409844`, Phase 4 `36015409829`: SUCCESS.
- Phase 5 only, WEB only, business/text first. No Finance/payment/accounting writes, WhatsApp cutover, production deployment, media AI, or Phase 6.

## Milestones
1. Understanding contracts + five playbook definitions: PASS (checkpoint commit records this milestone).
2. Pure merge/missing-field engine: PASS (checkpoint commit records this milestone).
3. Safe actions through existing Customer/Job services: PASS in isolated SQLite (not yet exposed to WEB).
4. Public WEB integration: pending.
5. Inbox/Job context: pending.
6. Security/idempotency/provider failure/concurrency: pending.
7. Disposable PostgreSQL + mobile browser QA: pending.
8. Exact scope review + COMPLETE: pending.

## Architecture decisions / resume notes
- Strict bounded model interpretation, deterministic playbooks, deterministic actions, grounded response formatting are separate responsibilities.
- Default-off Phase 5 flag; Phase 1–4 behavior unchanged when disabled.
- Reuse Phase 4 fields and operation records where possible; preserve owner edits.
- Provider runs outside write transactions. Job mutation and WEB event completion must commit atomically after claim-token, conversation-mode/version and Job-version checks. A takeover during inference must suppress BOTH Job writes and replies.
- Server resolves Customer/Job; no model-supplied IDs/actions/status/price/payment facts.
- Existing owner APIs must retain authorization and positive real-user actor validation. Automated audit attribution must explicitly identify system origin, never impersonate an owner.

## Verification
- Baseline current-head CI inspected as above; no Phase 5 pass claimed yet.
- PostgreSQL/browser validation will use disposable synthetic fixtures only.

## Exact next action
Wire milestone 4 WEB completion so the event fence, safe Job action and assistant message share one transaction. Add route-level failure/takeover/retry tests before enabling in QA.

## Blockers
None identified at initialization. Native local PostgreSQL was unavailable in the preceding phase; disposable GitHub Actions PostgreSQL remains the verified alternative.

## Milestone 1 checkpoint
- Initialization commit: `d701c27` (local; published SHA recorded after sync).
- Files: `client-hub/kilas_core/playbook_definitions.py`, `client-hub/kilas_core/understanding.py`, `test_kilas_playbooks.py`, this status file.
- Offline `test_kilas_playbooks.py`: 5 tests PASS. Closed enums/keys, duplicate JSON keys, malformed/oversized output, evidence presence, prohibited fields/actions, quantity validation, immutable result, category mapping covered.
- These are synthetic extraction-contract tests, not a claim of live model semantic accuracy. No provider, application route or database behavior changed.

## Milestone 2 checkpoint
- Milestone 1 local commit: `f828201` (published SHA recorded after sync).
- Files: `client-hub/kilas_core/playbooks.py`, `test_kilas_playbooks.py`, this status file.
- Offline `test_kilas_playbooks.py`: 11 tests PASS. Five workflows, conditional delivery location, logistics alternative volume/dimensions, known facts, correction/conflict/ambiguity, durable uncertainty, separate-request deferral, lifecycle restrictions, business redirect covered.
- Missing details are deterministic. Unresolved contradictions retain the previous fact and a clarification marker. No automatic lifecycle reversal or owner-state advancement. No runtime routes/DB/Finance/WhatsApp changes.

## Milestone 3 checkpoint
- Milestone 2 local commit: `64d93a6` (published SHA recorded after sync).
- Files: `client-hub/kilas_core/jobs.py`, `client-hub/kilas_core/actions.py`, `client-hub/tests/kilas_playbook_cases.py`, `client-hub/tests/test_kilas_playbook_actions.py`, this status file.
- Offline action tests: 7 PASS; existing Phase 4 store 15 and routes 8 PASS.
- Existing Job service extracted transaction-bound private helpers; public real-user actor validation retained. System audit has NULL user plus explicit WEB_PLAYBOOK origin. Tenant references, version checks, operation records and lifecycle still enforced by Jobs.
- Existing bounded JSON holds workflow, facts, missing/uncertain details. No migration added. Snapshot comparison protects owner edits. Ambiguous/multiple/finished requests defer to owner. Create+transition rolls back together on failure.
- Runtime integration still pending; these private helpers are not a new public endpoint.
