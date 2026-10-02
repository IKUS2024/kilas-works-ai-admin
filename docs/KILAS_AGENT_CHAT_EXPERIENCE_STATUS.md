# Kilas Agent chat experience — review candidate

Branch: `feature/kilas-agent-chat-experience-20261002`.
PR: https://github.com/IKUS2024/kilas-works-ai-admin/pull/108
Base: latest remote main `86511f21ab16a8141708aab8f78485e3162d50c8` (Autonomous V1, PR107).

## Production inspected, not changed

Read-only Render inspection confirmed Client Hub deployment `dep-davh22e7bikc73e1iuc0` LIVE on that base, with auto-deploy OFF. No merge, deployment, environment modification, resource creation, migration or production QA write was performed for this task.

## Conversation and task lifecycle

- Additive `0079_kilas_agent_conversations` supports PostgreSQL and SQLite. Existing Agent messages are assigned to one historical conversation per owner without deleting or rewriting their content. Existing jobs retain their state and have a nullable origin; they remain accessible in account-wide Active Tasks.
- New Chat creates an independent conversation, clears only transient chat routing/preview context and preserves background jobs, leases, checkpoints, approvals, connections and persisted Automation. Messages are owner-scoped and conversation-scoped. Rename derives no model cost; initial titles use the first user message.
- `/kilas-ai` opens Agent chat when the existing Automation and Autonomous runtime flags are enabled. `/kilas-ai?attachments=1` preserves the original attachment-capable chat and all its threads/tools. Existing Automation-result continuation retains its prior path. Agent navigation presents Chat rather than a separate technical AI Agent product.
- Recent sidebar history is limited to 20 conversations; message pages are limited to 60 with an older-message cursor. Context uses 12 messages. Task loading prioritizes active jobs plus eight recent terminal results, capped at 30. Detail loads bounded steps/events/artifacts only when opened.
- Older conversations remain reachable through a paginated history view (20 per page). Owner-scoped NULL-only association repair keeps late messages from an old Hub instance readable during a rolling deployment. Repeat SQLite/PostgreSQL initialization preserves already-linked messages and jobs.
- Jobs store origin conversation and verified calendar schedule metadata; chat/task navigation works both ways. Durable owner-bound operation keys reject duplicate submissions, including after an uncertain network result.

## Routing and schedules

- Ordinary questions use the existing Kilas AI FAST streaming provider and metering, without creating a task or calling the Automation planner. Normal chat can continue after connector interaction.
- Natural one-shot, continuous, condition-watch, recurring and scheduled requests use conservative deterministic inference. Existing structured Automation assistance remains available for ambiguous legacy schedules/edits. Missing clock or target prompts clarification rather than inventing values.
- WIB is the default. Explicit supported timezones are respected. Calendar recurrence uses the existing timezone-aware next-occurrence calculation after a completed cycle, preserving daily/weekly clock times rather than drifting by completion time. Internal storage remains UTC.
- Continuous market watches retain real-provider validation. Bitcoin/BTCUSDT aliases cannot bypass the market boundary via web watches. No quotes/signals are fabricated; unavailable market data is stated explicitly.
- Chat controls support pause/jeda dulu, lanjut/resume, stop/berhenti and constraint feedback. Multiple unfocused tasks require selection. New Chat does not control jobs. Runner leases, fencing, attempt/step limits, sandbox restrictions and approval payload binding are preserved.

## Scoped UI and Impeccable pass

- Existing dark surfaces, orange accent and typography remain the visual authority. Two-column desktop chat, recent conversations, compact task groups and mobile drawer replace the technical runner layout only in Agent.
- Composer appends the user message immediately, streams ordinary answers, prevents duplicate sends, shows accessible truthful preparation/Thinking feedback and supports Enter / Shift+Enter. Failure preserves the submission key and asks the user to reopen the chat before retrying an uncertain result.
- Advanced settings stay collapsed. Scheduling labels use WIB and human durations. Task cards show verified status/progress, current step, activity/wake times and existing controls. Empty plans say the steps are being prepared instead of claiming zero-of-zero progress.
- Dedicated Impeccable context/polish/audit guidance and one scoped mechanical scan were used. Two `flat-type-hierarchy` warnings are detector limitations: Jinja stylesheet URLs cannot be resolved statically. Rendered screenshots/computed layout show 20–24px chat headings, 28px mobile empty-state headings and 16px composer text. No detector-driven global fixes were made.
- Verified UI defects corrected: crowded mobile navigation became a drawer with Escape/focus handling; double textarea focus treatment became one clear enclosing accent focus state; technical UTC/seconds/server phrasing became human presentation; unrelated legacy task delete confirmation was retained after the script replacement.
- Chromium synthetic-data interaction checks cover 320/390/820/1440px, touch emulation, keyboard, reduced motion, long content and no horizontal overflow. This is not a physical-device or WCAG certification. The product currently supports the existing dark theme only.

