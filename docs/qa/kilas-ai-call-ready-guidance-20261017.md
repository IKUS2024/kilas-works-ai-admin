# AI Call opening, guidance and interruption

Implemented and independently reviewed with GPT-6.1 Sol, Ultra reasoning, as
requested. No paid provider test, new credential, service-disable flag, quota,
pricing, metering or unrelated product change is included.

## User behavior

Once a new user-started Call has browser microphone/playback readiness and a
checked provider setup, the app requests exactly one opening. Indonesian copy:

> Halo, aku asisten AI dari Kilas. Aku bisa nemenin kamu latihan interview, belajar bahasa, ngebahas pekerjaan, atau ide yang lagi kamu pikirkan. Kamu lagi butuh yang mana?

English, Spanish and Chinese openings follow the existing explicit app language
cookie. Indonesian retains the exact user-provided wording. Subsequent speech
follows the person's actual language or language-practice request.

The voice policy asks for a brief acknowledgement and **one relevant guiding
question** after the first intelligible user answer, using what they actually
said, without forcing a category menu, repeating known details or introducing
Kilas again. The policy also applies when the person speaks before the opening.
Silence/unclear speech and public-search/source/freshness instructions remain
in the same native conversation. No private chat history is imported.

## Readiness and once-only control

- Browser capture gets the first actual worklet frame and a running audio
  context before admission. Input is retained and dispatched in original order.
- A checked `setupComplete` exposes `provider_ready`. The browser flushes its
  buffered first utterance, awaits that upload chain, then sends `/ready` once.
  This task does not block polling, microphone capture, interruption or End.
- `/ready` retains existing CSRF/ownership checks, accepts only allowlisted
  locale metadata plus an actual boolean speech flag, and uses the server's
  existing UI cookie as initial-language authority. It opens no new session and
  reserves no additional usage.
- The opening waits for both readiness fences, drained queued/in-flight input,
  and a nonblocking 500ms provider-activity grace. That grace starts after the
  fences/drain, not during setup/backlog, and resets for a pending provider handoff.
- Known provider user activity/transcription, prior model output, or sustained
  raw startup speech permanently skips the introduction. The raw heuristic is
  >=.004 RMS for >=400ms, solely for suppressing a raced opening; every PCM byte
  still flows. Single-frame quiet noise is not treated as speech. Post-gain
  server PCM is not used to classify startup speech.
- Sent/skipped state belongs to the Call and survives funding/provider resume.
  Duplicate readiness requests, interruption, session renewal, resume and send
  failure cannot replay the opening. Direct default-off diagnostic callers
  that bypass browser readiness do not automatically receive an introduction.
- The greeting send does not hold the Call input/snapshot/End lock during
  socket latency. End/cancellation fences pending readiness and grace work.

## Barge-in and echo

The old engine zeroed microphone PCM while the model spoke and the provider
used `NO_INTERRUPTION`. Call now uses `START_OF_ACTIVITY_INTERRUPTS`, continuous
real AEC-processed microphone PCM during playback, and full queued/scheduled
output cancellation on the provider's interruption/reset. No mic tail is
discarded at model audio start. Old checkpoint callbacks cannot restore old
playback or erase a newer turn.

Browser echo cancellation, noise suppression and AGC remain enabled. During
output and the existing 300ms playback/cancellation decay, microphone PCM stays
at unity gain so the quiet-input boost does not amplify residual speaker echo.
This never gates samples or makes a local RMS event stop playback. Actual room
echo behavior and interruption quality still depend on physical capture/AEC.

Interrupted output tails are discarded but accounted for normally. A canceled
turn's same-envelope or late completion does not erase the new user's speech
or public-search intent. Existing public search contract correction
`activity-public-fx-v3-capped-complete` remains in place.

## Verification actually performed

**125 Python Call tests passed** in 1.803s, including 20 conversation cases,
five readiness/auth/report cases and all existing Call/search/diagnostic/wire
regressions. Full log: `/tmp/kilas-ai-call-final-all-20261017.log`.

**56 frontend Node tests passed**, zero failed/skipped. They cover readiness
ordering/locales/once-only flags, binary PCM, JSON+CSRF HTTP transport, late ACKs,
interruption/reset/End, gain decay, existing player, sources and capture.

The exact production payloads and full connection config (including tools,
resumption and native interruption) validate offline with Google GenAI 2.31.0.
This verifies wire shape; it does not verify provider speech or semantic quality.

Actual local Chromium used synthetic getUserMedia, AudioWorklet, CallCapture,
CallInput, CallSession and CallPlayer, with localhost/injected transport and no
provider IO. It preserved 224,000 expected captured/conditioned bytes of the
first utterance and 320,000 through reset. All five observed speaking-state mic
frames remained voiced. Interruption stopped 10 actual scheduled native audio
nodes, cleared 48,000 scheduled samples and a separate 4,800-sample prefill.
End left zero late mic frames, uploads or scheduled audio. A second case ended
while ready awaited the first upload ACK and sent no late readiness request.
Actual localhost `/ready` used JSON content type, CSRF and the Indonesian speech
flag exactly once. Raw result: `kilas-ai-call-ready-barge-in-browser-20261017.json`.

Raw readiness fixtures retained all input bytes: silence, low room noise
(max RMS .002035) and a 200ms transient (.01768) did not suppress the opening;
the sustained synthetic voiced fixture (max RMS .01150) did. These are local
energy/control tests, not independent semantic ASR verification.

No layout/style, End control, Translator, Voice Over, Finance, Group or other
product behavior was redesigned. Call-only module URLs are cache-busted. A
read-only production check found zero recent active Call operations before
release preparation; the service is deployed through the normal enabled flow.

## Remaining real-audio gap

The exact audible wording, contextually relevant generated follow-up, physical
Android capture/speaker echo, and real provider interruption/resumption have
not been verified on this revision. Native PCM/output control and mocked model
frames are not end-to-end spoken proof. Successful sourced news remains
unverified as documented by the existing search repair; this change does not
claim to close it. Paid diagnostics remain off.

If real-provider validation is approved later, a bounded proposal is one
45-second synthetic Indonesian Call, one socket and normal Call envelope, no
search/retry/reconnect/renewal, unchanged model cap, at most 20s observed output,
and $0.04 supplier planning allowance (not an invoice or hard supplier cap).
Observe the initial opening, interrupt it with a non-sensitive interview goal,
then observe exactly one relevant guiding question before End and settlement.
Physical Android/acoustic validation would still require a real device.

Provider protocol reference:
[Google Live API](https://ai.google.dev/api/live#ActivityHandling).
