# Translator Safari permission repair — 2026-10-19

Scope: classic Hold → release Translator only, based on remote main `ed519ad9b23c9890a9d870b94542791c640460d8`. The separate published PDF/PPT/runtime work remains in ancestry. No provider/model, credential, quota, Finance, AI Chat, Voice Over, tenant, billing or schema changes. No paid provider tests.

## Diagnosis and correction

The supplied screenshot was inspected by the coordinating agent: two completed Indonesian → English text bubbles and the browser's raw NotAllowedError wording. That establishes a browser permission/context rejection; it does not identify whether this particular device rejected a later microphone request or audio playback. No authenticated iPad runtime trace was available.

Confirmed source defects:

- Progressive playback created a fresh HTMLAudioElement after provider/network waits and called `play()` on that unprimed element. Only AudioContext had been resumed during Start. A rejected media play promise escaped as the raw browser error and could cancel the already dispatched output producer.
- Cached replay awaited decoding before resuming a suspended AudioContext, losing the opportunity to call resume directly in the replay gesture.
- Realtime capture awaited AudioContext.resume before invoking getUserMedia when the context was suspended/interrupted. Batch recording reported its generic error callback before its specific permission rejection could be classified.

Start/Resume now synchronously primes one nonmuted audio element with a local silent WAV, confirms the actual play promise, and reuses that same element across successive media sources. A denied/unsupported priming path uses the existing complete-file WebAudio decoder; it never fabricates permission. The media element is disposed when its context/session is disposed. Supported MP3 MSE and WebAudio features are detected, including the prefixed AudioContext fallback.

A later NotAllowedError/SecurityError, or failed context resume before progressive output starts, leaves capture locked while the same bounded producer download and SHA-256 validation finish. The completed text and bytes survive. The existing Resume button then plays those stored bytes under a new gesture, with no provider retry, duplicate input, or synthetic success. The final producer digest must still match the completed turn. Replay resumes WebAudio before any decode/fetch await. Mic and context activation begin synchronously in Hold, with separate typed errors and late-stream cleanup. Fixed diagnostic stage/code values contain no speech or account identifiers.

Hold/release intent, pointer cancel/lost capture/keyboard/blur/visibility fencing, first-frame readiness, final PCM flush and manual commit are preserved. Playback and microphone stay mutually exclusive. History/cache and technical renewal behavior remain bounded and unchanged. Start still never opens the microphone. Safari's MP4 MediaRecorder fallback remains feature detected.

## Language audit

[Full code-by-code matrix](qa/kilas-translator-languages-20261019.csv) covers every registry language. Current sources match the documented speech sets: 100 Scribe STT languages, 84 v4 speech languages, and their 83-language intersection for classic two-way Translator. Yoruba is v4-only and is correctly excluded from classic. The other 17 STT-only languages are also excluded. Text-model capability is not treated as speech capability.

The active classic chain is `scribe_v2_realtime` (verified realtime mode) or `scribe_v2` (existing batch mode) → existing `gpt-6-luna` → `eleven_v4`, using the chosen original Kilas voice and explicit selected-pair direction. The realtime URL carries both selected ISO codes as repeated `secondary_languages`, no forced single `language_code`, and manual commit. Both full-file and progressive TTS use the selected target code and the same v4 model. The read-only account `/models` intersection gates both picker and server admission; missing/alpha/unavailable models do not silently fall back.

Production read-only Render logs before release confirm `eleven_v4 status=available classic_languages=83` at **2026-10-19 09:00:47 UTC**. Startup at 05:26:24 reports `owner_realtime_ready=true`, `persisted_realtime_proof=true`, `activation_ready=true`; this is the existing durable account proof, not a new paid test. `KILAS_GEMINI_GATE enabled=false policy_valid=false qa_armed=false` confirms the native route is currently disabled. Entitled classic live access remains on, with monetary caps and shared concurrency intact.

