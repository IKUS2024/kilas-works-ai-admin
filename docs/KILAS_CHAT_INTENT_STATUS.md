# Kilas Chat intent and action routing hardening

Existing branch: `fix/kilas-logo-image-routing-20261002`. Existing PR: [#113](https://github.com/IKUS2024/kilas-works-ai-admin/pull/113). Based on production/main `81c41736708cba97d84fda81c60ce06a23a1c265`. Continue existing logo commits; no new branch or PR. Review only: no merge, deploy, migration, Render change or production QA mutation.

## Architecture and behavior

`kilas_ai/routing.py` is the one deterministic server-owned action policy. It receives owner/thread-scoped validated attachments and a bounded recent assistant answer, never a client-selected intent/provider/model. Normalized Indonesian verbs/slang/typos distinguish discussion/concepts and explicit source code from visual creation. No classifier call was added.

- CHAT: ordinary answers, logo ideas/concepts, explicit SVG/HTML/CSS/source requests; existing Luna analysis/reasoning and Conversation Standard remain.
- IMAGE_GENERATE: logo/wordmark/icon/mascot/poster/banner/illustration/photo creation uses the existing validated image provider. Short visual follow-ups use the nearby concept as bounded data. Logo direction asks for original, restrained, readable final visuals, requested brand name, no unsolicited mockups/slogans/watermark/trademark symbols or copied logos.
- IMAGE_EDIT: validated current upload or recent same-owner/thread image (including generated images). Last four messages bound contextual image reuse; missing images require upload. No cross-thread or account fallback.
- PDF: explicit PDF creation/conversion uses the existing actual renderer/persistence path and previous draft context; never calls a text result a file.
- WEB: explicit search and clearly current prices/news/CEO/schedules/weather/currency queries use existing bounded Search. Static explanations stay Chat.
- WORK: substantial research, monitoring, recurring requests and coding-until-tests-pass receive a server-built **Lanjutkan di Work** link into the existing prefilled flow. The handoff does not start or claim completion of a background job; opening/submitting Work uses its existing planner, quotas, approvals and progress architecture. The link carries at most the existing 1,200-character Work instruction limit. Work-disabled installations honestly say nothing started.
- FILE: unsupported Office output requests receive an honest limitation and PDF option, without silent format substitution.
- CLARIFY: bare action requests lacking usable context ask one short question. Reasonable logo defaults proceed without asking style/color questions.

For `buat logo bagus buat kilas works`, Chat bypasses prose, shows actual image activity and returns a real private preview/download after provider success. Work selects the registered IMAGE worker and completes only after byte/MIME validation and durable storage. Image failure returns calm public failure text and cannot fall back to SVG. Explicit `buat kode SVG logo Kilas Works` stays text/code.

## Response safety and existing controls

The last-resort guard buffers only visual/file prose-risk cases and rejects SVG/HTML/style/script/XML/canvas markup, raw CSS, characteristic ASCII art and base64-like output before streaming or persistence. PDF source is also checked before rendering. Invalid visual output has no DONE/success and is not saved as an interrupted assistant artifact. Explicit code/discussion remains allowed. Tool/visual regeneration cannot bypass action routing through the text regeneration endpoint; owners submit a new artifact request instead.

The guard is a bounded heuristic, not a semantic proof of every possible fake artifact. The high-confidence pre-route is the primary protection. Unrecognized phrasing can still reach normal Chat; no claim of universal natural-language classification is made. Source uploads and prior answers remain untrusted context, never executable registry instructions.

Existing image byte/MIME validation, CSRF, owner/thread access, idempotency, timeouts, metering/quota/fair-use, Gmail approval and autonomous leases/fencing are unchanged. Normal Chat cannot silently promote to Sol. Work retains existing model routing. No additional model call or artificial delay is introduced; actual requested images/Search still incur existing metered usage. Static clarification/handoff messages use the existing reservation/cleanup flow with zero provider tokens. Keyboard/cache-busting baseline is unchanged; this patch changes no JavaScript or UI structure.

## Verification

- **276 tests across 15 focused suites passed**: intents 10, tools/images 13, PDF 4, Work 22, Chat 8, cost/model/fair-use 35, usage 5, attachments 6, natural style 7, Agent 9, Automation 17, Agent chat 43, autonomous engine 47, PR #110 results 18, connectors/Gmail approval 32.
- **90 realistic deterministic matrix cases**, with Indonesian slang/typos, discussion, explicit code, visual generation/edit, PDF, current information, Work, clarification and unsupported files.
- Exact logo HTTP/SSE test proves no prose call, real image event and persisted PNG, foreign-account denial, IMAGE_GENERATION accounting, logo quality direction and honest failure with no fallback.
- Context tests cover concept-to-image, recent generated-image edit, previous draft-to-real-PDF; guard test proves raw SVG is neither streamed nor stored. Actual Work runner persists validated PNG through IMAGE with no AI_TEXT fallback.
- **Four Chromium scripts passed**: existing Chat/attachments/Search/image/PDF regression browser, Work/artifact/progress browser, held-stream composer focus browser, Agent chat browser. Combined coverage includes 320/360/390/820/1440 px and no overflow. Coarse-pointer completion remains unfocused; manual tap and desktop workflows remain. Browser emulation does not claim actual Android keyboard testing.
- All provider calls were mocked; no production model/image/search calls or production account mutations. Existing focused CI now includes the intent script. Current release CI will be linked on PR #113; it is not yet an all-repository green claim.

Diff review: no Finance, Assist, WhatsApp/Meta, OAuth, payment/pricing, schema/migration, lease/fencing, infrastructure or production data changes. Existing Work artifact migration is untouched. No new dependencies.

## Release state

Ready for code review. Not automatically cleared for deployment: relevant latest-head CI, owner approval and controlled provider acceptance remain review gates. **Do not merge or deploy this task.**
