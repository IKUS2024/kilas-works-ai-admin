# Chat model selection QA — 2026-10-17

Scope: Kilas AI text Chat, both current Agent conversation and legacy thread surfaces. No Call, Translator, Voice Over, Finance, Group, subscription/pricing-plan, or Creative Services files changed.

## Behavior and limits

Ten exact model IDs are registered under OpenAI, Claude, Gemini. The title selector contains model names and a checkmark; inaccessible choices are disabled. Desktop/tablet use an anchored dialog, phones a full-width bottom sheet. Preferences are owner-scoped per conversation. The new UI sends the exact selected ID; invalid/unavailable IDs stop before a user message, usage reservation or provider inference. Existing clients without a selection preserve their existing route.

Availability requires the existing deployment credential and successful read-only retrieval of the exact model from its provider Models API (plus generateContent support for Gemini). Documentation alone never enables a choice. Positive checks cache for ten minutes, negative checks thirty seconds. Safe startup marker `KILAS_CHAT_MODELS` contains IDs/statuses only. Access metadata does not prove inference quota, paid entitlement, response quality or successful model inference. No credentials or subscriptions are changed. Deployment/account findings belong in the release report.

Adapters use native OpenAI Chat Completions, Anthropic Messages and Google streaming generateContent. System instructions, text/image blocks, conversation roles, reasoning controls, finish reasons, usage and returned model IDs are mapped separately. An incompatible attachment or different returned model fails explicitly. There is no alternate-model fallback. Missing returned IDs remain unreported.

Search still retrieves through Kilas's existing service. The exact selected model composes the final answer from that evidence; retrieval and synthesis are metered separately within one existing operation reservation. Source-URL checks remain active. Currency conversions must preserve the already validated quote, arithmetic and provenance verbatim; changed conversion output is rejected. Search failure does not invent a verified result.

Text coding/discussion and uploaded document/image understanding use the selected model. Legacy PDF authoring uses the selected model, with incomplete output rejected. Background Work, generated images and artifact pipelines retain their existing separate engines and the picker discloses that boundary. This is not native-vendor-app tool parity and introduces no arbitrary code executor or sandbox.

Selected Chat keeps 32 recent messages/64,000 characters plus bounded earlier summaries. Adaptive output bounds are 2,048 / 8,192 / 16,384 / 24,576 tokens, with low/medium/high task-appropriate reasoning. Limits include provider reasoning tokens where applicable. No unlimited or maximum-reasoning default. Structural repair remains at most one separately reserved, separately metered call to the same selected model. Truncated/filtered/incomplete streams are not marked complete.

Existing locked capacity/reservation/settlement paths remain authoritative. Pending requests record the selected model so concurrent expensive requests count. Forecasts count source text, images and possible cache writes; settlement uses actual returned usage, including cached input, OpenAI/Anthropic cache writes and Gemini thought tokens. Missing billable usage retains a conservative estimate rather than creating free repeated dispatch. Selected pricing does not change old/unselected product rates or plan prices.

## Verification

- 61 focused synthetic tests passed: 19 new model tests plus existing automatic Search and unified Chat regressions. Network transport is forbidden except mocked native request fixtures. Includes all ten mappings, model mismatch/no substitution, unavailable/invalid IDs, owner/CSRF isolation, multi-turn switching/context, documents/images, repeated request keys, Search recovery, exact FX preservation, truncation/repair, pending premium reservations, effective prices and idempotent settlement.
- 85 existing offline Call boundary tests passed after the shared-provider/accounting changes; paid provider calls: zero.
- Real Chromium + real Flask routes: both Chat surfaces at 320, 390, 768, 1024, 1440 px (10 cases). Verified full-width phone sheet, anchored larger-screen menu, no horizontal overflow, keyboard arrows/Home/End/Escape/focus, unavailable disabled choice, reload persistence and unchanged draft. Committed visual/JSON evidence: `docs/evidence/chat-models-20261017/`; all ten screenshots also remain in `/tmp/kilas-chat-model-browser/` in the execution environment.
- Broader legacy regression run: 121 tests, 8 failures + 1 setup error. The same nine named failures reproduce on unchanged main `a87fff6617ff000862a2a022428841310c9d5186` (105 tests): old authentication-fixture expectations and duplicate synthetic QA-user setup. No protected-module changes were made to address them.
- Python compilation, JavaScript syntax checks and `git diff --check` passed.
- No paid inference or private user audio/transcript was used. Mocked provider streams establish mapping and application integration only. Real-provider generation and mobile-device generation remain unverified by this release QA.

## Pricing sources and effective-date handling

Standard first-party USD rates checked 2026-10-17: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing). The selected-only catalog includes OpenAI >272k-input pricing, Haiku >100k-input pricing, cached input and unrequested one-hour-cache exclusion. Gemini 4 Argon promotional rates end 2026-11-30; Gemini 3.8 Flash promotional rates end 2026-12-31. Settlement prices use the operation start date. Values are usage estimates, not a provider invoice reconciliation.

Native API references: [OpenAI GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Claude Models API](https://platform.claude.com/docs/en/api/models/retrieve), [Claude model overview](https://platform.claude.com/docs/en/models/overview), [Gemini generateContent](https://ai.google.dev/api/generate-content), [Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking).

## Browser-discovered structured-output correction

The single authorized synthetic Luna browser submission on legacy thread 131 at 2026-10-17 11:58:59 UTC failed visibly. Its initial operation and automatic quality repair both returned billable usage: 1,208 input / 205 output tokens, then 1,365 input / 184 output tokens. Both usage records are FAILED and BASE, with combined estimated supplier usage of USD 0.000516; no top-up debit exists. The returned-model snapshot and rejected answer text were not durably retained on this failure, and no validator-reason log existed. Consequently the exact production rejection code cannot be reconstructed retrospectively.

An automatic repair is only reserved after a completed first response fails structural validation. Offline reproduction with the exact synthetic prompt and correct reference JSON confirms a defect: minified valid JSON containing the requested Python function has four whitespace-delimited words and is rejected as `unusable_depth`; pretty-printing the identical object passes. The correction exempts successfully parsed, explicitly requested JSON from the prose word-count heuristic, recognizes the prompt's `SATU objek JSON` format instruction, and preserves malformed-JSON/truncation and other structural guards. New diagnostics log only server-owned model/attempt/finish/reason codes, never prompts or answer text.

Verification: 62 focused provider-free tests passed, including the exact reference answer in compact, pretty and fenced JSON forms, malformed/truncated rejection, ordinary-prose depth enforcement, and one-attempt completion through both current and legacy Chat routes. No paid retest was performed by the implementation worker. Production acceptance still requires a separately cleared browser retest; this correction is evidence-backed but does not retroactively prove the unavailable production answer's exact rejection code.
