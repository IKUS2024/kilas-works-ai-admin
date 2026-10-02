# Kilas AI Agent response and result polish — 2026-10-02

Branch: `fix/kilas-agent-response-result-polish-20261002`.
Base: latest remote main `4ce2f8cdf4b504cbbe0a616e43bf991735f2527a` (unified shell PR #109).
Release state: implementation complete; focused PR for review. **No merge or deployment is authorized by this task.**

## Root causes and changes

- Stored Agent answers and SSE completion used plain text, while normal Chat owned a private DOM Markdown renderer. Extracted one shared renderer for normal Chat, stored/streamed Agent answers and task results. User messages remain plain text.
- Task detail rendered all written results as raw `pre` and placed execution steps first. It now presents the last successful synthesis (or last successful written/search output), downloadable artifacts and compact sources before collapsed **Detail pekerjaan**. Actual coding logs/diffs remain preformatted. Failed/unverified steps are never the primary result.
- Research command recognition missed `cari` variants. Action-oriented research now uses the existing autonomous route. Ordinary questions remain Q&A; existing connector/reminder and scheduling boundaries remain intact. Broad unspecified trends receive Indonesia/current public-source guidance without a platform question. Explicit geography is retained.
- Agent Q&A inherited normal Chat guidance without Agent-specific presentation instructions. Added concise, natural Agent guidance through the existing provider adapters. Research planning and synthesis receive a short source-backed digest standard; original untrusted-data instructions remain in place. Ordinary Q&A cannot claim live research, while synthesis can use verified worker context.
- Creation and plan installation both sliced raw instructions into titles. A deterministic utility now removes command filler and scheduling tails, caps titles at eight words/about 55 characters, and truncates only at a word boundary. Legacy titles are improved on presentation without rewriting historical records or using another model call.
- Step headings exposed full internal instructions. Display labels now describe the work; execution instructions and persisted outputs are unchanged and available in secondary disclosures.
- Completed cards retained progress metadata and long instructions. They now show a concise title, terminal status/time, short result hint and **Buka hasil**. Failures use a red status and short reason; stopped tasks are neutral.
- Sources displayed long URLs. Source presentation validates HTTP(S), rejects credentials/control characters, deduplicates, strips tracking query fields, shows eight sources initially and up to 32 with a disclosure. Known bare citations become titled links; original stored outputs stay intact.
- Chat rename uses an accessible ellipsis control with the same existing form. Advanced settings remain collapsed. Existing dark theme, orange accent, navigation, composer and controls remain intact.

## Security and scope review

Markdown uses explicit DOM nodes and `textContent`; no model HTML is injected with `innerHTML`. HTML/script/image payloads remain harmless text. Only validated HTTP(S) links become anchors, with `target="_blank"` and `rel="noopener noreferrer nofollow"`.

No changes to Finance, Assist, WhatsApp, billing, Google scopes, Gmail approval security, worker permissions, leases, checkpoints, sandbox, database schema, migrations 0078/0079 or production data. Existing scheduling, retry, usage metering and approval paths remain in place. No new infrastructure or extra title/summarization model calls.

## Verification

206 focused unit/regression tests passed:

- 18 new response/result/routing/title/source/provider/worker tests.
- 43 Agent chat experience, 47 autonomous engine, 17 Automation, 32 Connector/Gmail approval, 9 Agent, 8 normal Chat.
- 7 natural-style, 12 AI tools, 4 Finance baseline, 9 Assist connection tests.

Six Chromium browser scripts passed: new response/result checks plus existing Agent chat, Agent, autonomous detail, shared shell and normal Chat browser checks.

New browser coverage at **320, 360, 390, 820 and 1440 px** verifies stored/streamed/reloaded Markdown, headings/bold/italics/lists/code/tables, XSS/unsafe URL rejection, plain user messages, result-first ordering, collapsed execution details, source deduplication/tracking removal, compact completed cards, visible composer and no horizontal overflow.

Screenshot fixtures: `agent-results-chat-{width}.png` and `agent-results-detail-{width}.png` in the OS temporary directory; CI uploads them with the existing Agent screenshot artifact. Screenshots use synthetic users/results and controlled provider streams, not real production account data.

One focused Impeccable detector pass and one batched screenshot inspection completed. The detector reports two flat-type-hierarchy warnings because Jinja stylesheet links cannot be resolved by the static scan. Actual rendered headings/body hierarchy was reviewed at 320/390/820/1440 px; no confirmed visual defect remained. No full audit or repeated polish loop.

Finance/Assist baseline direct runs initially failed on Windows `WinError 32`: legacy test reset helpers attempt to unlink an open temporary SQLite database. They passed using process-local harnesses that close the cached test connection before reset; no source files changed for this. CI retains its unmodified Linux invocations.

`git diff --check` passed. CI includes the new unit/browser tests and existing Linux sandbox/PostgreSQL checks. No whole-repository suite was run.

## Remaining limits and release handoff

Live model prose and real current search results were not production-tested in this task. Concision and source quality are guided through prompts; they remain model-dependent. The app must not claim official live TikTok/X rankings. The bounded DOM parser retains the incumbent Markdown subset rather than claiming full CommonMark support. Source display is bounded to 32 per result; complete stored execution output remains available.

Ready for PR review and CI; deployable only after checks are green and a separate release instruction. A later release should update Client Hub and the existing autonomous Cron runner to the same reviewed commit because planner/content-worker guidance also changed. No AI Admin deployment, migrations, data reset or new paid resource is needed. Perform an authenticated live research/ordinary-Q&A smoke check after release.
