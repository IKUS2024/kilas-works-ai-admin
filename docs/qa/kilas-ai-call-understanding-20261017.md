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
- Quiet input receives bounded Call-only gain when RMS is between 0.002 and
  0.06: target RMS 0.06, maximum 8x gain, peak capped below 0.95. Silence, very
  low-level noise and strong browser AGC output remain byte-identical.
- Provider VAD allows 1,200 ms pauses with high start and low end sensitivity. Existing
  NO_INTERRUPTION turn-taking remains: speak when Listening; End always works.
- The conversation stays in the same provider session, including existing context
  compression and supported fresh-checkpoint resumption. No local transcript replay
  or new per-turn session is introduced. Prompt instructions explicitly retain
  prior call details and avoid inventing requests from silence or unclear input.
- Input transcription is enabled for safe counts only. Runtime logs contain aggregate
  RMS, peak, accepted/successfully sent duration, packet/event counts, turn count
  and transcription character count; they never log
  user audio, words, secrets or provider exception bodies.

## Local verification

- 27 Python AI Call tests: authentication/CSRF, ownership, admission, normal metering,
  long-call renewals, End, bounded transport, provider resumption and diagnostics.
- 5 Python smoke-fence tests: default off, service and short-expiry checks, child
  launch, fixture hashes and durable once marker preventing restart duplicates.
- 34 Node AI Call tests: quiet capture, source-rate/channel conversion, sequential
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

## Actual provider attempt and follow-up correction

At 01:58:33 UTC, deployment dep-db9dc1navr4c73dl2t1g (7667d077fda7e72397236663afcde8f66d9fb5ed)
started exactly one production smoke. It established one provider connection and
passed setup. Initial silence generated no response. It stopped at the 70-second
deadline on the first quiet Indonesian fixture: 39,163.9 ms of total input was
accepted, output was 0 ms, transcription character count 0 and completed turns 0.
The aggregate input RMS was 0.00285 with peak 0.05685. End took 204 ms, no output
frames remained and normal metering settled. No second paid attempt was made.

This does NOT verify a working multi-turn conversation. At this revision there
was no successful-send byte counter, so accepted bytes must not be described as
proof that every byte reached the provider. The silent result is consistent with
low-level input not triggering provider VAD, but does not establish that as the
sole cause. Physical Android input and provider resumption remain unverified.

The browser measurement showed AGC can raise the same fixture substantially,
while the direct backend smoke lacked browser AGC. The follow-up adds the bounded
Call-only gain above so quiet input is less dependent on a device's AGC, requests
sensitive provider speech onset, and records successful socket-send byte counts
separately from acceptance. Tests show 27 quiet frames receive gain, no sample is
lost or clipped, and the fixture peak reaches 0.45190. This correction has local
verification only; no claim of a successful real-provider retest is made.

The environment proxy returned HTTP 403 for direct custom-domain and Render-host
health/asset probes, including an escalated public read. Render's deploy status
and production logs are the available LIVE evidence. A physical Android test and
an explicitly authorized additional bounded provider test are still needed before
claiming the original end-to-end complaint is resolved.
