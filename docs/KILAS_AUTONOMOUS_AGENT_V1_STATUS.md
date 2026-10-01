# Kilas Autonomous Agent V1

Branch: `feature/kilas-autonomous-agent-v1-20261002`, based on remote main `f3b48b62b3c0d2d77eb196e8ebd0233de67bc5e9` (Google send-only release retained).

## Review candidate, not deployed

Additive migration `0078_kilas_autonomous_agent_{sqlite,postgres}.sql` creates five job/step/event/artifact/approval tables. Explicit checksum-protected PostgreSQL release helper only; ordinary production boot does not apply it. `KILAS_AI_AUTONOMOUS_ENABLED` defaults off. No production environment, resource, schema or data changes have been made. This task must end with one PR; do not merge or deploy.

Existing Automation runs first, then a small autonomous pass. Jobs persist mode, validated plan, constraints, checkpoint, wake time, revision, attempts, failure/replan budgets, lease token and expiry. PostgreSQL uses row locks/SKIP LOCKED; SQLite uses BEGIN IMMEDIATE. Token + revision fencing prevents stale results after recovery, pause, stop or feedback. One step per job claim, at most three jobs per tick, bounded HTTP/subprocess work. Paused jobs retain in-flight lease until release/expiry; resume cannot overlap the old worker. Verified completed steps are preserved on replans. Active job limit20, overall step cap24, attempts3, failure cap3, automatic replan1, user replan3, daily executed-step guard100 using existing QA exemption. All model/search calls use existing quota/cost reservations; public pricing unchanged.

Workers: metered AI text; source-backed WEB; quiet condition WATCH; non-destructive txt/md/json/csv artifacts; local allowlisted CODE snapshots/inspection/validated full-file patches/real diffs. Code test execution requires Linux bubblewrap with network, host credentials and application paths absent; CPU/memory/process/file/output/time caps. No sandbox means a truthful capability wait. No repository is implicitly permitted. Market provider is an injectable read-only interface; absent provider means WAITING with provider_not_configured. External push/merge/deploy/publish adapters are deliberately unavailable: exact-payload approval does not manufacture a capability. Gmail remains on its separate existing explicit send approval flow and its exact three OAuth scopes.

Agent Chat can create/control server jobs. Optional mode controls support one-shot, continuous, condition watch, recurring and scheduled UTC start. Existing ordinary schedules still use Automation. Task cards/detail expose progress, current step, wake, concise events, results/downloads, pause/resume/stop/feedback and unread acknowledgment. No model chain-of-thought or internal metadata is exposed. In-app notification adapter is durable; push/email delivery infrastructure is deferred.

## QA checkpoint

Local temporary Python3.12 with isolated dependencies (including Windows timezone data): autonomous35 PASS; existing Agent9 PASS; existing Automation17 PASS; existing Connectors32 PASS. Chromium task UI at1440/820/390/320 PASS: controls, feedback, unread, no page horizontal overflow. PostgreSQL concurrency/additive rehearsal and actual Linux sandbox tests are required in CI and pending. Focused CI workflow added; broad repository suite is not being run locally. More regression checks and final diff review are pending. No production claim is made.

Further local regression evidence: tools12, Chat8, foundation5, usage5, attachments6 PASS. Existing Finance boundary4 and Assist connection9 tests cannot reset their open SQLite fixtures on Windows (WinError32); unchanged test fixtures will be evaluated on Linux CI. Impeccable scoped detector returned two typography suggestions because it cannot resolve Jinja CSS links; rendered mobile screenshot shows distinct heading/body hierarchy. No global style changes made.

## Release limitations

Do not claim unrestricted 24/7 execution. Work continues across runner ticks within saved budgets; continuous/recurring execution stops at the total step cap. Condition checks are quiet until matched; missing adapters remain visible waits. No broker/trading, social publishing, automatic Gmail, deployment, GitHub write credentials, new paid resource or production activation. Production review must separately assess the migration, feature flag, configured credential-free coding snapshots and sandbox availability. Local Windows cannot execute Linux sandbox tests; CI must establish those actual results.

## PR #107 checkpoint

Single draft PR: https://github.com/IKUS2024/kilas-works-ai-admin/pull/107. Initial CI run36916749469 passed focused42-at-next-head/41-at-initial-head, task+existing Agent browser, PostgreSQL additive/claims; existing Automation boundary job110552485138 passed Chat/Search/image/PDF/usage/Finance/Assist. Sandbox job failed because CI-selected Python was outside the mounted system directories. Existing Automation PostgreSQL job failed on a UTF-8 BOM in new0078 SQL. Both corrected; PostgreSQL coverage now also completes a real FILE step and checks its artifact. Final-head checks pending.

