# Kilas AI unified Chat / Agent shell

Branch: `fix/kilas-unified-chat-agent-shell-20261002`.
Base: current remote main `87ce1e5`, including merged PR108. Completed conversation/task work is preserved.
Release boundary: one review PR; no automatic merge or deployment.

## Implementation

- Shared `_app_header.html` supplies the Kilas AI header and Chat / AI Agent tabs with the same orange active underline. Normal Chat retains its existing thread options. Agent conversation titles remain small within content. `_agent_nav.html` delegates to the same header on task detail without an unusable drawer button.
- Shared `_sidebar_top.html` supplies branding and an accessible SVG close button. Both modes use existing `ai-shell`, `ai-sidebar`, `ai-history` and composer primitives from `kilas_ai.css`: 270px desktop sidebar, 85vw mobile drawer capped at 310px, matching header heights, font sizes, composer radius and Send targets. Conflicting Agent shell/drawer/composer rules were removed from its stylesheet rather than introducing another CSS file.
- Shared `kilas_ai_shell.js` replaces both drawer implementations. Hamburger, X, backdrop and Escape work consistently. Keyboard focus remains inside the open drawer; the closed mobile sidebar and open-drawer underlying content are inert. Reduced motion uses the existing shared transition rule.
- Normal Chat New Chat and Chat mode links use the existing `attachments=1` route when Automation is enabled, preventing the canonical home redirect from sending them back into Agent. Thread history and lazy thread creation are unchanged. Agent New Chat still uses its existing conversation POST and never stops background work.
- Agent sidebar puts recent conversations before its contextual Active Tasks / Connections / Activity / Settings links. Agent task cards, polling, approvals, feedback and advanced settings retain existing handlers. Advanced settings remain collapsed.
- Both modes retain separate histories. No conversation database is combined. Streaming, Search, attachment processing, copy, regenerate, rename/share/delete, scheduling, Gmail sending/approval and task execution code are unchanged.
- Asset versions are bumped for changed consumers, including existing task detail, to avoid a stale cached Agent stylesheet.

## Focused validation

156 local unit tests PASS:

- `test_kilas_agent_chat_experience.py`: 43.
- `test_kilas_autonomous_agent.py`: 47.
- `test_kilas_ai_automation.py`: 17.
- `test_kilas_ai_connectors.py`: 32.
- `test_kilas_ai_agent.py`: 9.
- `test_kilas_ai_chat.py`: 8, including thread actions and owner isolation.

Five browser suites PASS:

- `test_kilas_ai_shell_browser.py`: shared header/tab active states, measured matching shell/composer dimensions, both histories and New Chat actions, two-way mode switching, task continuity, pause/resume/stop, attachment selection/removal, Search presence, X/backdrop/Escape and console-error checks.
- `test_kilas_agent_chat_browser.py`: streaming, Thinking, duplicate safety, Enter/Shift+Enter, task creation/history/control/detail and overflow.
- `test_kilas_ai_agent_browser.py`: connections, Gmail explicit approval and existing Agent/Automation presentation.
- `test_kilas_autonomous_browser.py`: existing task detail, feedback, pause/resume/stop and long content.
- `test_kilas_ai_browser.py`: existing normal Chat streaming/history, attachments, Search, PDF/image output, copy affordance and supporting existing journeys.

Shell screenshots and no-overflow checks: 320, 360, 390, 820 and 1440px. Existing suites also exercise 768px. Screenshots use isolated synthetic accounts and are saved as `kilas-shell-{chat,agent}-{width}.png`, plus mobile open-drawer captures, in the runner temporary directory. CI uploads them under `kilas-agent-chat-responsive`. Browser fixtures use controlled AI/Google transports; no real mail or production writes are claimed.

Focused Impeccable review: one desktop/mobile inspection batch, one fix batch, one final confirmation. Empty-state typography was aligned to 28px desktop / 23px mobile; shared app title remains 20px and composer input 16px. The scoped detector returned two hierarchy warnings because it cannot resolve Jinja stylesheet URLs; rendered screenshots verify real hierarchy. No full-product audit or global automatic fixes were run.

## Scope / release

Final diff is templates, scoped Kilas AI CSS/JS, focused tests, their existing CI workflow and this checkpoint only. No production Python, schema/migration, Google scope, Finance, Assist, WhatsApp, billing or runner safety changes. No production data, environment or resource mutation.

The existing Autonomous QA workflow includes the new shell browser suite and normal Chat browser regression. All local focused gates pass; remote CI evidence is recorded in the PR. Full repository CI is not claimed green from local checks.

Limitations: Chromium emulation rather than physical-device/mobile-keyboard certification; dark theme only; Google/AI providers mocked in isolated QA. Regular Chat and Agent remain distinct histories and capabilities intentionally. Attachments stay in normal Chat. Canonical `/kilas-ai` entry behavior is unchanged; the explicit Chat tab reaches normal Chat through its existing route.

After PR review and release approval, deploy only `kilas-works-client-hub` at the reviewed SHA. No Cron or AI Admin deployment and no migration are needed. Then verify both modes with an isolated production account. This task does not deploy automatically.
