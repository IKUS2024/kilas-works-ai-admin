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
