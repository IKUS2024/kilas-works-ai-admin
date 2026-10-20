# Translator pending playback correction — 2026-10-20

Baseline: `20ee2ce053323ea86f5f76c3d45e27d6b17083d7`. Scope: Translator browser progressive playback only. No provider calls were made for this work; all speech and translation responses were local fixtures.

The progressive decoder appended the first audio prefix and awaited `HTMLMediaElement.play()` before fetching the next prefix. That promise resolves only when playback starts. A browser requiring more than the first ~0.25 seconds of MP3 could therefore wait for bytes that the same loop had stopped downloading, until the existing five-second startup timeout. The new deterministic regression fails against the original implementation and passes with this change.

One owned playback attempt now runs concurrently with sequential bounded fetch/append operations. Its rejection is consumed immediately, cancellation checks fence late success/rejection, and completion still waits for the playback attempt. The existing five-second bound, final digest, one stream, byte caps, permission-denial download/cache behavior, replay and explicit Resume remain. `progressive_start_wait_ms` measures the first start attempt through successful playback. Translator entry and progressive module URLs are versioned for browser cache invalidation.

No STT endpointing, translation text/context/model/reasoning policy, ElevenLabs voice/model, TTS requests, quota/reservation/settlement, DB fences, Start/tap/Stop interaction, or other product implementation changed. Complete validated translation remains required before speech dispatch.

## Validation

- Six new Node cases: second-buffer startup; permission denial drains/caches the same audio; cancellation with late rejection; decoder rejection; unresolved startup timeout; cancellation with late success. The second-buffer case fails before the change (`audio_stalled`, no second read) with an injected 80 ms timeout representing the production 5-second bound.
- Focused progressive, Safari-policy, toggle and playback Node suites: **65 passed**.
- Full Translator Node glob: **272 tests, 260 passed, 12 failed**. Independent pristine-baseline run: **266 tests, 254 passed, the identical 12 failure names**. These existing failures are older DOM contracts and segmented timing expectations; no new failures. Logs: `/tmp/kilas-translator-pending-play-node.log`, `/tmp/kilas-translator-node-baseline.log`.
- Existing four real Chromium progressive browser tests passed: complete/progressive alternating directions and replay, Stop during playback, visibility/resume with cached audio, and slow-tail starvation. The first run loaded four tests before the new fifth test was inserted.
- New fifth browser test passed separately: real Chromium MP3 decoder at 390×844, first 4096-byte prefix, synthetic 350 ms delayed tail, and an explicit synthetic 0.5-second startup-buffer policy. **Release-to-browser-onset 400.4 ms**, one play and one simulated TTS dispatch, full completion/replay retained. This is a controlled fixture result, not live-provider latency. Log: `/tmp/kilas-translator-pending-play-browser.log`.
- Existing Safari-policy browser suite: **5 passed** under Chromium permission emulation. Log: `/tmp/kilas-translator-pending-play-safari.log`.
- Independent backend regressions: **21 passed** across progressive output, language mapping and complete language contracts. Log: `/tmp/kilas-translator-stream-backend-tests.log`.

## Capability evidence and limits

[MDN play()](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/play) documents that the returned promise resolves on actual playback and may be delayed. [ElevenLabs HTTP stream](https://elevenlabs.io/docs/api-reference/text-to-speech/stream) documents streaming the generated audio for supplied text. The existing Translator language payload uses `eleven_v4` and the existing selected voice; this correction does not switch models, voices or endpoints. The deprecated provider latency knob was not enabled. No provisional translation fragments are spoken.

This removes browser startup self-starvation; it does not remove translation-provider first-token latency. There is no new paid production timing sample and no physical Android/iOS verification. Safari policy tests emulate permission behavior in Chromium; they do not certify Safari hardware.

Optional future live measurement, requiring separate paid-call authorization: two synthetic turns (one Indonesian→English, one English→Indonesian), at most eight seconds input and 200 source characters each, total cost cap US$0.10, no retries. This proposal was not executed.
