# Integrated workspace structure — 2026-10-17

## Release scope and acceptance boundary

The latest instruction prioritizes integrated code and a normal production deployment, with paid-provider QA and comprehensive functional acceptance deferred. This release does not claim ChatGPT/Claude/Gemini consumer-product parity or completion of the earlier full acceptance criteria. No paid inference, image generation, voice generation, subscription, top-up or new infrastructure was purchased during this project.

Baseline: main/live `5fd9d30d3610c40265708e8eaf034861076a40f4`. The branch retained all prior Voice Over/Translator/Call/typography releases. Finance, billing, connectors, Group, Call, Translator and Voice Over implementation files are unchanged.

## Initial verified gaps

- Native exact-model chat adapters and independent image selection already existed. Models GET checks proved account access, not function/image inference acceptance. The ordinary chat response was coupled to its HTTP connection and had no durable delta replay/cancellation state.
- Existing durable jobs and real PDF/DOCX/XLSX/PPTX rendering were reused. XLSX deliberately rejected formulas, and there was no source-project ZIP pipeline or shared native file-tool loop.
- Image edit dispatch carried one reference and forced square output. Missing or uncertain generation could enter worker retry/recovery paths.
- The Python web service has 0.5 CPU / 512 MB RAM. There is no verified tenant-isolated arbitrary-code execution service. A host subprocess timeout or merely finding bubblewrap is not sufficient authorization or isolation.

## Implemented architecture

- `workspace_model_tools.py`: exact OpenAI Responses, Anthropic Messages and Gemini generateContent function-call adapters. The registered tools are `list_files`, `read_file` and `publish_project`. They can access only the job owner's captured uploads, and never host paths, production secrets, shell commands or external URLs. Provider calls have no fallback or automatic transport retry. Encrypted OpenAI reasoning items / native provider tool context stay internal; private reasoning is not presented as progress.
- `workspace_projects.py`: at most four native turns / ten file calls, per-turn existing usage reservation/settlement, bounded context/output, cancellation/revision fences and lease heartbeat. Real source implementation, README and configuration are packaged as a validated ZIP; eligible self-contained HTML receives an isolated preview. Python AST and JSON syntax checks are static. Runtime tests are explicitly shown as **not run**.
- `workspace_files.py`: UTF-8 source and project extraction/packaging without executing code. Rejects traversal, absolute/hidden protected paths, symlinks, encrypted members, duplicate paths, dependency trees, excessive ratios/counts/sizes and invalid source. Limits: 80 source files, 256 KB per member, 2 MB expanded source; generated model plans are further limited to 40 files. Archives are round-trip/CRC checked, never extracted onto the host filesystem.
- `work_attachments.py` / `pdf_vision.py`: add source/ZIP inputs, preserve origin/coverage, explicit truncation and Office sheet/row/slide bounds. PDF pages containing important images are rasterized even when text is present, within the existing bounded renderer. Office files remain macro/external-link restricted. Multiple-upload/removal UI is retained.
- `work_office.py`: valid editable XLSX sheets, numeric cells, restricted local arithmetic/SUM/AVERAGE/MIN/MAX/COUNT/COUNTA/ROUND/IF formulas and real bar/line/pie charts. External workbook/DDE/WEBSERVICE/HYPERLINK/INDIRECT paths are rejected. CSV cannot inject formulas. Formulas are saved for recalculation by the spreadsheet app; the server does not claim to calculate them.
- `selected_image.py` / image worker/store: carry all supplied compatible original reference bytes (up to five) through private job storage and native edit payloads. Normalized oversized edit inputs are rejected before dispatch. OpenAI budget output supports 1024-square / 1536×1024 / 1024×1536; Gemini supports native 1K aspect ratios. Unsupported explicit dimensions/quality/transparency fail rather than silently substitute. PNG transparency is gated to the implemented GPT Image 1 Mini path and output alpha is checked. Native returned image type, dimensions/aspect, byte limits and model provenance are validated. No additional voice call is involved.
- `workspace_streams.py`: persistent SSE deltas and event IDs, first text emitted immediately, read-only replay/reconnect and refresh reattachment, owner/CSRF checks, cancel state and bounded per-process chat slots. Disconnect/replay does not dispatch inference again. A lost process becomes an honest interrupted outcome after timeout; it is not automatically regenerated. Cancellation stops consuming/publishing further work; an already sent provider request may still be billed. Existing background jobs retain genuine action/event progress and artifact metadata.
- Generation failures or abandoned in-flight document/image/project steps become terminal uncertain outcomes instead of automatic paid retries. Modern job starts run bounded background formatting/provider work, avoiding a long HTTP request. Generated source is never executed there.
- Inline artifacts retain authenticated open/full-image/download actions, safe opaque-origin HTML previews (`sandbox="allow-scripts"`, no same-origin permission, network/forms/frames denied by CSP), visible test status and an explicit retention disclosure. Files remain in account history without automatic expiry; archiving a conversation hides it and does not delete its files. No active-work sidebar or notifications panel was added.
- New UI labels/progress/errors/retention text support Indonesian, English, Spanish and Chinese independently of conversation/output language. Chat input increases from 1,200 to 24,000 characters while preserving the existing premium white layout, model selectors and responsive composer.

## Model registry and evidence

`workspace_registry.py` and authenticated `GET /kilas-ai/chat/capabilities` distinguish documented API capabilities, implemented application limits and inference acceptance. Existing labels and exact IDs remain unchanged:

