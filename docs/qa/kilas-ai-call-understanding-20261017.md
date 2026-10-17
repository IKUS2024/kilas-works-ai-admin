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


## Second authorized bounded check

The continuation explicitly authorizes one additional provider session, maximum
90 seconds. No other paid runs are authorized by this continuation. The clear-run
ID has its own durable normal metering marker; the earlier marker is retained.

The first run's safe logs do not contain dispatch counters, websocket event
counts or provider timing. These cannot be reconstructed after its process ended.
Its 39.164 seconds accepted over 70 seconds show substantial pacing loss, and its
input bypassed browser gain. Those limitations prevent attribution of the silent
result solely to a provider defect or solely to quiet VAD.

The new harness uses the browser's 500 ms packet size and one continuous sample
clock. It sends the first fixture after the exact production JavaScript gain
function, with RMS 0.04949 / peak 0.45190. It records accepted and actually sent
bytes, their in-memory digest equality, queue duration, setup completion, numeric
provider errors, known protocol event counts, first-event times, socket send
latency, send gaps, admission latency and pacing lag. No transcripts, raw audio,
keys, session handles or exception bodies are reported.

An audio-response timeout after 12 seconds may use exactly one same-connection
text control to distinguish generation/output transport from audio recognition.
That control never counts as an audio success. There is no reconnect or speech
retry. The entire session deadline is 74 seconds, below renewal at 80 seconds,
with one normal reservation, a 55-second input fence, and an 88-second process
backstop. No policy, plan, credential or quota is changed.

Two complete simulated harness tests verify all four checks and dispatch byte
identity under 300 ms admission latency, and verify the failure/control path
cannot claim audio success. They do not substitute for the provider run.

## Measured second provider result and delivery correction

The clear run used LIVE addc37607fbc65b58139cdb3601af6bd42c93292, deploy
`dep-db9dhi8m7kps73cvnq4g`, at 02:10:11 UTC. It completed setup on one connection
and stopped after 59.272 seconds. There was no provider numeric error reported.
Initial silence did not trigger output. The test failed: the first three response
checks were irrelevant with no expected input subject recognized; the fourth
question timed out. There were 11 input-transcription characters, 12.040 seconds
of output audio and three completed turns. No words from these transcriptions or
responses are recorded in this report.

Safe transport measurements:

- 50,664.6 ms accepted; 50,164.6 ms successfully sent in 102 packets; 500 ms still
  queued at End. Accepted/sent digests differed because of this unsent tail.
- Maximum admission time 1,196 ms; maximum outgoing PCM gap 1,402 ms; maximum
  sample-clock lag 7,405 ms. Maximum actual websocket send time was only 3 ms.
- Setup completed at 1,337 ms from the diagnostic epoch; first PCM send at
  1,888 ms; first input-transcription event at 9,397 ms; first output audio at
  10,599 ms. The socket produced 114 provider messages.
- Known event counts included 10 voice-activity, 5 input-transcription, 42 audio
  model-turn, 10 output-transcription and 3 completed-turn events.
- End took 398 ms, no output frames remained and normal metering settled.
- No additional provider session was started after this failure.

This is evidence of a production audio-delivery defect, not a total provider
outage or merely a stress-fixture gain problem. `Call.accept`, `Call.send` and the
provider receive loop all called full `Call.check`, which opens a fresh PostgreSQL
policy transaction. It also held the Call lock across that transaction. Repeated
admission/read/dispatch checks therefore serialized the real-time audio stream.
Measured gaps exceeded the configured 1,200 ms VAD end-of-speech duration, providing
a supported mechanism for fragmented speech and unrelated clarification responses.
This evidence does not prove every unrelated answer has that sole cause.

The correction removes fresh database authorization queries from steady-state
PCM admission, dispatch and provider-frame handling. Fresh checks still occur at
admission, setup, provider resumption and in the once-per-second watchdog, outside
the audio lock. Packet handling uses a fail-closed three-second authorization
lease anchored to the start of the successful policy check. A database result
older than that lease cannot reauthorize audio. Feature disable, End, liveness,
bounded buffers, sequential indices and existing durable funding boundaries still
apply. Funding uses the unchanged normal budget transactions; plans, quotas,
reserves and ledger behavior are not relaxed. Authenticated HTTP routes continue
to check disabled-account access independently on each request.

New tests hold the policy transaction pending while PCM admission, actual socket
dispatch and provider-frame handling continue within 100/200 ms bounds. Separate
tests verify expired/stale authorization fails closed, campaign and account
revocation, End during a blocked check, and existing metered renewals. All 31
Python Call tests pass. Seven smoke tests, 35 Node Call tests, four rendered DOM
checks and 19 existing shared transport/encoding tests also pass (96 total), plus
the earlier real Chromium synthetic microphone check.

The final database-path correction has unpaid test coverage only. The two staged
provider attempts did not establish relevant Indonesian/English multi-turn
answers or retained context. Physical Android capture/playback and long provider
resumption remain unverified. Do not describe the user's complaint as resolved
until the corrected dispatch path is verified against the provider and device.


