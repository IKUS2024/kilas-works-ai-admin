# AI Call conversation understanding — 2026-10-17

Scope: AI Call microphone capture, provider turn detection and playback input
suppression. Base: f6d09a66a6d46b4da83cda3645d9d428ca1e502d, including hidden Group
navigation and all preceding Finance work. No Translator, Voice Over, Finance,
Group, pricing or Creative Services implementation was changed.

## Evidence and limits

Render runtime log at 2026-10-17 01:47:39 UTC shows the reported call sent 20,300 ms
of input and received 13,680 ms of output, ending normally with zero interruptions.
It contains no input transcript and therefore cannot establish what the provider
heard. The screenshot's generic clarification is not sufficient to identify a cause.

A deterministic test of the previous capture adapter reproduces a definite input
loss: all 6,363.9375 ms of a quiet Indonesian question are discarded because every
200 ms frame stays below the local 0.015 RMS admission gate. Corrected Call capture
forwards all 203,646 speech-fixture bytes, byte-for-byte. Maximum frame RMS is
0.01149961. A loud syllable after quiet speech would admit only the short retained
pre-roll rather than the full question. This is a confirmed failure mechanism,
not proof of the exact acoustic conditions on the user's device.

The previous client also stopped sending input during playback without telling
the automatic VAD that the stream had stopped. Google documents continuous input
for automatic VAD and requires audioStreamEnd for pauses over one second:
https://ai.google.dev/gemini-api/docs/live-guide#automatic-vad
The correction sends equal-duration zero PCM while the assistant speaks, preserving
the VAD sample clock without returning speaker audio to the provider. A 300 ms
clearance interval after the output device drains precedes Listening. Tests fence
late output, End and new-answer races through this interval.

## Focused correction

- AI Call has its own bounded capture adapter; the shared PCM worklet and all
  Translator capture code remain unchanged. Quiet speech and initial silence reach
  the provider without a local speech threshold.
- Existing PCM conversion remains mono signed PCM16 little endian, 16 kHz input,
  24 kHz output. Device rate conversion tests pass at 16, 44.1 and 48 kHz.
- Provider VAD allows 1,200 ms pauses with low end-of-speech sensitivity. Existing
  NO_INTERRUPTION turn-taking remains: speak when Listening; End always works.
- The conversation stays in the same provider session, including existing context
  compression and supported fresh-checkpoint resumption. No local transcript replay
  or new per-turn session is introduced. Prompt instructions explicitly retain
  prior call details and avoid inventing requests from silence or unclear input.
- Input transcription is enabled for safe counts only. Runtime logs contain aggregate
  RMS, peak, duration, turn count and transcription character count; they never log
  user audio, words, secrets or provider exception bodies.

## Local verification

- 27 Python AI Call tests: authentication/CSRF, ownership, admission, normal metering,
  long-call renewals, End, bounded transport, provider resumption and diagnostics.
- 5 Python smoke-fence tests: default off, service and short-expiry checks, child
  launch, fixture hashes and durable once marker preventing restart duplicates.
- 31 Node AI Call tests: quiet capture, source-rate/channel conversion, sequential
  dispatch, playback silence and echo clearance, cancellation and jitter buffer.
- 4 actual Flask-rendered DOM locales: unchanged composer, modal and End controls.
- 19 existing shared capture/encoding/Translator transport regression tests pass.
- Actual Chromium synthetic microphone: getUserMedia -> AudioWorklet -> CallCapture,
  48 kHz context, one input channel, 36 frames / 230,400 PCM16k bytes (7,200 ms),
  32 voiced frames, no capture error, zero post-End frames and all tracks ended.
  Chromium's AGC raised this input's measured maximum frame RMS to 0.14069; this
  browser result must not be confused with the quieter direct worklet fixture.

These are separate layers of evidence. None verifies a physical Android microphone,
speaker/headset, acoustic echo cancellation or a real provider conversation.

## Bounded production provider validation

`kilas_ai.ai_call_smoke` is OFF by default. An explicit run ID plus a <=30-minute
expiry and the exact production service ID are required to launch a child. It uses
the existing account policy, key and normal Call admission. A fixed operation ID and
normal database uniqueness fence prevent another paid attempt after a restart.
The child permits one provider socket and one normal reservation, refuses renewal,
stops within 70 seconds / 55 input seconds, and has a 78-second process backstop.
No feature flags, quota, plan or credentials are relaxed or replaced.

The fixture manifest supplies two Indonesian and two English discussion questions.
Each follow-up requires the previous answer's context. The first question is quiet.
Checks include initial silence, a non-speech interval, provider-heard subject,
expected answer, output PCM, normal settlement and End cleanup. Only booleans and
numeric measurements are logged. Run results and LIVE deployment evidence must be
reported separately after execution; no provider success is asserted by this file.
