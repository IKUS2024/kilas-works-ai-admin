# Owner-only live QA allowance — ready-build requirements

Owner approved one non-sensitive sample-audio test for existing account `irvankarnavi@gmail.com`, at most 120 seconds and USD 0.10 total provider charges, with no TTS, automatic sending or automatic retries. This document supersedes the earlier proposal-only budget section of `kilas-live-assist.md`. It does not claim a real browser/provider pass.

## Release and activation status

Disabled commits `483804a502656753e70bb1a04a513f71416812ee` and `2ad69b4edd24db8d6cb76dc9738891b560e55f92` were pushed to main after fetch confirmed no competing change. All ten triggered GitHub workflows succeeded, including [Content Chat QA](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/38032309951), AI, Audio, Video and session QA. Disabled release local checks: 89 Python cases including disposable PostgreSQL and synthetic browser cases, plus 26 JavaScript cases.

The Render mutation to merge only `KILAS_CHAT_TRANSCRIPTION_ENABLED=false` and `KILAS_LIVE_ASSIST_ENABLED=false` was rejected by automatic approval review, which interpreted the historical read-only instruction as prohibiting deployment/settings changes. No workaround was attempted. Latest independently verified Render live SHA remains `ba98005d55731888a990402787973054c3f7c095`, deployment `dep-db4t9ll9fdbs73ar2lm0`. Existing activated content projects remain there; this task has not changed those flags or demo flags. New owner-QA code is prepared locally, not yet activated or paid-tested.

## Shared server allowance

- `live_qa_schema.sql` adds only QA grant, operation and checksum metadata tables. It uses its own named marker; existing content release checksums, numbered migrations and customer billing tables are untouched.
- QA defaults OFF via `KILAS_LIVE_ASSIST_QA_ENABLED`. Enabling this isolated switch exposes live assistance only to the authenticated CLIENT_OWNER whose current database email exactly matches the approved address. Even a globally enabled normal live flag cannot widen QA access. General project transcription's `budget_ready()` remains hard False.
- A fixed grant primary key consumes exactly one session on the first successful start. PostgreSQL row locks serialize operation reservations across workers. SQLite uses BEGIN IMMEDIATE for disposable tests. Stop, expiry, exhausted budget, restart, uncertain requests and failed requests cannot reset or recreate the grant. No grant/session is created by viewing the page.
- Each operation commits its full worst-case micro-USD reservation and irreversible DISPATCHED marker before calling OpenAI. Operation keys are bounded canonical chunk sequences or opaque reply keys. Duplicate DISPATCHED/UNCERTAIN/COMPLETED operations cannot cause another provider request. No reservations are refunded, even when actual usage is cheaper or unknown.
- Server database time enforces <=120 seconds and the pricing-manifest expiry. Stop on any worker closes the shared grant; late responses and subsequent translation/draft calls are fenced against the database. An already accepted provider call may finish after stop and incur cost, which remains fully reserved.
- No audio, captions, personal facts, replies, API keys or new authentication credentials are persisted in QA metadata. The stored session digest is a binding for the existing ephemeral nonce, not an account credential. Existing invoice, balance, price, quota and usage policy are unchanged.

## Verified pricing and conservative bounds

Official sources checked 2026-10-10; the isolated pricing manifest fails closed outside that UTC date. Only the fixed models below are priced; unknown models are rejected. There are no tools, model fallbacks, regional endpoints, paid generation, TTS or automatic sending.

| Operation | Exact model and official standard rates per 1M tokens | Reservation before call |
|---|---|---|
| STT | `gpt-4o-mini-transcribe`: input USD 1.25, output USD 5.00; 16,000 context and 2,000 maximum output | Full 16k input + 2k output = **USD 0.030000** even for a <=10-second WAV |
| Translation / explicit reply | `gpt-6-luna`: input USD 0.10, cache writes USD 0.125, output USD 0.50; explicit `service_tier=default` | <=16,384 serialized request bytes, conservatively reserve 20k byte-BPE input tokens including fixed two-message protocol margin, plus 512 completion/reasoning tokens = **USD 0.002756** at the higher cache-write input rate |

Text payload size is checked at the transport boundary before any reservation/request. STT transport independently revalidates mono 16kHz/16-bit WAV <=10 seconds and 512KiB. At most 12 chunks/translations and three explicitly clicked drafts can be attempted, but the **USD 0.10 total allowance takes precedence**. Three STT+translation pairs retain USD 0.098268, leaving insufficient allowance for another draft; one pair plus one draft retains USD 0.035512. This small QA can therefore stop earlier than two minutes. These reservations are deliberate conservative ceilings, not an actual invoice or a two-minute throughput promise.

Sources: [STT model bounds](https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe), [pricing](https://developers.openai.com/api/docs/pricing), [Luna rates](https://developers.openai.com/api/docs/models/gpt-6-luna), [Chat Completions limits/service tier](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

## Actual test handoff

Supported path: authenticated owner in **Chrome desktop on HTTPS**, `/kilas-ai/live-assist`, non-sensitive sample video/call tab ready, choose call mode to test an explicit editable draft, enter only true sample facts, accept capture/provider/sample consents, then click start and choose **Chrome Tab + Share tab audio**. Ordinary phone system audio is not supported. Start consumes the single grant, so prepare the tab before starting; there is no rearm endpoint. The first caption is expected after ten seconds plus provider processing; stop after one useful chunk/draft to retain cost headroom.

Before paid QA: parent must coordinate the real desktop browser and completed Render release/activation. The previously denied production browser/network access must not be bypassed. Isolated QA flag activation is a separate explicit production action; normal live/transcription remain OFF and existing content projects remain active. The public build page must show the one-use, 120-second, USD 0.10 warning and sample-only consent. Do not call this end-to-end verified until real selected-tab audio and actual provider output have been observed.

Local verification after the allowance change: **106 Python cases passed without skips**, including 17 allowance cases, disposable PostgreSQL contention for grant creation, a shared monetary cap and duplicate operation claims. The actual dedicated QA transport adapters were exercised with injected responses; timeout retains full cost, cross-worker stop fences late STT and follow-up translation, other owners/admins cannot access the QA route, sample consent is required, and general transcription stays hard-off. **26 JavaScript cases passed**. Existing browser/worklet tests use generated PCM and injected capture/provider data; they are not an end-to-end paid pass.

Render currently reports `gunicorn app:app` and one service instance. Process-local caption state still requires requests to reach the same worker; a worker change/restart fails closed and does not authorize another paid session. Worker count from private environment settings was not inspected or changed. The cost allowance itself is shared and independently tested across database connections.
