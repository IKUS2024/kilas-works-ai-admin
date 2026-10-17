# Selected document authors and independent image models — 2026-10-17

The modern Chat/Work document path previously dispatched its own automatic author rather than retaining the selected Chat model. Image generation also used a separate fixed engine without an independent per-conversation selection. New jobs now snapshot both selections. A queued job retains its requested author/image model even if the user later changes a picker. Unavailable selected models stop explicitly; no provider or model substitution is added.

## Document path

The selected native OpenAI, Anthropic or Google Chat model authors source content using the existing evidence and owner-scoped attachments from the originating message. Existing validators and renderers produce PDF, DOCX, XLSX, PPTX, CSV, JSON, TXT and Markdown. Requested/returned model and provider provenance persist on the artifact and appear on its card. Provider-returned snapshots are validated; an omitted returned model is labeled unreported. Research/planning tools remain separate from authorship. Legacy jobs without a selection snapshot retain their prior behavior. The legacy thread surface retains its existing PDF route and unsupported Office-format handoff; full Office rendering is the modern Chat/Work path.

## Image catalog and price preview

Only exact native image endpoints that pass read-only account model metadata checks are offered. These checks do not establish successful image inference or remaining quota. The configured request is one square 1024×1024 image: OpenAI low quality; Gemini native 1K. Output estimates are ordered for these settings, with a visible notice that provider quality differs and input/reference/thinking charges are additional. No cheapest-model claim across arbitrary settings or fixed total supplier quotation is made.

| Exact model | Configured output estimate, USD |
| --- | ---: |
| gpt-image-1-mini | 0.005 |
| gpt-image-2.5-sunburst | 0.00588 |
| gpt-image-2.5-flare | 0.00588 |
| gpt-image-2 | 0.006 |
| gemini-3.1-flash-lite-image | 0.0336 |
| gemini-3-pro-image | 0.1344 |

Text/image/thinking token rates accompany the preview. Actual native usage settles against those rates; missing, inconsistent or malformed usage retains the conservative application forecast. That forecast is not a hard supplier spending cap. Gemini 2.5 Flash Image, shut down on 2026-10-02, is excluded. Live account-access results are checked after deployment; unavailable choices are hidden, and existing unavailable preferences fail explicitly rather than silently changing.

Official contracts/prices checked 2026-10-17:

- https://developers.openai.com/api/docs/guides/image-generation
- https://developers.openai.com/api/docs/pricing
- https://developers.openai.com/api/docs/models/gpt-image-1-mini
- https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst
- https://developers.openai.com/api/docs/models/gpt-image-2.5-flare
- https://ai.google.dev/gemini-api/docs/image-generation
- https://ai.google.dev/gemini-api/docs/pricing

## Validation

- 71 targeted Python tests passed: selected artifacts, Chat models, automatic search and unified routing. Native dispatches are mocked; existing renderers produce validated real PDF/Office bytes. Tests cover all 10 Chat author choices, all six image contracts, independent persisted selections, owner/CSRF boundaries, immutable job selections, original-message attachments, durable provenance, exact legacy image dispatch, unavailable providers and conservative settlement.
- A final additional targeted billing test passed after review hardened malformed image usage; the already passed unrelated tests were not repeated.
- Ten Chromium responsive cases passed: modern and legacy surfaces at 320, 390, 768, 1024 and 1440 pixels. Both pickers preserve independent selections across reload, keyboard focus and draft text, with no horizontal overflow. Representative mobile/desktop screenshots and the machine-readable results are in evidence/selected-artifacts-20261017/.
- Provider icons are local CC0 Simple Icons assets with provenance in static/provider-icons/README.md, accessible provider alternatives, and no remote image dependency.
- No paid document/image inference was dispatched by this executor. Contract tests and account metadata checks do not prove actual production image generation or real-device microphone behavior. Existing Call, Translator, Voice Over, Finance, hidden Group, subscription/pricing plans and Creative Services implementations were not changed.

## Separate bounded browser text smoke reconciliation

The browser operator submitted the same non-sensitive QA-017 JSON/code question once to each tested model, with at most the application's existing one metered quality repair. Read-only production records establish:

- Luna failed prior to the valid-JSON validator fix: two failed attempts, recorded total $0.000516.
- Luna after the fix, thread 132: one complete response, 1208 input (1205 cached), 280 output; $0.000152 recorded.
- Haiku 5.5, thread 134: one complete response, 2048 input, 718 output; $0.000564 recorded.
- Gemini 3.5 Flash-Lite, thread 135: one complete response, requested and returned exact gemini-3.5-flash-lite, 1227 input, 1418 combined answer/thinking output, no cache, no repair; $0.003913 recorded. BASE quota and zero top-up debit rows. Browser reports all requested JSON values and Python arithmetic correct.

Total recorded cost is $0.005145. Conservative prior-model allowance $0.002090825 plus Gemini at the higher published Priority rates (1227×$0.54/M + 1418×$4.50/M = $0.00704358) gives cumulative supplier upper estimate $0.009134405. Release the prior $1.75 Gemini reservation. No further paid test is dispatched here.