The separate native registry has 76 distinct languages for `gemini-3.5-live-translate-preview`, with explicit `zh-Hans` / `pt-PT` defaults. All 76 setup wire values and 5,700 ordered native pairs are validated locally. That registry does not imply native production availability. The separate upload-dubbing registry has 93 targets and 76 explicit STT/dubbing source intersections; it is not substituted for live speech coverage. No language/provider list correction was justified by this audit, so those production registries are unchanged.

Primary sources checked 2026-10-19:

- [WebKit per-element autoplay policy and rejected play promises](https://webkit.org/blog/7734/auto-play-policy-changes-for-macos/).
- [ElevenLabs models and exact v4/STT language tables](https://elevenlabs.io/docs/overview/models).
- [ElevenLabs transcription language codes](https://elevenlabs.io/docs/overview/capabilities/speech-to-text).
- [Realtime secondary_languages and manual commit API](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime).
- [Google dedicated Live Translation language table](https://ai.google.dev/gemini-api/docs/live-api/live-translate).

These are documented/model-account and mocked routing checks, not live linguistic quality certification of all languages or accents.

## Validation and latency limits

- Focused Node suites: **196 tests**, including 7 added Safari lifecycle/gesture/MIME checks; no provider/network access.
- Focused Python suites: **36 tests** (language, both-direction translation, progressive producer, early text, continuation, handoff and restored route). Coverage includes **13,612 classic pair/voice combinations**, **332 batch STT → actual translation adapter → TTS chains** across every language/direction/both voices, and **166 realtime adapter directions**. All transports synthetic; no speech generation purchased.
- Existing native Chromium browser regressions: **6 tests passed**, covering four alternating directions, 320/390/768/1440 layouts, replay bytes, technical renewal, late permission, Stop, progressive decoder starvation, visibility offset recovery, and matched latency.
- Added native Chromium + explicit Safari-style per-element gesture policy: **5 tests passed**, including six translated turns across three scenarios plus stored-byte replay; repeated turns, output denial followed by explicit Resume, denied prime with WebAudio fallback, and separate realtime/batch microphone denial/reset. Native MP3/MSE/WebAudio decoders; synthetic media input/provider boundaries, exact cached replay bytes, no overlapping mic/output and no duplicate paid adapters. This does not emulate Safari's complete engine or OS.
- Full Translator Node sweep on pristine `ed519ad9`: 236 tests, 224 pass, 12 fail. Candidate before the final extra MIME case: 242 tests, 230 pass, the **identical 12 failing names and no added failures**. These existing failures concern obsolete auto-listening page fixtures/missing Hold nodes, old Stop label, duplicate-language page fixture, and two segment expectations. They were reproduced in `/tmp/kilas-safari-baseline`; broad CI is not claimed green.

[Controlled timing evidence](qa/kilas-translator-safari-benchmark-20261019.json): with artificial 200 ms text processing + 100 ms first TTS prefix + 1,100 ms tail, native Chromium first-audio onset proxy was **647.7 / 600.6 ms** for ID→EN / EN→ID with progressive playback versus **1,656.7 / 1,633.7 ms** for complete-file playback, N=2 per arm. Those measurements are local browser evidence, not live supplier/acoustic latency. Start/Resume priming adds no release-path wait; release still flushes, drains uploads and commits immediately, with early final text and numeric stage metrics retained.

Real release→final text / first audible output at 1–2 seconds remains **unverified**. Historical paid backend measurements were approximately 6.65–6.82 seconds; this change does not remove provider processing/credit verification or claim that target. No paid QA was needed for this browser repair.

Actual WebKit installation was attempted under `/tmp`; Playwright's CDN and Microsoft mirror returned proxy HTTP 403. Direct production HTTP also returned proxy 403. No physical iPad, authenticated production browser, or actual microphone/speaker acoustic test was available. Production deployment status/commit and startup evidence are reported separately after the authorized release.