## Validation checkpoint

- Local: 43 focused chat tests, 47 existing Autonomous tests, 9 Agent, 17 Automation and 32 Connector tests PASS (148 unit tests). Coverage includes Q&A after connector interaction, repeated schema initialization, late legacy messages and paginated history.
- Three browser suites PASS: new chat/streaming/Thinking/duplicate prevention/history/task continuity; existing Agent connections/Gmail approval layout; existing Autonomous pause/resume/feedback/stop/unread/detail.
- Initial PR head `8fecb06b52995c5b4327ef9322648f4eb03bf44b`: Autonomous workflow `36958307796` all four jobs PASS: focused `110686139538`, browser `110686139470`, code sandbox `110686139497`, PostgreSQL `110686139295`. Both targeted 0078 and 0079 native migration rehearsals passed.
- Final implementation SHA `4d39f18f2325d010daaa5e79bc66ffca39182308`: Autonomous QA `36959259040`, Automation QA `36959259068` and Connectors QA `36959259164` all PASS. This includes native PostgreSQL migration/backfill/repeated initialization, Linux bubblewrap code sandbox, three browser suites and existing Agent/Automation/Connector regressions. Responsive screenshot artifacts are attached to Autonomous QA.
- Additional automatically triggered checks: Session Timeout, Phase 6 and Phase 8 PASS. Master QA PostgreSQL release and root-bot runtime PASS, but its Assist regression job fails existing pricing redirect and training-language assertions. Phase 9 and Phase 10 browser jobs fail existing Finance entry selectors (`Mulai Kilas Finance` / `Mulai Sekarang`); Phase 10 migration rehearsal PASS. Connector baseline job `110689060626` independently reproduces these same failures on unmodified main. They were not ignored or fixed by changing protected Finance/Assist code. Phase 7 remains running at this checkpoint; no all-repository-green claim is made.
- An earlier intermediate Master QA run also had an intermittent unchanged CRM fixture failure; it is absent from the final implementation run. Final diff review and `git diff --check` PASS. No Finance/Assist implementation, historical migration or Google scope file is changed.

Scoped Impeccable technical review: accessibility 3/4, performance 3/4, responsive 4/4, theming 3/4, implementation integrity 4/4 (17/20, provisional). Accessible labels/focus/status, reduced-motion behavior and four emulated viewport sizes were checked; this score is not a compliance certification. Existing palette literals remain intentionally scoped rather than rewriting a global design system. The two static detector hierarchy warnings were verified as Jinja resolution false positives, not confirmed UI defects.

## Scope and limits

Finance, Assist, WhatsApp routing, Google OAuth configuration, connector executors, pricing/billing and production customer data are unchanged. Google remains exactly `openid`, `userinfo.email`, `gmail.send`; sending still requires the existing explicit approval. Focused Connector tests use controlled transports, not live Gmail delivery.

The existing attachment-capable chat at `/kilas-ai` is preserved and linked from Agent; this patch does not rebuild attachment/image/PDF tools inside the Agent composer. Natural-language inference is conservative rather than a general schedule-language solver. Ambiguous unsupported expressions can require clarification. Continuous work remains bounded by the original step/attempt/usage caps. Market/provider and unsupported external publishing limits remain real.

## Required production steps after review (not executed)

1. Review PR108 and require its relevant focused/regression checks; merge only after separate release authorization.
2. Apply only targeted `0079` via `kilas_ai.agent_conversation_schema.apply_release()` against production PostgreSQL using reviewed candidate source. It uses an advisory lock and checksum record. Alternatively the existing startup hook uses `KILAS_AI_AGENT_CONVERSATION_SCHEMA_APPLY=true` for one controlled release; disable that flag after confirmed application. Do not replay historical migrations or reset data.
3. Deploy the existing Automation Cron to the reviewed SHA after schema application, then Client Hub to the same SHA. Calendar recurrence adds a small runner behavior change, so the existing Cron is affected. No new resource, AI Admin deployment, Client Hub upgrade or infrastructure is required. Preserve existing runtime flags and credentials.
4. Verify New Chat/history, ordinary Q&A, one-shot/recurring/scheduled WIB work, task-origin links, controls, Gmail approval and mobile layout with an isolated account. Confirm active tasks survive switching chats/browser sessions, and Finance/Assist remain unchanged.

Current stop condition: review PR only. Do not merge or deploy automatically.
