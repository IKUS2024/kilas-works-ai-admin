# Chat/Search model, image and answer presentation audit — 2026-10-20

Baseline: `bbe0dbff5e2845c2367b83529247db0fb2c03bf2` on current main. The supplied screenshot shows model selectors only, not an answer-quality defect. Findings below come from code, synthetic reproductions and current official documentation. Owner subsequently authorized push/deploy after tests; no paid provider validation is authorized or performed.

## Verified findings and corrections

- `intelligence.classify` treated any occurrence of “singkat/brief” as an explicit short-answer request. “Analisis strategi … jangan singkat” received QUICK/2,048 selected-model output tokens instead of DEEP/16,384. Negated and quoted brevity instructions now remain substantive; explicit short requests still work. All ten selected IDs remain intact. The quality guard uses the same interpretation.
- Chat already had useful-depth guidance; it was not uniformly configured to be terse. Removed its blanket instruction to limit headings and strengthened completion guidance with concrete reasons/examples/steps proportional to the request. No compulsory word count, fixed list size, forced verbosity or hidden-reasoning disclosure.
- Image generation lost the tail of accepted instructions in Home dispatch (1,200 characters), concept carry-forward (800) and native payloads (4,000). The complete direct image request now travels through an owner-scoped job checkpoint to its image worker; generic multi-step jobs keep their own step prompt. Planner labels remain bounded. Native payloads preserve the full prompt and reject oversized input explicitly instead of silently truncating it (32,000-character guard). Existing HTTP input bounds remain unchanged. The existing reservation forecast now uses the complete image prompt UTF-8 byte bound when it exceeds the old 16,000-token floor, preserving quota protection without changing rates, allowances or settlement.
- Logo enhancement previously imposed a simple/clean style even on an ornate request. It now preserves the user's requested complexity and style while retaining the real-image output and safety contract.
- GPT Image 2.5 Flare/Sunburst support transparency according to the provider, but the application rejected it. Both now use the supported transparent PNG setting; GPT Image 2 is still rejected rather than substituted.
- A real Pillow failure affected even the already-allowed Mini transparent image: reading alpha extrema loads the decoder, after which `verify()` raises `RuntimeError`. Verification now reopens the same bytes. Invalid image bytes also become accounted `ToolUnavailable` failures, with no retry/fallback.
- GPT Image 2/2.5 now accept standard 16:9, 9:16, 4:3, 3:4, 4:5, 5:4 and 21:9 shapes within the existing resource envelope. Mini retains its three supported sizes. Explicit pixel size and ratio must agree; returned metadata reflects the actual dimensions. No default resolution/quality increase.
- Answer rendering flattened nested lists and recognized only three Markdown heading levels. It now preserves basic nested ordered/unordered lists and supports six heading markers. Tables gain semantic header/body groups and a labelled keyboard-focusable horizontal scroller. Scoped sans typography, paragraph spacing, heading hierarchy, non-decorative emphasis, readable tables/code and uncropped image previews work on both chat surfaces. Original Markdown/copy source, image bytes, links, math and HTML safety remain intact.

## Exact selectable Chat mapping

Display labels are not aliases for cheaper backends. `chat_models.CATALOG` IDs are sent unchanged; response model identity is checked when reported (missing provider identity stays explicitly unreported), with only same-ID dated/version snapshots accepted. Account Models GET confirms availability, not successful inference or consumer-app feature parity.

| Display label | API ID | Actual ordinary-Chat endpoint |
| --- | --- | --- |
| GPT-6 Luna | `gpt-6-luna` | OpenAI `/v1/chat/completions` |
| GPT-6.1 Sol | `gpt-6.1-sol` | OpenAI `/v1/chat/completions` |
| GPT-6 Astra | `gpt-6-astra` | OpenAI `/v1/chat/completions` |
| Claude Haiku 5.5 | `claude-haiku-5-5` | Anthropic `/v1/messages` |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | Anthropic `/v1/messages` |
| Claude Opus 5.5 | `claude-opus-5-5` | Anthropic `/v1/messages` |
| Claude Fable 5.1 | `claude-fable-5-1` | Anthropic `/v1/messages` |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | Google `models/{id}:streamGenerateContent` |
| Gemini 3.8 Flash | `gemini-3.8-flash` | Google `models/{id}:streamGenerateContent` |
| Gemini 4 Argon | `gemini-4-argon` | Google `models/{id}:streamGenerateContent` |

Selected Chat uses low/medium/high reasoning; Claude uses adaptive thinking plus effort. All three dispatched effort values are documented for these selected families. OpenAI documents larger effort options, and Google Lite documents minimal; the application does not claim to expose every provider setting. Ordinary Chat does not enable provider-native tools; Search retrieves through the existing metered search service, then synthesizes with the chosen Chat model. Validated currency arithmetic is returned deterministically with truthful metadata instead of a paid synthesis. Workspace tool/artifact routes are separate. Unavailable/mismatched selected models fail visibly, without a cheaper-model fallback.

Current application guardrails are **not provider maximum capabilities**: 32 recent messages/64,000 text characters for selected Chat, older extractive summary, bounded document excerpts, 2,048/8,192/16,384/24,576 output-token request budgets, 120,000 response-character guard and existing timeout/repair envelopes. These metered resource limits remain; this patch fixes incorrect short-tier classification rather than blindly reserving maximum-priced outputs. Historical context beyond the bounded window is not fully available. It would be inaccurate to promise an unlimited context or every native multimodal/tool feature.

