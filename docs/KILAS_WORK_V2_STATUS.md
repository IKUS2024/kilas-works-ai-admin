# Kilas Work V2 — review checkpoint

Branch: `feature/kilas-work-real-worker-v2-20261002`.
Base: current remote main `a0851ed` (PR #113 merged). One focused review PR will be opened. **Do not merge or deploy this task.** Production resources, environment, database and data remain untouched.

## Implementation

Work retains the current dark/orange identity and shared Chat/Work navigation. Its sidebar now has Work baru, recent conversations, actual active jobs, separate unread notifications, history and settings. Connections, legacy Automation previews and technical mode/date controls are removed from normal Work. Existing connector/OAuth/approval code and stored connections remain intact; Work does not invoke connector flows.

Questions use the existing metered Chat provider without creating a job. Essential pre-start document/reminder clarification stays conversational. A started job needing input remains WAITING with `waiting_input`, no wake time and no finished artifact; its question is persisted in its original conversation. The reply adds a bounded constraint and replans that same job. Explicit new document requests remain separate jobs.

Jobs are committed before execution. A CSRF-protected, owner-scoped start endpoint claims one due job under the existing lease/revision fences and executes one bounded pass. The browser may request up to three passes; the existing runner/Cron supplies recovery and continuation after the page closes. No unpersisted process/thread, additional queue, WebSocket or new runner infrastructure.

Customer progress comes from persisted events at actual planning/search/writing/file creation/verification boundaries. Visible active pages poll read-only state every three seconds; hidden, idle and terminal conversations stop polling. Focus/visibility refresh uses that same path. Raw execution instructions, planner prompts and arbitrary event diagnostics are not shown. Existing Markdown/XSS behavior and capability-based mobile blur remain.

Natural reminders use existing account timezone settings, server UTC, calendar schedules, jobs, events and Work messages. Supported examples include tomorrow, relative minutes/hours, a named date, next week/month, daily/weekly/monthly schedules and natural edits/pause/resume/cancel. Missing subjects ask one question; no invented reminder content. Each occurrence inserts an idempotent event and message in one fenced transaction with scheduled/actual delivery times. Missed occurrences catch up once; recurring reminders reuse one registered step without weakening other worker step/daily/attempt caps.

Browser timezone is captured on first Work submission when no saved setting exists. Manual settings win on later visits. GPS is requested only after a relevant location request and explicit user action; coordinates must be finite, bounded and fresh, apply to that request only, and never imply a street/city. Ordinary reminders do not request location.

## Artifacts and security

PDF remains the document default. Real DOCX/XLSX/PPTX bytes are produced locally with python-docx/openpyxl/python-pptx. CSV/JSON/Markdown/TXT and real image generation remain. Uploaded images can be edited through the existing image provider and owner/conversation-scoped durable sources. Source files are available from the unified composer; pending attachments can be removed individually. Existing validated PDF/DOCX/TXT/CSV/image limits are reused; Work-only XLSX/PPTX inputs are bounded and extracted as untrusted source text.

Office ZIP/XML validation rejects traversal, macros, ActiveX, embeddings, entities and external relationships. XLSX/CSV reject executable formulas. Files remain private, MIME-validated, byte-bounded and owner-scoped. Research-to-PDF keeps the existing verified evidence path; revisions preserve the earlier file. Coding continues through the existing configured repository sandbox and approval/cost fences.

Supported: public-source research, document/data/deck/image artifacts, source analysis/revisions, reminders/scheduled work and configured sandbox coding. Unsupported: arbitrary cloud browser interaction/login/clicking, connected-account read/send from Work, unconfigured market feeds, unconfigured image providers and unsupported external executors. Work makes no success claim for unavailable capabilities.

Model policy is retained: Luna for ordinary/simple writing; Sol for existing complex planner/coding escalation. Deterministic reminders and file formatting do not need model calls. Existing usage reservations, daily caps, fair-use and QA entitlement expiry are retained.

## Additive migration and future rollout

`0081_kilas_work_push_{sqlite,postgres}.sql` adds only owned push subscriptions and idempotent delivery records. Existing jobs/events/messages/timezone settings are reused. No backfill, data rewrite, destructive SQL or protected-product migration.

Future approved rollout:

1. Verify dependencies and existing 0078/0079/0080 schema are already released.
2. Apply only `0081_kilas_work_push_postgres.sql` in one targeted transaction. It is additive/idempotent. Do not run all historical migrations or reset data.
3. Coordinate the same reviewed commit on Client Hub and the existing Automation Cron runner. No new paid resource, Client Hub upgrade or AI Admin deployment is required.
4. Preserve existing feature flags, OAuth/WhatsApp/payment configuration and secrets.
5. For device push only, configure matching `KILAS_WEB_PUSH_PUBLIC_KEY`, `KILAS_WEB_PUSH_PRIVATE_KEY` and `KILAS_WEB_PUSH_SUBJECT` (a valid `mailto:`/HTTPS contact) on Client Hub and its existing runner. Generate/store keys securely; none are committed. HTTPS, browser support and explicit device permission are required.
6. Without all push configuration, in-app reminders still work and the UI honestly says device push is unavailable.
7. Run controlled real-provider artifact acceptance, live device closed-tab push, and Android keyboard checks before production acceptance.

Push delivery commits its attempt before transport, so uncertain/crashed sends are never blindly retried. This is **at-most-once transport**, not guaranteed delivery: a push can be lost after an ambiguous failure, while the durable in-app message remains. 404/410 disables the invalid subscription. User/account subscription isolation and endpoint/key validation remain mandatory.

## QA checkpoint

Focused Work V2 18, artifacts 22, runner 47, conversation 43, result presentation 18, model/cost 35, Automation 17, connector backend 32 and Work/legacy planner 9 tests passed locally. Additional Chat intent, usage, attachments, PDF, style, top-up, console, tools and normal Chat tests passed. Provider/transport calls are mocked; no live model/email/push or production action is claimed.

The Work V2 responsive pass passed at 320/360/390/820/1440: source attachment removal, four Office/PDF result cards, real bounded start, progress/wait/schedule, actual active count, >=44px key controls, no overflow, coarse-pointer completion/manual focus, no automatic location/push prompts. Screenshots: `%TEMP%/kilas-work-v2-chat-{width}.png` and `kilas-work-v2-detail-{width}.png`.

Existing autonomous-control, Chat/Work conversation, result/Markdown/source safety, shared shell, connection preservation, artifact/revision and composer focus browser journeys passed. The final Work V2 five-viewport confirmation also passed after the last composer changes. Browser emulation verifies focus/viewport behavior; it does not prove a physical Android keyboard or device delivery.

Scoped Impeccable context and detector ran on Work only. Two static flat-type warnings cannot resolve Jinja CSS links; rendered desktop/mobile hierarchy is distinct. No full audit or global design fixes.

Local PostgreSQL is unavailable (loopback connection refused); native additive migration/lease/BYTEA checks and Linux sandbox execution are required CI gates. Protected Finance baseline (4) and Assist connection (9) modules hit existing Windows SQLite reset file-lock errors; their code was not changed. Known broad Master Assist/signup/language/customer and Phase10 browser baseline failures are outside this patch. CI status and final review evidence will be appended before stopping.

**Not yet cleared for deployment.** Remaining review gates: final scoped diff, native PG/Linux sandbox/CI, live provider/device acceptance and explicit deployment authorization.

## Review PR and explicit acceptance answers

Review PR: https://github.com/IKUS2024/kilas-works-ai-admin/pull/115. Current main PR #113 is integrated; the final diff has no normal Chat routing, Finance, Assist, WhatsApp/Meta, pricing or payment implementation changes. `git diff --check` passes. Production remains untouched.

Native PostgreSQL CI passed additive/idempotent 0081, existing lease fencing/BYTEA and concurrent cross-owner push registration. Linux sandbox CI passed. A focused CI assertion expected an exact Work prompt; it now verifies the unchanged base style plus the explicit Work-only capability boundary, and passes locally. Final CI rerun is pending at this checkpoint.

1. **Does “kamu bisa bikin PDF ga?” create a job? No.** It is conversational Q&A.
2. **Does clarification complete a job? No.** Pre-start questions have no job; started jobs wait and resume the same persisted job.
3. **Does “buat company profile Kilas Works” produce a file? Yes, through the real PDF writer and private binary storage.** Verified facts are retained; absent facts are omitted or requested. Automated provider output is mocked; real-provider acceptance remains necessary.
4. **Does “ingatkan aku besok jam 8” use local timezone? Yes.** Browser capture/manual account setting resolves to server UTC. Without a subject, Work asks what to remind about before creating a job.
5. **Can a reminder notify with the tab closed? Yes, when configured and permitted Web Push is supported by that device.** Durable queuing and transport are tested with mocks; real closed-tab device delivery remains an acceptance gate. Delivery is not guaranteed after ambiguous failure.
6. **GPS for ordinary reminders? No.** Only relevant location tasks present an explicit permission action or accept a typed area.
7. **Connections gone from Work? Yes.** Existing backend/OAuth/approval routes and stored accounts remain intact.
8. **Automation/Advanced gone from customer Work? Yes.** Existing scheduling/runner architecture remains behind natural chat requests.
9. **Can Work continue after the browser closes? Yes.** Persisted jobs are claimed by the existing enabled Cron runner under current leases, revisions and limits. No new infrastructure is created.
10. **Can Work interact with arbitrary websites? No.** Public research is supported; interactive cloud browser/login/click automation is intentionally unavailable.
