# Selected-tab live assistance — bounded offline implementation

The owner's primary goal is captions/translation while watching a selected YouTube tab, and editable answer assistance during a browser call. This work adds that path directly at `/kilas-ai/live-assist`; it does not expand project dashboards or script organization. Local transcription commit `483804a502656753e70bb1a04a513f71416812ee` is preserved as the parent. Existing production project activation remains unchanged.

## Current availability and exact blocker

`KILAS_LIVE_ASSIST_ENABLED` defaults **off** and has not been set in production. The page/API require the existing authenticated Kilas AI CLIENT_OWNER gate, without changing authentication or permissions. No production feature flag, deploy, credential or billing change happened in this task. Code is handed off locally with a reviewable commit/patch; no live-success claim is made.

With the new flag enabled in an approved environment, capture itself is real browser code: clicking the start button immediately opens Chrome's picker, only after capture consent. The app rejects window/monitor selection and missing shared-tab audio. It requests system audio exclusion, monitor exclusion, self-tab exclusion and no tab switching. A separately consented processing checkbox is disabled while provider readiness is false. Thus local tab selection/level indication is possible without pretending captions exist or submitting paid work.

Paid pipeline readiness reuses the previous `transcription_provider.budget_ready()` **hard False** guard. A flag or API key cannot bypass it. Existing usage/billing lacks an approved STT reservation/settlement path. No existing billing policy was altered. Before a real end-to-end run, approval must cover a strictly bounded owner QA cost exception/reservation, account scope, runtime activation and actual browser-source consent; merely enabling the flag cannot authorize or unlock paid inference. Existing OpenAI key/model permission and real Chrome selected-tab audio delivery are not production-verified. The previously denied production browser/network access was not bypassed.

## Smallest proposed paid QA, not executed

One owner-controlled, non-sensitive video/call tab, **one session <=120 seconds**, at most **12 STT chunks**, **12 translations**, and **3 explicitly requested answer drafts**, with **US$0.10 maximum approved provider spend**. STT uses verified `gpt-4o-mini-transcribe`; translation/reply uses existing server-owned `model_policy.luna_model()` (`gpt-6-luna`) with `max_completion_tokens=512` and low reasoning effort. Existing credentials are reused, never created or reconfigured.

Official standard estimates checked 2026-10-10: mini transcription $0.003/minute (about $0.006 for two minutes); existing text model $0.10/million input tokens and $0.50/million output tokens in short context. Text is bounded to <=4,000 characters per caption, <=2 caption context items plus <=1,200 characters of user facts for a reply, and 512 completion tokens per call. Estimated total is below the proposed $0.10 cap with headroom. These are estimates, **not an implemented monetary reservation or guaranteed charge ceiling**. The missing capped QA budget enforcement must be approved and implemented before opening the hard guard. Cancellation/timeouts can still incur accepted-provider cost, so automatic retries remain forbidden.

## Browser/audio implementation

`TabAudioSession` uses `getDisplayMedia` only from a trusted click and capture consent. No `getUserMedia` call exists in this tab workflow. The required video track is kept solely to validate the selected browser surface and detect sharing termination; no video frames are recorded or transmitted. Only selected-tab audio tracks feed the Web Audio graph. Ordinary phone system audio is not promised.

The actual AudioWorklet downmixes to mono and forms independent 16kHz/16-bit WAV files every 10 seconds, including a fresh header per file. This deliberately avoids treating MediaRecorder timeslices as separately decodable files. Output to the destination is silent; a level meter and persistent Audio tab aktif indicator display capture state. There is no auto-speech, auto-send, realtime assistant voice or YouTube downloader.

The client stops at 120 seconds or twelve chunks, discards a tail on stop, fences late picker/worklet/network results, and releases tracks/nodes/context/timers on stop, source end, processing error or pagehide. At most one request and one pending chunk exist; overload stops capture instead of building an audio backlog. New requests are not retried automatically. A slow initial provider-session start also stops capture rather than dropping a chunk and pretending sequence continuity.