OpenAI documents 1,050,000 context/128,000 output tokens for these three models. Claude documents 1M context/128K output for the four selected models. Google Flash/Lite document 1,048,576 input/65,536 output; Argon has a unified 1,048,576 window but default synchronous output remains 65,536. Its separate long-decode ceiling is now explicitly distinguished in the internal registry; that path is not enabled.

## Exact selectable image mapping and cost constraints

| Display label | API ID | Generation/edit dispatch | Default |
| --- | --- | --- | --- |
| GPT Image 1 Mini | `gpt-image-1-mini` | OpenAI Images generations/edits | low, 1024×1024 |
| GPT Image 2.5 Sunburst | `gpt-image-2.5-sunburst` | OpenAI Images generations/edits | low, 1024×1024 |
| GPT Image 2.5 Flare | `gpt-image-2.5-flare` | OpenAI Images generations/edits | low, 1024×1024 |
| GPT Image 2 | `gpt-image-2` | OpenAI Images generations/edits | low, 1024×1024 |
| Gemini 3.1 Flash Lite Image | `gemini-3.1-flash-lite-image` | Google `models/{id}:generateContent` | 1K, 1:1 |
| Gemini 3 Pro Image | `gemini-3-pro-image` | Google `models/{id}:generateContent` | 1K, 1:1 |

One output, at most five original reference images, existing input byte checks, 8MB decoded response and 4M-pixel guards remain. Google supports the ten existing ratio choices. Lite Image is documented as 1K-only; Pro can support higher resolutions, and OpenAI 2.5 supports higher quality settings. **This release does not enable high/medium/xhigh/max/auto or 2K/4K upgrades**: those need an explicitly costed options/reservation flow, and automatically raising image charges or changing billing/quota configuration is excluded here. The rejection now describes an application limitation rather than falsely claiming the provider lacks it. No catalog model/rate/default was replaced. Better visual quality from live inference is untested, not guaranteed by these fixtures.

## Official documentation checked

- [OpenAI Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra).
- [Claude model IDs, thinking and limits](https://platform.claude.com/docs/en/models/overview).
- [Google thinking settings](https://ai.google.dev/gemini-api/docs/thinking), [Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [Argon](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon).
- [OpenAI image options/transparency/dimensions](https://developers.openai.com/api/docs/guides/image-generation), [Google image models and limits](https://ai.google.dev/gemini-api/docs/image-generation).

Provider documentation supports the mapping/options audit, not live account quality. Existing price tables were not changed or newly certified by this work.

## Validation and release boundary

The initial eight-method audit fixture against archived clean `bbe0dbff` produced 68 failed subtest assertions and 13 errors, including long prompt loss, forced-short classification, unsupported aspect ratios and transparent PNG failure. Patched final eleven-method suite passes. Synthetic transports prohibit external provider calls.

22 isolated backend suites pass (270 tests after the final three additions); 11 additional intelligence-corpus tests pass. Coverage includes all ten native Chat transports, all six image payloads, selected-model persistence and mismatch/no-fallback behavior, owned image jobs, corrupt/transparent responses, full prompt tails, default quality, Search source/empty/error handling, current facts, follow-ups, model preferences, Creative Services, Finance legacy provenance and Translator measured effort. AI Call/Translator JavaScript regressions: 117 pass.

Browser: both chat surfaces × 390/820/1440 pass streamed/final Markdown, nested lists, headings, math, escaped code, table semantics, sans/non-italic typography, original source and no page overflow. Native image artifact tests at 390/820/1440 verify unchanged downloadable bytes, ratio, uncropped preview and foreign-owner 404. Link/JSON browser regressions also run. Evidence is in `/workspace/shared/kilas-answer-presentation-20261020/` and isolated logs `/tmp/answer-*.log`.

The broad pre-existing typography runner reaches an unrelated Translator selector failure (`#live-setup-form button` resolves to three buttons); the identical failure was reproduced on archived clean main and is not a Chat regression. One attempted combined unittest process also polluted shared fixture databases; valid backend results above come from isolated processes. No whole-repository-green claim.

Changed shared adapters needing coordination: `capacity.py` (existing reservation forecast only), `routes.py`, `routing.py`, `unified_runtime.py`, `intelligence.py`, `response_style.py`, `image_models.py`, `selected_image.py`, `autonomous_routes.py`, `agent_workers/image_worker.py`, `workspace_registry.py`; Chat guard and renderer are scoped. No AI Call runtime, Finance/Translator implementation, Voice Over back-link, Creative Services route, migrations, credentials, billing rates/quotas or deployment settings changed.

Minimum release: re-fetch main, preserve incoming work, verify diff and tests, commit/push without force, deploy Client Hub once (auto-deploy is off), observe exact commit and LIVE/startup. Render evidence is separate from authenticated browser/provider verification. The execution proxy previously denied production HTTP CONNECT with 403; do not bypass it. No paid calls, paid searches or image generation have been run. Optional later paid acceptance requires a separately approved USD 5 ceiling for one small capped answer per Chat model and one default-quality image per image model, with no retries or automatic upgrades; this is a proposed test budget, not money spent or a guarantee of provider quality.