Review also caught ephemeral Cron filesystem loss: CODE now saves bounded original/work snapshots as internal artifacts and rehydrates them after /tmp is lost. These contain sanitized allowlisted source only, have a20KB durable snapshot cap, and are hidden from owner artifact lists. New focused test removes the workspace between patch and diff ticks and verifies the actual patch survives. Autonomous42 local PASS. This V1 supports small credential-free snapshots; larger repositories truthfully hit the workspace cap. No production mutation.

At runtime head71e4f3f, focused job110555460081, PostgreSQL job110555460160, and real sandbox job110555460222 PASS in run36917642854. Sandbox proof:4 actual tests,0 failures/errors/skips; includes real success/failure exit capture, absent production environment and absent host application mounts. Process-count limit128 permits sandbox startup on shared CI while remaining bounded. Autonomous44 passed at that head. Final review added paused-feedback/resume replan coverage (autonomous45 local PASS), preserving existing Automation pause/resume routing and treating “Stop setelah test pass” as a saved constraint instead of stopping immediately. Final runtime-head CI pending this follow-up.

Final market boundary: providerless market-condition jobs receive a deterministic capability-wait plan without a model call; market WATCH cannot fall back to search-generated quotes. Focused47 local PASS after these two additional checks. Final candidate is frozen pending CI. The exact migration has no BOM or trailing whitespace; final diff does not change historical SQL, Finance/Assist implementation, Google scopes/actions, WhatsApp, billing or production configuration.

## Final runtime verification — fcb09df

Runtime commit: `fcb09dfcc601c8cb2169f12d1db1da180e54ce42`. Remote main rechecked: unchanged `f3b48b6`. Clean scoped diff and `git diff origin/main --check` PASS. Production remains unchanged; migration0078 NOT applied, flag NOT enabled, PR NOT merged, no deployment/resource/data/configuration mutation.

All4 autonomous jobs PASS in run36918624322: focused110558769815, real sandbox110558769367, PostgreSQL110558769822, browser110558769681. All4 existing Automation jobs PASS in run36918624222: focused110558768993, browser110558769286, boundaries110558769330, PostgreSQL110558769349. Existing Connector focused110558770064, browser110558769715 and PostgreSQL110558769346 PASS; baseline comparison remains separate.

Exact commands/counts (run each from repository root with Python3.12):

| Command (prefix `python client-hub/tests/`) | Passed | Failed/errors |
| --- | ---: | ---: |
| test_kilas_autonomous_agent.py |47|0|
| test_kilas_autonomous_code_sandbox.py (Linux bubblewrap required) |4|0|
| test_kilas_ai_agent.py |9|0|
| test_kilas_ai_automation.py |17|0|
| test_kilas_ai_connectors.py |32|0|
| test_kilas_ai_tools.py |12|0|
| test_kilas_ai_chat.py |8|0|
| test_kilas_finance_baseline.py |4|0|
| test_assist_connections.py |9|0|
| test_kilas_ai_attachments.py |6|0|
| test_kilas_ai_pdf.py |4|0|
| test_kilas_ai_usage.py |5|0|

Total157 distinct focused unit/regression tests PASS,0 failures/errors/skips in these CI files. Additional procedural checks: `test_kilas_autonomous_postgres.py` PASS (additive/idempotent migration, concurrent claims, expired-lease fencing, actual FILE completion/artifact, terminal stop); `test_kilas_autonomous_browser.py` PASS at1440/820/390/320 with controls/feedback/unread and no overflow. Existing Automation/Agent/AI Chromium journeys and additive schema checks PASS. Local foundation5 also PASS separately. Scoped Impeccable suggestions were verified against rendered type hierarchy; no full audit or global design change.

Broader automatically triggered workflows are not claimed green: master Assist retains the pre-existing billing redirect (302 vs200) and training language (None vs forced_language=en) failures; CRM cleanup passed on this candidate. Broad Finance/Phase9/10 suites may still be running or retain documented pre-existing assertions. These are outside the focused task and no Finance/Assist code was edited to satisfy them. Relevant scoped boundaries above are green.

Implementation is ready for production review with the documented V1 limits, **not approved for activation/deployment by this task**. Market provider, external publishing/GitHub writes/deployment, richer media and push/email notifications remain unavailable adapters. Coding supports only explicit credential-free small source snapshots (20KB durable snapshot), and test execution additionally requires an OS sandbox. Re-enable a capability through a reviewed adapter and replan affected waiting tasks; never infer success from an approval alone. Persistent runner continuation, lease recovery, browser independence and owner controls are tested, but execution is bounded rather than unrestricted24/7.
