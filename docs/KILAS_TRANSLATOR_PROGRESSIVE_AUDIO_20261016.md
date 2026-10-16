# Translator progressive audio — 2026-10-16

This follow-up removes an avoidable playback delay from the two-way native
release bc09720afac50072648819920f808d7409e19823. The provider remains Gemini
Live, model gemini-3.5-live-translate-preview, using the existing native voice,
two opposite fixed targets and the existing server-held credential. No supplier,
model, billing configuration, subscription or key is changed.

## Cause and change

The preceding pair implementation withheld all received PCM until both provider
receivers had stopped and settlement finished. This made the four-to-six-second
EOS drain part of the first-audible critical path, even when translated audio
was already available. The client also rejected frames before output_closed.

Progressive mode pins the first stream that supplies valid PCM. Its accepted
frames become available immediately through the same append-only cursor. The
other stream stays buffered until the primary receiver has irrevocably stopped,
then continues as the second contiguous run. The client progressively feeds the
ordered raw queue into its bounded player. It still holds playback during local
speech and releases only after 32000 silent PCM16k samples, exactly two seconds.

The tail receive windows remain four to six seconds, within the original
90-second paid lease. No timeout was shortened to make audio appear faster.
Accepted PCM, resets, late primary tails and secondary runs retain their order.
End cancellation, disabled-account checks, one owned logical operation, paired
atomic reservation, aggregate output limits and bounded queue admission remain.

Fresh pages explicitly negotiate gemini-live-two-way-v2 and progressive output.
The server persists a distinct internal session marker; it never upgrades a
cached v1 form or active v1 session. Cached v1 keeps its original closed-output
contract. The marker changes the protocol, not the acoustic voice. Existing
sessions are not force-ended or reset.

## Latency evidence and limits

Two completed production v1 pairs at 07:37 and 07:38 took approximately 10.8s and
11.5s from ledger admission to settlement. They accepted 3.9s and 4.8s of input
and 14.0s and 15.25s of aggregate provider output. These are backend durations
and PCM lengths, not first-audible measurements. Historical single-stream logs
recorded first provider PCM at 2594.1ms and 2786.4ms; these do not establish the
new pair's latency or any client-demo readiness.

A controlled offline clock can demonstrate that primary PCM received before
the endpoint is scheduled at the two-second silence gate while both provider
streams are still open. This establishes removal of the forced application
drain wait. It is not measured microphone, network, provider or speaker latency.
Provider/network delay, polling, player scheduling and drain of the second run
can still delay audible output. Semantic sentence ordering for speech mixing
both languages without a pause and exact final-word completion remain unproven.

New server diagnostics contain only numeric timing/output data and known mode,
target and completion codes. They contain no audio, transcript or credential.

## Internal allowance reconciliation

USD9.60 remaining meant USD0.40 of historical gml reserves was already retained.
Three single-stream operations retained USD0.25 each after durable dispatch:

| Created / finished UTC | Result | Accepted input / provider PCM |
| --- | --- | --- |
| 06:14:57.600 / 06:15:33.387 | COMPLETED | 32.0s / 32.75s |
| 06:15:34.494 / 06:15:37.305 | UNKNOWN, cancelled | 2.2s / 0s |
| 06:16:00.286 / 06:16:39.307 | UNKNOWN, cancelled | 39.2s / 35.5s |

That USD0.75 explains USD9.60 to USD8.85. The zero-output cancellation has a
pre-network dispatch marker but no positive handshake/output proof in the
available logs, so it remains possible paid usage and cannot be treated as an
unused reservation. Two other operations returned actual validated provider
PCM. Historical zero-charge cancellations have no dispatch timestamp.

Four newer paired operations at 07:37–07:38 retained USD0.50 each, adding USD2.00.
At 07:39:48 UTC the historical total was USD3.15 retained, USD6.85 remaining,
with zero RESERVED/DISPATCHED rows, active native sessions or processing turns.
These retained conservative estimates are not supplier invoice amounts. No
history was erased and no dispatched or unknown usage was refunded. The shared
USD10 cap and all prior campaigns remain included. Recheck current metadata
before reporting a final balance because legitimate production use can continue.

## UI and recording verification

The preceding deployed tree 9f1970601adc774e2a51818ee01969e2c20963aa passed nine
nonbrowser DOM/layout checks using actual Flask-rendered English/Indonesian HTML.
They cover the full-viewport call layout, inert/hidden background, End-only
active controls, recovery and cancellation. This is source/DOM verification,
not an Android pixel or real-browser check. The active visual UI is unchanged
by progressive protocol negotiation.

Library resolved the user's new recording as 1000333764.mp4, but one attempt
with the current transfer helper failed with `library file transfer failed:
download failed`. No local video file, frames or audio were available. No
recording-specific conclusions or repeated transfer attempts were made.

Local validation passed all 19 Python suites and all 265 Node tests. Focused
coverage includes 20 paired backend, 17 paired route and 23 paired client tests,
plus fresh v2 DOM rendering. Ruff E9/F and diff checks passed. Independent review
found no remaining concrete blocker. At 07:47:26 UTC the read-only ledger still
showed USD3.15 retained, no unsettled rows and no active native sessions.

Final source, browser-free CI, Render LIVE commit, read-only ledger and runtime
readiness evidence are recorded in the cloud release artifact after release.
No browser tests, new microphone capture or paid automated provider QA are used.
