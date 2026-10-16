# Native Translator utterance release — 2026-10-16

The later same-day automatic-pair implementation is documented in
[the native two-way note](KILAS_TRANSLATOR_NATIVE_TWO_WAY_20261016.md).
This record describes the preceding fixed-target release.

The active requirement uses Gemini's existing native voice. Kilas Male/Female
and ElevenLabs integration were cancelled at 07:06 UTC. Playback now waits for
**32000 silent PCM16k samples (2 seconds)** after speech. This is the local
silence wait, not a promise of two-second total or first-audible latency. Native
capture uses 100ms frames; legacy capture retains 200ms framing.

Processing continues while the user speaks. Accepted translated PCM is held and
resumed from its exact remaining samples, preserving order across new speech,
provider generation resets and physical renewals. The logical session and
microphone remain open; quiet renewal prefers 45 seconds, with the existing 59s
input and 90s paid lease bounds. Standby silence, recognizable pure playback
echo and silence-only carry do not start another paid turn. Voice threshold and
400ms pre-roll remain. The active page has the orb/status and End control;
consent, usage and selected source/target controls appear before Start.

Failure stops network admission immediately. During terminal output pagination,
local voice can still hold playback without any new upload. After failure, a
local silence observer waits at most 10s before draining accepted PCM, or ends
without autoplaying over ongoing speech. Explicit End cancels immediately and
cannot be undone by late callbacks. A new failed preparation cannot inherit a
previous session's speech state.

Echo recognition additionally requires residual RMS below .003 at the original
16k input rate. Correlation alone could incorrectly erase quiet new speech under
loud echo. Uncertain mixtures are retained. This local reference check and the
requested browser echo cancellation do not prove Android acoustic performance;
headsets remain recommended.

Backend end-of-input drain retains a four-second minimum, extends for late PCM
with a 1.5s output-quiet interval, and is capped at six seconds within the original
90s lease. The output-quiet interval is separate from the user's two-second
speech endpoint. Without a qualified provider marker, completion remains
bounded_drain with tail_confirmed=false; semantic final-word completion is not
asserted. Numeric timing/interruption metadata contains no audio or transcripts.

## Automatic two-way status

This release still uses one fixed target per provider connection. Two separate
one-way tests do not establish automatic English–Indonesian translation in one
session. The [official translation guide](https://ai.google.dev/gemini-api/docs/live-api/live-translate)
documents one target and suppression of input already in that target when
echoTargetLanguage=false. The [Live API contract](https://ai.google.dev/api/live)
does not permit changing setup while connected.

A separate implementation is in progress: one owned logical turn broadcasts
identical input to two opposite-target native streams, labels output by stream,
and atomically reserves both physical leases under the unchanged shared USD10
cap including all historical gml operations. This composition has not been
activated or verified with real provider audio. This native gate release is a
partial delivery and must not be described as completed automatic two-way work.

## Validation and production evidence

The feature checkpoint ea3177b9edd74e4c8bfe52e839551e291261ec05 passed dedicated
browser-free CI run 38863621502 before review fixes. Final candidate CI, commit
and deployment evidence are captured in the cloud release artifact after release.
Validation uses offline PCM, deterministic clocks, Flask rendering and native
PostgreSQL concurrency tests. It performs no browser tests, microphone capture,
paid provider inference, credential changes or supplier billing changes.

Read-only production ledger at 07:11:42 UTC: 10 historical native operations,
USD1.15 retained, zero unsettled, USD8.85 remaining under the shared USD10 cap.
No history, balances, campaigns, quotas or active sessions were reset.

Real-device microphone/speaker behavior, translation semantics, exact final
words and first-audible latency remain unverified. Cloud HTTP access to the
production health URL has been blocked by the CONNECT proxy (403); Render
LIVE state and SELECT-only runtime readiness logs provide server-side evidence.