## Ephemeral provider integration

The server stores only bounded **in-memory** session state, never a project/DB/job row or audio file. A daemon expiration timer purges captions/results after 120 seconds even without another request. Stop immediately removes the session and text; already accepted HTTP calls may continue until their response/read timeout and their late outputs are discarded. Connect/read timeouts are not an overall end-to-end deadline, and cancellation does not undo accepted-provider cost. No background inference worker, local/sessionStorage retention or transcript history is added.

Owner/session nonce, sequence ordering, audio digest and lock guard requests. Only one chunk can process per session, at most twelve are accepted, exact successful repeats reuse cached results, and failed/inflight repeats cannot replay paid work. WAV headers/channels/sample width/rate/frames/size are checked; each file is <=10 seconds and <=512KiB. Digital-zero chunks are skipped without STT or fabricated captions. The server rechecks that a session still exists after STT, before starting translation, so stopping can fence the second paid operation too. Requests use existing `OPENAI_API_KEY`, fixed provider URLs, sanitized errors, bounded JSON, no redirects and no automatic retries.

Source text and translation update per completed chunk. Nominal delay is 10 seconds plus measured-provider/network latency; no word-level streaming or latency/accuracy guarantee is claimed. Slow providers trip bounded backpressure. This is a small chunk architecture, not an already-proven Realtime deployment.

Call mode offers an explicit draft button, latest-two-caption context and user-entered factual context. Prompt forbids invented interview experience, achievements, credentials and commitments; missing facts require clarification or a marked placeholder. The text remains editable and user-reviewed. This is not a guarantee against all model hallucinations; live QA must inspect source accuracy and draft grounding. The app never speaks or sends the answer.

The session registry is process-local. Restart, another worker or loss of process affinity fails closed rather than recovering/resubmitting paid work. Wider deployment requires shared, expiring reservations/limits or a deliberate single-process QA scope, not an unreviewed persistent-data addition.

## Verified offline evidence

- **17 live-assistance Python cases** cover default flag/role/CSRF/consent, validated chunks, owner isolation, ordered/deduplicated calls, silence, parallel-request limits, failures, stop/late response fencing, expiry and explicit reply limits/grounding instructions.
- Chromium page QA uses fully injected display tracks and synthetic provider responses: local indicator while paid readiness is blocked, source+translation rendering after a fixture chunk, editable reply, preserved user facts, desktop/mobile overflow checks, and cleanup. Actual microphone, tab chooser, speech output and external requests are blocked or replaced at the test boundary.
- A separate Chromium OfflineAudioContext executes the **shipped AudioWorklet**, not a stub, on generated PCM. It yields one standalone 320,044-byte WAV for ten seconds, silent destination output, and zero capture calls.
- Combined verification: **82 Python cases passed, 1 skipped** (opt-in disposable PostgreSQL transcription case; previously tested in its own release). **26 Node cases passed** (9 new tab/PCM/queue lifecycle + 10 listening + 7 voice-recorder lifecycle). Browser QA found and fixed unbound native timers; the same small fix preserves the existing local recorder implementation.
- Screenshots: `/tmp/kilas-live-qa/desktop.png`, `mobile.png` are synthetic QA images, not production or real YouTube evidence. CI configuration adds the tests; CI is not claimed green until pushed.

Finance, Trading, auth/logout, billing/pricing, credentials, provider configuration and existing production flags are untouched. No paid call, real capture, customer record query or deployment occurred.

## Official references

- [Chrome screen-sharing controls](https://developer.chrome.com/docs/web-platform/screen-sharing-controls): tab selection/audio and exclusion hints; hints do not replace post-selection validation.
- [Chrome AudioWorklet](https://developer.chrome.com/blog/audio-worklet): secure-context worklet loading, processing and transferable messages.
- [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text) and [API reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create): verified model, multipart WAV and JSON. Streaming a completed file is different from continuous Realtime audio.
- [OpenAI chat completion reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and [pricing](https://developers.openai.com/api/docs/pricing): bounded existing text-model integration and cost proposal.