## Final authorized three-turn verification

The continuation authorizes one final bounded session on the 83bf993 corrected
Call implementation: Indonesian question, dependent Indonesian follow-up, English
switch. Only the smoke module and its tests change to select these three fixtures;
the production Call implementation remains byte-identical to 83bf993.

The run ID is `call-understanding-final-20261017`. Existing one-connection,
one-reservation, 74-second session / 88-second process / 55-second input fences
remain. No retry or reconnect is allowed. A short final drain distinguishes an
unsent silence tail at End from lost speech. The smoke trigger will be disabled
after this single attempt.

The requested semantic assessment uses bounded input and output text exclusively
from the hash-verified offline synthetic fixtures. This reporting path is a private
child process with no public microphone input, chat history or tools. It does not
log private user audio/transcripts, secrets, session handles or provider errors.
Reports explicitly label this text synthetic. Keyword checks are harness assertions;
semantic and context correctness must be assessed separately from actual synthetic
responses. No success is asserted here before the run completes.

## Final smoke outcome — not resolved

The single final run started at 02:21:19 UTC on LIVE
6507906158456057cee996689eacdec440428f6b / deploy dep-db9dmlvbtjjs73bb6lc0.
Its production Call implementation was identical to 83bf993. Execution recovered
from the environment-disconnected notification; no uncertain attempt was duplicated.

The test stopped after 25.692 seconds during the Indonesian follow-up. All
24,685.8 ms of accepted PCM reached the socket in order: 789,946 bytes, 50 packets,
identical accepted/sent digests and zero queued input. Maximum admission time was
12 ms, sample-clock lag 3 ms, outgoing gap 513 ms and websocket send time 1 ms.
Compared with the prior 1,196 ms admission / 1,402 ms gaps / 7,405 ms drift, these
measurements confirm that the database-stall correction works in production.

Conversation understanding still failed. These are solely offline synthetic
fixtures, not private user speech:

| Turn | Synthetic recognized content | Actual response | Harness check | Semantic assessment |
| --- | --- | --- | --- | --- |
| Indonesian: three apples, buy two more | `S` | `...` | Subject and expected five both absent | Failed: question not recognized; no substantive answer |
| Indonesian: give two to a friend | No transcription/response before timeout | None | No completed follow-up | Failed: no evidence of retained context |
| Switch to English picnic question | Not reached | Not reached | Not tested | Unverified |

First assistant audio started 1,600 ms after the first fixture began, 4,764 ms
before its 6,363.9375 ms input finished. There was only one recognized character,
910 ms of output audio and one completed provider turn. The provider sent two
voice-activity events, one input-transcription event and no reported numeric
error. Initial silence produced no output. The non-speech end check was not
reached. End took 98 ms, output was erased, and normal metering settled.

Independent offline inspection confirms PCM16 little endian, mono, 16 kHz.
The first clear fixture's longest low-energy interval is 600 ms even at a 0.01
RMS threshold, and speech remains present throughout its first two seconds.
This does not explain the early response by an ordinary 1,200 ms silence gap.
It narrows the remaining failure to audio interpretation / automatic turn
segmentation or this synthetic voice's interaction with the provider. It does
not establish a specific provider defect or validate physical-device behavior.

The smallest next controlled diagnostic is one identical short fixture with
provider automatic VAD disabled and explicit `activityStart` / `activityEnd`,
waiting for all PCM dispatch before the end marker. Recognition would distinguish
premature provider activity segmentation from audio interpretation/fixture issues.
This is a proposed isolated diagnostic, NOT a production change or another run.
The API supports that activity-control mode:
https://ai.google.dev/api/live#bidigeneratecontentrealtimeinput

No further paid attempt was started. No broad application or provider-model
change was made after this result. The smoke trigger is disabled for the final
deployment. The user's end-to-end usability complaint remains unresolved despite
confirmed capture and dispatch fixes; do not call this release functionally
verified for discussion, Indonesian/English continuity or physical Android audio.

## Unpaid format, fixture and protocol audit

No additional provider inference request was made in this audit. Temporary local
ASR/SDK packages were installed only under `/tmp`; project dependencies were not
changed. The smoke trigger remains off.

### Reconstructed outgoing audio

An offline test executes production `Call.accept` and `Call.send` against an
in-memory socket with the exact known fixture sequence from the last run. It
reconstructs 50 messages and 789,946 bytes / 24,685.8125 ms: two seconds of silence,
the clear Indonesian question, its follow-up, and the 12.5-second timeout silence.
It is a reconstruction from hash-verified fixtures and the production serializer,
not a recovered runtime/private audio capture. The runtime's accepted/sent digest
comparison was separately successful.

Each decoded message contains only raw signed PCM16 little endian, one channel,
16 kHz, labeled `audio/pcm;rate=16000`; there is no WAV header in the socket PCM.
An independent FFmpeg s16le decode/re-encode produces exactly the same samples.
The reconstructed PCM SHA-256 is
`eb67c14bd47d8e0176e389542a5d6c31b825cac497d63e8c2fd7715e2354c655`.
This matches the provider's documented raw audio format:
https://ai.google.dev/gemini-api/docs/live-api/capabilities#sending-audio

