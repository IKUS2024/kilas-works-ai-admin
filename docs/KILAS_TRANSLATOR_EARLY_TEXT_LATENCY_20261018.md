# Translator final-text latency — 2026-10-18

Scope: show the full validated translation as soon as available, while the unchanged single TTS operation continues. No partial ASR/model text, provider/model/voice changes, paid QA, automatic replay, Finance changes, or sandbox configuration changes.

## Verified bottleneck and change

The live PTT client already streams PCM during the hold and flushes the final partial frame before manual commit. Its 3000ms flush timer is a failure deadline, not an intentional release delay. Final text previously remained hidden until TTS completed. The worker now publishes the complete validated source/translation/language pair before the existing fresh credit check and audio reservation. The owned turn GET exposes this immutable snapshot while status remains PROCESSING; it does not expose an audio URL or mark the job complete. The client adds one text bubble, keeps capture/replay locked, then attaches one stored-audio replay to the same bubble when the existing audio job completes. TTS failure preserves the text with the existing truthful error and no fake audio. End/abort suppresses late publication on the client; no old speech is uploaded or synthesized again.

Telemetry distinguishes session preparation/admission, microphone readiness, PCM preparation/upload, release-tail drain, commit HTTP acknowledgement, first complete text, audio start, and playback completion. Browser monotonic durations are separate from server monotonic durations. Commit HTTP acknowledgement is not provider STT completion. Audio-start is a browser playback-onset proxy, not hardware audibility.

## Measurements and limits

Historical sanitized production backend logs, N=2 (11:37/11:38 UTC): final STT 152.7/217.2ms; full translation 2997.9/3310.9ms; fresh TTS credit check 1064.7/1193.6ms; first TTS byte 5321.7/5801.7ms; whole backend 6648.1/6818.7ms. Backend mean 6733.4ms and translation mean 3154.4ms. These server measurements do not measure owner release-to-screen or physical audibility and are not an apples-to-apples after comparison.

Controlled cloud-executor Chromium experiment: same real local app routes, synthetic microphone, actual fixture MP3 decoding/playback, fixed 200ms model and 1000ms TTS suppliers, no external/paid calls. N=3 per arm at 390/768/1440px, alternating ID→EN / EN→ID / ID→EN with short/question/longer negation/names/numbers fixtures. Baseline disables only early publication; both arms otherwise use the same client. Synthetic rate-window clock advances 61s between arms without deleting ledger/history or changing caps.

| Release metric | Before (ms) | After (ms) | Mean before → after |
|---|---|---|---|
| First final text | 1384.4, 1396.7, 1361.6 | 381.9, 324.3, 312.0 | 1380.9 → 339.4ms |
| Browser audio-start proxy | 1401.2, 1409.3, 1383.1 | 1443.2, 1387.1, 1383.4 | 1397.9 → 1404.6ms |

Complete text is earlier by 1041.5ms mean under this fixture. **Audio optimization is not delivered: onset is unchanged. Real after-provider N=0; a real 1–2s final-text goal and physical Android/iOS audio latency are not verified or guaranteed.** Existing real translation alone was roughly 3s. The current safe release removes the additional TTS wait from text without lowering quality or bypassing funding.

Official current contracts: [Scribe realtime](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime) supports manual commit and distinguishes partial from committed transcripts; [HTTP TTS streaming](https://elevenlabs.io/docs/api-reference/text-to-speech/stream) exists. The application currently buffers bounded MP3, validates duration/settles, then decodes the complete file in Web Audio. Provider streaming support is not claimed absent. Incremental audio playback would require a separately validated bounded transport/player and settlement/cancel lifecycle; it would still follow stable STT, the full translation, and fresh funding check. No speculative streaming/credit/model change was made here.

Next smallest audio investigation: one newly authorized short ID→EN synthetic utterance with release, STT, final translation, fresh credit, first provider byte, complete bytes, browser playback-onset timestamps, no retries. That establishes whether a streaming transport can remove meaningful post-first-byte wait. A fresh explicit bounded QA budget/credit verification is required first; historical one-shot approvals are consumed. No dollar estimate is invented and no further provider calls are authorized by this document.

## Focused validation

- Final Node: 70/70 PASS across early-text, API, hold, realtime/PCM and recovery. Earlier 33/22 runs are overlapping subsets, not extra unique tests.
- Python: 15/15 PASS across whole-utterance, handoff/watchdog, two-way direction and early-text tests. Barrier test confirms complete text appears while fresh TTS credit blocks, status remains PROCESSING, audio GET is unavailable, and a credit failure makes zero TTS calls.
- Cloud Chromium hold lifecycle: 2/2 PASS; start does not open microphone, directions/replay/renew/Stop remain coherent, late permission after release/Stop is cleaned up.
- Matched browser benchmark: 1/1 PASS, six synthetic turns, exactly six mocked model/STT/TTS operations, zero paid provider requests. One row is promoted once; no mic during pending audio/playback; stored replay adds no provider operations.
- Test maintenance: an old whole-utterance expectation `no_speech` was already `translation_ambiguous` on unchanged HEAD (baseline reproduced); assertion updated without changing recognition semantics. Recovery page fixtures lacked existing hold/history DOM nodes; restored those fixture nodes. Timing assertion now selects its named metric rather than assuming it is the first metric forever.
- Physical phone microphone/acoustic accuracy, production authenticated UI and paid-provider latency are not tested. Public production HTTP access from this environment has historically been proxy-blocked.

Evidence: `/tmp/kilas-translator-early-text/benchmark.json`, `client-metrics.json`, `completed-1440.png` (visually inspected), `/tmp/kilas-translator-early-text-node-final.log`, `/tmp/kilas-translator-early-text-python.log`, `/tmp/kilas-translator-early-text-hold-browser.log`, `/tmp/kilas-translator-early-text-browser.log`, `/tmp/kilas-translator-early-text-baseline.log`. Temporary evidence is not durable artifact storage; this document preserves the results. Release identity and post-deploy non-generating checks are reported separately.
