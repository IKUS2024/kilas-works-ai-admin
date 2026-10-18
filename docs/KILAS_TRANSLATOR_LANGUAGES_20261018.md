# Translator languages and speech —2026-10-18

Owner authorized Translator implementation/deploy now, superseding its sandbox prerequisite. No paid generation/QA, new service, credential or sandbox attempt is included.

## Findings and implemented routes

One shared18-language UI/validator had restricted every Translator route despite different provider capabilities. Classic speech also requested multilingualv2 for Thai/Vietnamese, outside its documented29-language list. Translator now has separate mode catalogs; VoiceOver and Call retain their existing18-language list and behavior.

| Mode | Exact route | Documented distinct ceiling | Availability boundary |
|---|---|---:|---|
| Live with Kilas voices | Scribe v2 / v2 realtime → existing Luna translation → eleven_v4 |83 | Intersection of100 enumerated ASR languages and84 explicitly enumerated v4 languages; further intersected with read-only account GET /v1/models |
| Google native Live | gemini-3.5-live-translate-preview, existing opposing streams |76 | Dedicated Live Translation language table, existing opt-in/account/funding gates preserved; no custom Kilas acoustic voice claim |
| Uploaded media | dubbing_v2 POST /v1/dubbing/project |93 targets,76 explicit sources plus automatic detection | Existing upload visibility flag preserved; v2 alpha/account acceptance not newly proven |

These routes cover108 distinct output languages in total,42 short of150. Regional/script variants and Chinese/Mandarin or Norwegian aliases are not counted twice. This is documented routing coverage, not108 languages individually generated/listened to. The live Kilas mode can expose fewer than83 if account metadata omits languages/model or denies access. Missing/alpha/unavailable v4 fails closed, without silently changing model or voice. Google/dubbing documentation is not proof that this account accepts every language.

Kilas Male/Female resolve the same existing saved voiceIDs. No voice update, clone, original sample change or replacement occurs. Existing English assets were already generated on this v4 path in the prior release; this change makes no new generation. Translator-only v4 requests use language_code, stability0.5, similarity_boost0.75 and automatic text normalization. Normal conversational speed uses the provider default; no synthetic emotion tags, exaggerated style, speaker boost or saved-setting mutation. The documented streaming endpoint supports model IDs reporting can_do_text_to_speech. No end-to-end latency or naturalness claim is made from the contract.

Native Chinese/Portuguese defaults explicitly display Simplified/Portugal and send zh-Hans/pt-PT; other regional response aliases normalize for validation. Existing native model, echo rules, sessions and provider choice remain unchanged. Speech documentation acknowledges accents, related-language confusion and possible voice shifts; audio quality still needs listening acceptance.

## Interface, availability and safety

The same select positions now offer search by localized name, English/autonym or code, with keyboard navigation and a native-select no-JS fallback. Duplicate pair exclusion, consent, Start/recovery and submitted values remain owned by the existing flow. Result/history/download names support expanded languages. VoiceOver controls, consent and layout were not rearranged.

v4 account catalog is fetched read-only, bounded by existing transport limits, cached5minutes on success/30seconds on failure and warmed on Render startup. A sanitized KILAS_TRANSLATOR_CAPABILITIES log records actual account catalog-enabled count. Metadata discovery creates no audio. Existing quota, subscription-credit checks, cancellation fences and no-paid-retry behavior remain in force.

## Verification

-162 focused tests:161 pass; one existing privacy-link assertion fails identically on untouched c36b0cf. The existing consent checkbox/copy was preserved. The intentional previous-v2 payload expectation is updated to v4 with language_code.
-9 new contracts cover exact counts, account cache/intersection, malformed/alpha/missing/failed metadata, no fallback, exact voice and streaming payload, expanded classic/native pairs, unsupported rejection before paid IO and one mocked expanded dubbing submission.
-Real Chromium:8 classic/native cases across320/768/1440 and id/en/es/zh pass code search, keyboard selection, opposite-pair exclusion, form values, consent retention, popup/document bounds and JS error checks. Uploaded93-target UI checked in each locale. Screenshot inspected at320. No microphone or provider invocation.
-Logs: /tmp/kilas-translator-final-tests.log, /tmp/kilas-translator-baseline-one.log. Browser report/screenshots: /tmp/kilas-translator-picker-qa/verification.json. Reproducible harness: client-hub/tests/test_kilas_translator_picker_browser.py.
-No paid provider/model calls. No new E2B VM. Sandbox remains OFF with two consumed attempts. No Finance, pricing, Call, voice identity or data migration change.

Production deployment/read-only discovery results are recorded in the release handoff. Public authenticated generation/listening was not performed; paid language/naturalness/latency acceptance is deferred. A LIVE code deployment is not paid provider acceptance. Expanded dubbing remains behind its existing visibility/account gates.

## Primary sources checked2026-10-18

-https://elevenlabs.io/docs/overview/models — exact model IDs and explicit language enumeration (not the headline count).
-https://elevenlabs.io/docs/api-reference/models/list — account catalog capability/language metadata.
-https://elevenlabs.io/docs/api-reference/text-to-speech/stream — exact voice endpoint, model capability requirement, per-request settings, language enforcement and stream contract.
-https://elevenlabs.io/docs/overview/capabilities/speech-to-text — explicit Scribe languages and accuracy limitations.
-https://elevenlabs.io/docs/overview/capabilities/dubbing and https://elevenlabs.io/docs/api-reference/dubbing/create-project — v2 language table, cloning default and project API.
-https://ai.google.dev/gemini-api/docs/live-api/live-translate — dedicated translation model/table, variant codes and preview limitations.

## Initial picker regression correction —01:29UTC

The new picker inserted non-submit buttons before Start. Classic page initialization used form.querySelector('button'), so recovery mistook the first picker for Start, disabled it and overwrote its language label. This was reproduced at320px in English: expected Indonesian, observed disabled Start. Native already used a submit-specific selector. Classic now targets button[type=submit]; its template module version changes to retire cached initialization. Consent, readiness and submission validation remain unchanged.

Strengthened Chromium checks pass8 classic/native cases across four UI languages, including initial labels before any interaction, reload, search/selection, pair exclusion, form values and required consent.25 focused Node language/recovery tests pass; their DOM mocks now expose the actual submit selector and existing data-enabled contract. Before/after logs: /tmp/kilas-translator-initial-label-before.log and /tmp/kilas-translator-initial-label-after.log; Node log: /tmp/kilas-translator-picker-node.log. No paid calls.

The owner's renewed150-language target requires complete speech coverage for42 languages outside the documented108-language output union: ASR plus translation and compatible TTS, or voice-preserving dubbing. Adding selector rows cannot supply that coverage. Another speech route must also demonstrably preserve the chosen Kilas voice; if it needs a new provider/voice mapping, compatible capability and explicit approval are prerequisites. No new route or service was researched/provisioned for this regression.