The first fixture was also regenerated with eSpeak NG's Indonesian voice, speed
175, from the full source sentence. Both versions contain 95,423 samples before
padding; waveform cosine similarity after the bounded gain is 0.990789. eSpeak
produces the expected full Indonesian phoneme sequence, rather than synthesizing
just the letter S. This is evidence against a post-processing corruption, but
phoneme output and correlation are NOT an intelligibility assessment.

Direct audio input/listening is unsupported by this execution interface. An
independent local faster-whisper/base int8 CPU transcription was attempted, but
public model-weight downloads failed with proxy HTTP 403/ProxyError, including an
escalated read. Official OpenAI and the original whisper.cpp model hosts were
also inaccessible. No paid transcription service was substituted. Consequently,
independent semantic intelligibility of this synthetic voice remains UNVERIFIED.
The reconstructed synthetic WAV is retained for a permitted local ASR or listener.

### Official SDK and schema comparison

Google's `google-genai` 2.31.0 validates the current `LiveConnectConfig` locally.
The model is `models/gemini-3.8-live`; input/output transcription, AUDIO response,
Kore voice, context compression, resumption and automatic activity configuration
are supported fields. Unsupported thinking or translation configuration is absent.
An in-memory `AsyncSession.send_realtime_input` serializes the same MIME and exact
decoded PCM bytes as our sender. SDK snake_case/our documented camelCase names and
URL-safe/standard Base64 spellings are equivalent ProtoJSON representations, not
an identified wire defect. No SDK client, credentials or network socket is used
for this comparison.

Sources:
https://github.com/googleapis/python-genai/blob/main/google/genai/live.py
https://github.com/googleapis/python-genai/blob/main/google/genai/_live_converters.py
https://protobuf.dev/programming-guides/json/#representation-of-each-type
https://ai.google.dev/api/live

### Packet timing and local segmentation

The final run used mostly 500 ms packets with 364/322 ms final speech tails, not
tiny PCM fragments. The first fixture has only 600 ms maximum low energy; a local
10 ms-window energy reference with 1,200 ms silence produces one segment: voice
210–5,790 ms, finalized at 6,990 ms. Changing wire packets between 10, 20, 100, 200
and 500 ms does not change that result. This is a silence-timing reference; it
DOES NOT emulate Gemini's learned VAD or prove provider segmentation is defective.

One evidence-backed harness correction was made: prerecorded packets had been
sent at their sample interval's start, giving the provider up to 500 ms of future
audio compared with a real microphone. The harness now waits until each packet's
sample interval ends. A regression test fails if bytes are sent before they could
have been captured. This bias cannot account for the observed 4,764 ms early reply.
No production VAD, provider model, transcript pipeline or other feature was changed.
The two new wire/segmentation tests and seven harness tests pass without provider IO.

### Proposed next diagnostic — not authorized or run

First prerequisite: independently establish that the retained synthetic question
is intelligible via a human listener or an accessible local ASR model. The current
interface cannot complete that prerequisite. No conclusion attributing failure
solely to provider VAD should be made before it is met.

If the prerequisite passes and a single diagnostic is authorized, use the same
6,363.9375 ms / 203,646-byte `id-first-clear.wav` payload in one new connection:

1. Keep the current model, prompt, voice and normal metering. In this private test
   only, disable automatic activity detection and cap output at 128 tokens.
2. Send `activityStart`, then the entire hash-verified PCM in capture-end-paced
   200 ms packets. Confirm all bytes are dispatched before sending `activityEnd`.
   Do not send `audioStreamEnd` in this manual mode.
3. Await one answer for at most eight seconds, with a 25-second whole-session
   deadline, one normal reservation, no reconnect, repeat or alternative model.
4. Record activity types/audio offsets, complete synthetic transcription,
   response text, first response relative to the END marker, byte equality and
   normal settlement. The expected semantic answer is five apples. A response
   before the END marker or incomplete source recognition fails the diagnostic.

This activity mode and the different automatic/manual end signals are documented:
https://ai.google.dev/gemini-api/docs/live-api/capabilities#disable-automatic-vad

Estimated API use: one connection, 6.364 seconds of input audio, approximately
300–400 setup text tokens, at most 128 output tokens, and no tools or grounding.
At the published Gemini 3.8 Live rates inspected on 2026-10-17 ($0.005/input audio
minute, $12/million output audio tokens, $0.75/million input text tokens), the rough
supplier estimate is about $0.002–$0.003, excluding tax/rounding and any additional
billed transcription tokens. Actual usage/billing determines the invoice. The
application still uses its unchanged $0.25 conservative Call reservation; the
supplier estimate is not an application-credit promise or a proposed price change.
https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-live

No paid request has been made or newly authorized by this proposal. Usability,
relevant multi-turn context and physical Android audio remain unresolved.