| Provider | Chat label → exact API ID | Ordinary / native workspace tools |
| --- | --- | --- |
| OpenAI | GPT-6 Luna → `gpt-6-luna`; GPT-6.1 Sol → `gpt-6.1-sol`; GPT-6 Astra → `gpt-6-astra` | Chat Completions / Responses |
| Anthropic | Claude Haiku 5.5 → `claude-haiku-5-5`; Sonnet 5.5 → `claude-sonnet-5-5`; Opus 5.5 → `claude-opus-5-5`; Fable 5.1 → `claude-fable-5-1` | Messages / Messages |
| Google | Gemini 3.5 Flash-Lite → `gemini-3.5-flash-lite`; 3.8 Flash → `gemini-3.8-flash`; 4 Argon → `gemini-4-argon` | streamGenerateContent / generateContent |

Image IDs are independent: `gpt-image-1-mini`, `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare`, `gpt-image-2`, `gemini-3.1-flash-lite-image`, `gemini-3-pro-image`. Native image generations/edits or Gemini generateContent are used; a text-model alias is never substituted.

Official API sources checked on October 17:

- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra): documented 1,050,000 context / 128,000 output tokens; Sol function calls use Responses, not ordinary Chat Completions.
- [Claude overview and Models API](https://platform.claude.com/docs/en/models/overview): exact four IDs, text/image input, adaptive thinking, tools, 1M context / 128K maximum output. Account policy can restrict actual operations.
- [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [4 Argon](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon): 1,048,576 input/unified context, 65,536 default synchronous output, documented native functions/structured output. Gemini native PDF/audio/video support is distinct from this app's text/page-image preprocessing.
- [OpenAI images](https://developers.openai.com/api/docs/guides/image-generation), [Gemini images](https://ai.google.dev/gemini-api/docs/image-generation): native generation/edit/reference contracts; app limits are intentionally narrower and exposed separately.

Own read-only Render log inspection at baseline found all ten chat and six image IDs returning `verified` from the deployed Models GET checks at 15:52:49–50 UTC. This is account metadata evidence only. No paid operation was used to certify the new function/image workflow. The app still bounds ordinary context to 64,000 characters and adaptive output to at most 24,576 tokens; those application limits are explicit and are not presented as provider context limits.

## Safe execution blocker

`workspace_execution.py` reports unavailable. The existing code-worker test launcher is gated by this same authority and cannot run generated tests on the production host. The minimum dependent decision is approval/provisioning of a genuinely isolated execution facility (tenant-specific filesystem, CPU/RAM/disk/time limits, stripped secrets, process/dependency/network controls and cleanup), its connection and a bounded operating budget. None was provisioned or purchased. Source ZIP delivery, Office formatting, native file tools, image payload handling and browser-only preview do not depend on that decision.

## Verification performed

All inference was synthetic or blocked. Tests use disposable local owners/SQLite, with no production data writes.

- `test_kilas_workspace_runtime`: 10 critical contracts, PASS. Real source ZIP/CRC and hostile archive rejection; real XLSX formula/chart structure; native provider function payloads; bounded project publish; authenticated download / opaque preview headers; generation failure terminal; two-image original bytes; durable replay/cancel/idempotency and ownership/CSRF.
- Existing isolated suites: selected model routing **20 PASS**; selected artifact/providers/real PDF/Office output **9 PASS**; Work V2 lifecycle **22 PASS**; Work documents **23 PASS**. The historical document fixture now explicitly selects Indonesian for its Indonesian label assertion.
- Critical Chromium browser: **320 / 768 / 1440 PASS**. One inference through refresh/replay; Thinking cleanup; multiple source input/removal; real project ZIP; interactive HTML button inside opaque origin (`self.origin === 'null'`); CSP blocks network fetch; no horizontal overflow or JS errors. This browser check found and fixed initial-delta batching latency and the global frame-deny header on the narrowly authorized preview endpoint.
- `node --check` and `git diff --check` PASS. Legacy attachment suite's two HTTP303-versus200 failures reproduce identically on clean baseline `5fd9d30`; they are not reported as a passing suite or silently removed.
- Evidence logs: `/tmp/kilas-workspace-new-final.log`, `/tmp/kilas-workspace-final-critical.log`, `/tmp/kilas-workspace-models-regression.log`, `/tmp/kilas-workspace-artifacts-regression.log`, `/tmp/kilas-workspace-work-regression.log`, `/tmp/kilas-workspace-documents-regression.log`, `/tmp/kilas-workspace-browser.log`. Browser screenshots: `/tmp/kilas-workspace-runtime-browser/`.

Comprehensive capability/E2E acceptance, paid provider function/image execution, physical-device acceptance and runtime execution tests remain deferred or blocked, rather than marked PASS.

## Additive rollout and rollback

Migration `0105_kilas_workspace_streams` adds only two feature tables and their owner/event indexes. SQLite applies it through the normal disposable schema list. Production applies exactly this release through the existing checksum-guarded `chat_models_schema.apply_release` transaction/advisory lock at blueprint registration; broad `RUN_MIGRATIONS_ON_BOOT` remains unchanged/off. No old table is altered, dropped or backfilled. Before deploy, own read-only production SQL verified both new tables absent and the existing 0102/0103 release checksums present.

Old code can run with the additional tables unused. Reverting the application commit preserves these additive tables and all pre-existing data; do not replay historical migrations or drop tables to roll back. Paid operations interrupted by a process/deploy are terminal/uncertain and are not automatically repeated.

Release SHA, Render deployment and post-deploy evidence are reported separately after tool confirmation. Public HTTP probes from this environment fail at the outbound proxy for both production hostnames. Connected Render exact-SHA/LIVE logs and read-only schema/configuration observations are available; an authenticated production browser is not available. LIVE alone is not full functional acceptance. The final 320px preview smoke also verifies parent CSP blocks navigation to an external origin in addition to blocking fetch inside the opaque iframe.
