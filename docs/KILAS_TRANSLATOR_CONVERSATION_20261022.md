# Translator conversation control, 2026-10-22

Baseline main and Render Client Hub LIVE were both `3c53da37016cd6fd2700d84e76de269da2a2fb43`.
Public production JS returned HTTP 200 with `recordOnStart:true` and without
`continuous:true`. The startup report selected ElevenLabs and confirmed
`realtime-v1` input for the existing entitled audience. The account probe's
`prepaid_only` result is Creator-specific in current source; persisted Scribe
wire proof is present. No entitlement or paid connection was inferred from docs.

## Diagnosis and supported architecture

Scribe PCM input already streamed to the server and its provider WebSocket while
the user spoke. The UI nevertheless required Stop before translating each whole
turn, then required another Start. Existing v4 speech already supports progressive
output playback. This change connects that pipeline into a continuous *sequence
of turns*, with no new service, key, model, pricing or budget configuration.

Start records; a 1.2-second local speech pause commits the current turn; the
existing metered text translation and natural v4 voice output run; after output
finishes the microphone opens for the next direction. The mic is closed during
processing and playback, preventing generated audio from entering the next turn.
Stop flushes current speech, or drains already admitted output, then stays ready.
End still cancels the session/output immediately. Pointer release never submits.

Conversation continues until explicit Stop/End or an existing lifecycle/error
condition. The initially introduced 20-turn/10-minute run caps were removed to
restore continuous usability. Server concurrency, per-utterance leases, admission,
balances and durable supplier-cost reservations remain unchanged. No automatic retry/regeneration after a
failed utterance; recovery verifies existing work and requires a new Start.
Background/blur cancels continuation. Batch fallback remains explicitly manual,
with different visible instructions; it is not called streaming.

This is not simultaneous/full-duplex translation. It does not play draft
translations while a speaker is still talking. The 1.2-second endpoint is a
configured delay, **not measured end-to-end latency**. Semantic pauses inside
sentences can split turns; users should speak in complete phrases and wait for
the Listening state. Mobile acoustic quality and actual provider latency remain
unverified in this release.

## Official documentation checked today

- [Scribe realtime](https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime): partial and committed transcripts, PCM and manual/VAD commits; transcription alone does not translate.
- [Streaming TTS](https://elevenlabs.io/docs/api-reference/text-to-speech/stream): text-to-audio streaming, separate from translation.
- [Realtime Translation](https://elevenlabs.io/docs/api-reference/realtime-translation/v-1-translation-realtime): a real unified endpoint exists, but currently Enterprise workspaces only. Its documented TTS choices include v4 turbo, not the current `eleven_v4` configuration. It was not called or enabled. Switching requires separately verified entitlement, voice/model compatibility and bounded pricing authorization; no upgrade is authorized here.

Existing language selection is unchanged: selected A/B, documented STT/TTS
intersection, live account model catalogue and voice checks remain authoritative.
No claim that every language/voice combination has been acoustically tested.

## Validation

- 135 focused Node tests passed, including 8 new conversation tests: streaming
  PCM before commit, exact pause boundary, repeated turns, no duplicate callbacks,
  mic/output exclusion, Stop during processing/playback, manual flush, batch
  distinction, continuation beyond 20 turns/10 minutes, retired callbacks after Stop/End,
  and failure/visibility behavior.
- 25 Python realtime tests passed with real disposable SQLite and mocked providers.
- 4 actual Chromium/Flask toggle tests passed, including two automatic opposite
  directions, exactly two commits/TTS calls, no batch dispatch, Stop during audio
  preventing recapture, initial gesture, double-click protection and silent Stop.
- Windows lacks `fcntl`/`resource` imported by unrelated sandbox startup. The local
  test launcher supplied fail-on-use module placeholders only for those imports,
  denied external Python networking and left Translator/Flask/SQLite real.
  This is not Linux sandbox validation. No application workaround was committed.
- Broad Node baseline: 272 tests, 260 pass, 12 fail; unchanged baseline archive
  produced the same totals (obsolete DOM fixtures and timing assertions). The
  broad Python flow suite has 5/8 failures in stale response expectations
  including the existing `max_chunk_bytes` field. No backend source changed.
  These broader suites are not represented as green.

No paid speech/model tests, purchase, upgrade, credential/configuration mutation,
customer audio inspection, production data write, or Finance/Voice Over/AI Chat
implementation change. Old checkout and its untracked files were preserved;
work used a separate main checkout under this task's writable directory.

Deployment commit/ID and post-live HTTP verification are reported in the release
handoff after deployment; this document alone is not evidence of production QA.

## Continuity correction validation

The cap-removal revision passed all 135 focused Node tests. Its Chromium run
passed 3/4 cases initially; the silent realtime startup case timed out awaiting
the synthetic microphone. An isolated rerun passed (1/1); no application change
was needed for that rerun. No paid provider calls were made in these checks.
