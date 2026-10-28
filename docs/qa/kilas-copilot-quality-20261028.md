# Copilot quality hardening — 2026-10-28

Scope: retain the approved reference layout and working engines. Remove main-page Info, retain provider disclosure in `/privacy#audio-processing`, hide the global left rail on Translator/Voice Over only. Their in-page history/controls remain. Legacy AI Chat code, routes, owner checks and historical data remain intact and hidden reversibly.

## Verified defects and corrections

- Capture discarded an entire final PCM frame when that frame crossed the 60-second byte cap. The buffer now copies exactly the remaining even-byte sample tail.
- ScriptProcessor capture ran on the main thread. Prefer the existing tested PCM AudioWorklet processor, resampling actual hardware rate to mono 16 kHz PCM16. Stop the physical track, flush queued frames, wait for a FIFO final acknowledgement, then submit. A failed flush requires a new recording instead of submitting partial data. Compatibility capture remains for browsers without worklets. Neither path guarantees recovery of hardware samples not yet delivered by the browser.
- Whole-clip RMS rejected quiet speech or a short utterance surrounded by silence. Only near-digital silence is filtered locally on the server using peak plus RMS. This is not speech recognition, VAD, noise removal or confidence. More low-level non-speech clips can reach the provider; existing per-request account guards and the same 60-second envelope remain unchanged.
- The SSE reader waited for EOF even after the completed saved turn arrived. It now releases the reader at completion and accepts CRLF framing. Interrupted partial answers still remain unsaved.
- Context fallback to the last two turns could still exceed the 24,000 UTF-8 byte budget. Context now retains a bounded contiguous recent tail, labels clipped fields, and keeps the latest utterance. Oversized malformed input is rejected rather than silently reinterpreted.
- The old prompt inserted personal-detail placeholders and lacked direct-answer/identity guidance. The policy now prefers useful, proportionate spoken replies, resolves heard context, clarifies only essential unknowns, uses honest natural replies when personal facts are absent, prohibits bracket slots, answers directly from known heard context, and distinguishes previous AI suggestions from confirmed facts.
- Malformed transcription JSON arrays are handled explicitly. Empty/punctuation-only transcripts request repetition without generating a reply. No phrase blacklist or language whitelist was added.

## Provider compatibility and boundaries

Existing `gpt-4o-mini-transcribe`, JSON transcription endpoint, OpenAI backend key and `gpt-6-luna` reply model remain. No provider swap, extra inference pass, model fallback, credential change, grant or spend commitment. The transcription request deliberately omits a forced language. Primary reply language is inferred from recognized text and heard context; the app does not claim to receive a calibrated confidence or detected-language identifier from this legacy JSON response. Translation target does not set primary reply language.

Official contracts checked: [speech guide](https://developers.openai.com/api/docs/guides/speech-to-text), [transcription request](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create), [existing model](https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe). Current guide marks the legacy transcription models for shutdown on 2027-02-26. New-model fields such as `languages` must not be sent to the legacy model; a future migration needs account/cost verification. [AudioWorklet](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet) is the preferred browser API; the deprecated ScriptProcessor remains only as compatibility fallback.

## Language and answer evaluation matrix

| Case | Offline coverage | Actual provider recognition / answer quality |
| --- | --- | --- |
| Bahasa Indonesia, English, Español | Unicode source/reply persistence, unforced STT request, prompt rules | NOT RUN |
| 日本語, العربية, 中文, हिन्दी | Unicode persistence, UTF-8 budget; automatic paragraph direction | NOT RUN |
| Mixed English/Indonesian | Source preserved; dominant-language instruction | NOT RUN |
| Short `OK` after Spanish heard context | Context represented; explicit short-utterance policy | NOT RUN |
| Empty or punctuation-only, digital silence | Repeat/no-reply path; no paid silence request | NOT RUN on physical audio |
| Quiet/brief signal plus long silence | Real PCM/WAV admission regression, not speech accuracy | NOT RUN on physical audio |
| Other languages, including Klingon example | No app-level language blacklist; uncertainty rubric | Support and accuracy UNVERIFIED |

`client-hub/tests/copilot_quality_cases.json` contains good/bad examples and review rubrics for directness, context, proportionality, style, missing personal facts without templates, known dates, app identity, legitimate provider mentions and uncertain input. Prompt-contract and mocked pipeline tests only verify application policy, transport and persistence. They do **not** measure Luna adherence or word error rate. App branding never blindly replaces ChatGPT in user content and must truthfully acknowledge OpenAI when specifically asked about the provider.

## Optional bounded paid acceptance proposal — not executed

Eight clips at most 15 seconds each (at most 120 seconds total), one transcription and one reply up to 250 output tokens per clip, no translation, no retries, no parallel inference, existing capacity guards. Suggested cases: Indonesian, English, Spanish, Japanese, Arabic, mixed language, quiet speech, short contextual utterance. Score transcript meaning/names/numbers separately from answer relevance, factual grounding, tone and language. This requires explicit bounded paid-test authorization; deployment permission alone is not treated as that authorization. No physical mic, real phone call, Safari or paid provider acceptance has been run here.

## Local verification

- Copilot backend: 28 tests PASS (real auth, ownership, CSRF, persistence and capacity guards; provider calls mocked).
- New capture tests: exact cap tail, FIFO flush, timeout rejection, cancel/cleanup and resampling at 16/32/44.1/48/96 kHz PASS. Existing shared capture/PCM: 11 PASS. SSE/WAV contracts PASS.
- Usage 5, Finance onboarding 4, Translator languages 10 and Voice Over editing 4 PASS.
- Chromium at 360/393/768/1440: first/second tap, repeat taps, permission denial, late permission/cancel, history translation OFF/ON, in-flight cancel, deferred session network, native worklet synthetic device, single-sync-worker disconnect and Arabic direction PASS. Tool pages have no global drawer/hamburger; centered content, in-page history, open-drawer navigation and back/forward covered.
- `git diff --check`, JS syntax and scoped Impeccable layout detector PASS (detector returned no findings; this is not visual certification).
- Historical broad-suite failures are tracked separately in `kilas-copilot-ci-triage-20261027.md`; do not represent them as passing or disable assertions.

## Follow-up review correction and production readiness evidence

Parent approved the layout/RTL/tool navigation in artifact 12790089452, then rejected generated fill-in slots as spoken replies. The prompt now prohibits bracket templates and editing instructions in spoken suggestions. Unknown availability receives an honest natural response, while a known date from heard context is answered directly. Good/bad fixtures cover both paths and reject bracket slots in good suggestions. This remains a prompt-contract change, not a claimed paid model-quality score.

The unavailable labels in screenshots reflect the disposable SQLite harness with no real ElevenLabs key, no approved production saved voices and unfunded synthetic accounts. The audio provider, routes, entitlement/budget modules, saved voices, engines and schema are unchanged. An added read-only route test supplies mock provider readiness plus an actual disposable audio balance: Voice Over retains enabled generation metadata and in-page history; classic Translator retains ready/start metadata; no provider generation runs or balance is debited.

Production startup for live c19a3416 at 2026-10-28T03:11:49Z reported KILAS_ELEVENLABS_READY configured_ready=true for the existing owner and nonowner checks, both approved voice aliases, authenticated audience and paid_qa=false. KILAS_LIVE_INPUT_POLICY retained owner funding modes, paid-customer audience, monetary caps and shared concurrency; OpenAI presence=true. These are safe configuration/readiness observations, not live provider connectivity or generation tests. Recheck after deployment without reconfiguring credentials or entitlements.
