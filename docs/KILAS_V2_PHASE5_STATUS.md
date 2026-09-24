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
4. Public WEB integration: PASS in isolated SQLite; default-off.
5. Inbox/Job context: PASS in SQLite route tests.
6. Security/idempotency/provider failure/concurrency: PASS on SQLite; PostgreSQL pending.
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
Implement and run milestone 7 disposable PostgreSQL runtime/concurrency and real Chromium mobile A–D flows; inspect CI/artifacts. Do not mark COMPLETE until these and exact diff review pass.

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

## Milestone 4 checkpoint
- Milestone 3 local commit: `e484d6d` (published SHA recorded after sync).
- Files: `client-hub/public_chat/adapter.py`, `client-hub/public_chat/playbook_adapter.py`, `client-hub/public_chat/store.py`, `client-hub/tests/test_kilas_playbook_routes.py`, this status file.
- Offline Phase 5 route tests: 6 PASS; Phase 2 store: 9 PASS.
- Default-off `KILAS_PLAYBOOKS_V2_ENABLED=true` also requires Customers/Jobs and existing Core/WEB tenant entitlement/channel gates. Exactly one bounded extraction provider call, no hidden retries.
- Completion locks business then conversation; the existing claim-token/mode/version fence runs before safe action. Job writes + audit + assistant reply + event completion share one transaction; expired leases cannot write. A concurrent owner edit causes clarification, not overwrite.
- Disabled flag retains legacy WEB provider behavior. Provider/action failures produce no Job or success reply. No schema/deployment/WhatsApp/Finance changes.

## Milestone 5 checkpoint
- Milestone 4 local commit: `22cba8e` (published SHA recorded after sync).
- Files: `client-hub/kilas_core/jobs.py`, `client-hub/kilas_core/job_routes.py`, `client-hub/templates/_jobs_panel.html`, `client-hub/templates/job_form.html`, `client-hub/tests/test_kilas_playbook_routes.py`, this status file.
- Phase 5 routes: 7 PASS; action tests 7 PASS; Phase 4 routes 8 PASS.
- Owner context shows linked Job/workflow, operational facts, missing details and status alongside existing Customer and AI/Human mode. Job form exposes relevant workflow fields only; existing non-playbook forms retain their Phase 4 fields.
- Manual edits preserve server-owned workflow metadata and recompute missing details; human-mode manual editing remains available. Forged workflow form key rejected. Templates escape facts; no raw model output/prompt is rendered.

## Milestone 6 checkpoint
- Milestone 5 local commit: `60667fb` (published SHA recorded after sync).
- Files: `client-hub/tests/kilas_playbook_cases.py`, `client-hub/tests/test_kilas_playbook_actions.py`, `client-hub/tests/test_kilas_playbook_routes.py`, this status file.
- Phase 5 SQLite: pure 11 + actions 9 + routes 11 PASS.
- Current implementation regressions: Phase 1 30, Phase 2 routes 18/store 9, Phase 3 9, Phase 4 schema 1/store 15/routes 8 PASS (isolated offline processes).
- Four concurrent completion workers create exactly one Job and one assistant reply. Stale/reclaimed/expired events and takeover->AI toggles cannot invoke action callbacks.
- Real route tests cover retry no extra provider, later same-Job update, stale owner edit, flag revocation, unknown model action tags, provider/action rollback, tenant forged references, human suppression, owner form compatibility, booking date/time reuse and business-only redirect.
- SQLite authorizer permits only WEB/Core/audit/usage writes; Finance methods and WhatsApp send spies remain unused. No production data/service touched.
