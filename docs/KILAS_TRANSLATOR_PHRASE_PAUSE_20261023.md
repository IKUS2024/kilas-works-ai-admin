# Translator phrase pause release

Base: production/main `425df2bca25cbd47f3d8923f96bd477a55d88233`.

The clauses relay now observes PCM silence and requests a manual STT commit after
800ms quiet following at least 400ms voiced PCM, at existing <=1s transport-frame
boundaries. Only the committed provider acknowledgement enters translation.
Pause commits flush a punctuation-free tail; fixed 4s commits still retain an
unfinished tail. No partial hypothesis is spoken or regenerated.

The duplex client keeps the same supplier lease through short conversational
pauses. It closes after 10s idle, Stop, or the existing 120s rotation boundary.
Capture continues during phrase rendering/playback. Existing bounded queues,
120s rotation drain, 8s rollover buffer, verified browser echo-cancellation gate,
End cancellation, recovery verification, batch fallback and progressive MP3
playback remain in force. Automatic acoustic barge-in is not added.

No model, voice, language-pair policy, provider admission, monetary cap, Finance,
Voice Over or shared layout change. TTS remains the existing model-catalogue-gated
`eleven_v4` HTTP streaming request with the saved voice. Official HTTP TTS docs
accept a model with `can_do_text_to_speech`; standard TTS WebSocket is a different
interface and is not substituted. Account-specific live compatibility has not
been re-proven with paid calls in this release.

Numeric `KILAS_LIVE_CLAUSE` translation/first-audio/completion measurements were
added without transcript, identity or credentials. These measure server work,
not audible device latency. The earlier 3–5s target is unmeasured, not a promise.

Local offline validation: 12 clause tests, 25 relay tests, 43 focused JS tests,
and one actual Chromium/Flask two-direction synthetic-media test passed. Network
to external providers was blocked and supplier calls mocked. The full JS suite
has 12 pre-existing failures reproduced on a clean production-base checkout
(273/285 passed). A separate phrase-stream CI job covers the affected path;
existing broad checks remain enabled. No paid provider test ran.

Official references:
- https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime
- https://elevenlabs.io/docs/api-reference/text-to-speech/stream
- https://elevenlabs.io/docs/overview/capabilities/text-to-speech/eleven-v4
- https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/tts-vs-ttd-websockets
- https://render.com/docs/deploys
- https://render.com/docs/health-checks

Remaining acceptance: physical Android/iOS browsers, headset/speaker echo,
sentence-boundary/negation quality and measured p50/p95 phrase-end-to-audible
latency using an explicitly approved paid-test budget. Continuous capture still
requires the tab to remain active; backgrounding pauses safely.
