# Translator echo and response recovery — 2026-10-16

The owner reported the same functional failure after progressive release
a75d437ac6d2b85b046711ac2edf7cda0307ab16. This follow-up distinguishes observed
production facts, reproduced code defects and remaining real-device uncertainty.

## Production evidence

The 07:57:35 UTC session used the progressive v2 server marker. Its completed
turn first received and published PCM at 4070.9ms from lease admission, before
EOS at 4291.7ms. It accepted 13.75s of provider PCM: 7.0s target id and 6.75s
target en. This was not a cached v1 turn or a remaining primary publication hold.
It does not prove that the device played or the user heard valid translation.

At 07:59, another v2 turn accepted 12.5s PCM and published its first packet at
3983.5ms. A successor in the same logical session failed with
gemini_response_invalid and zero accepted PCM. The original logs cannot identify
the rejected field. Its failure was approximately 1.084s after EOS, before the
four-second minimum drain, so the separately reproduced late-completion race
below is not established as that production event's cause.

The new screenshot was identified as 1000333777.jpg, but one download attempt
failed. There were no readable local bytes, dimensions or inspected pixels. The
previous recording 1000333764.mp4 also remained unreadable. No screenshot or
video-specific interpretation is supported.

## Reproduced echo defect and correction

The deployed echo detector measured full 16k input energy against a 4k averaged
reference. Within-block energy belonging to the echo itself became residual
"new speech." Independent pure-copy probes at 100/500/1000/2500Hz failed, with
no acoustic distortion or mixed speaker.

A production-engine/player trace made the functional effect concrete: only
delayed, scaled playback PCM arrived after the speech endpoint, yet it set
speech.active, held the player and stopped all five scheduled nodes. Accepted
samples were retained, but playback was interrupted without a transport error.
This is a confirmed source defect. Its responsibility for the owner's actual
device incident remains unverified because the recording/pixels are unavailable.

The corrected reference retains scheduled 24k samples. A bounded current window
is reconstructed at the existing AudioContext rate, then passed through the
same weighted 16k capture filter. Candidate delays stay within 600ms. Candidate
probes only accelerate selection; a match must explain every original 16k input
sample, with the existing positive gain/correlation checks and residual RMS
below .003. The .015 voice threshold and 32000-sample/two-second silence gate
are unchanged. Quiet new speech and uncertain mixtures remain input.

Tests include normal context-rate capture paths, fractional delays, high-frequency
playback, mixed new voice, bounded reference retention and the engine's playback
hold behavior. Desktop CPU measurements establish a bounded implementation, not
Android performance. Certain 24k context/fractional-delay combinations remain
uncertain and are retained rather than weakening the mixed-voice floor. This is
not a general acoustic echo-cancellation guarantee; headsets remain recommended.

## Response validation and cancellation

Provider validation previously collapsed many independent failures into the
same public code. New internal reasons are fixed enums for envelope, shape,
language, PCM format and size failures. A provider error may retain only an
integer status in the range 100–599. Supplier messages, details, transcripts,
audio, identifiers and credentials are not added to these diagnostics.

The public gemini_response_invalid code, strict active-response guards and
no-retry behavior remain. This records the reason for a future legitimate
attempt; it does not retroactively identify the 07:59 response.

A separate deterministic race showed that a completed receiver could reject a
late packet before reaching its completed guard. Bounded parsing and the
stream-specific target check now share the same lock after cancellation and
completion checks. Already-completed packets are ignored; active malformed or
wrong-target packets still fail. End and accepted-tail privacy fencing remain.

## Preserved scope and verification

Gemini model/provider/native voice, progressive two-way translation, the full
tail receive window, two-second gate and fullscreen End-only UI are preserved.
Authenticated owner/nonowner access, existing account/quota rules, one owned
operation, shared USD10 cap and all historical charges remain unchanged. No
key, subscription, supplier billing, authorization or production data is reset.

At 08:08:49 UTC the read-only ledger had USD4.90 retained, USD5.10 remaining and
zero unsettled rows. Production use can change this snapshot; final current
metadata is recorded in the cloud evidence artifact. No retained dispatch is
released and these internal estimates are not supplier invoice amounts.

Local verification passed all 20 Python suites, all 273 JavaScript tests and
Ruff E9/F checks. The four DOM tests also use freshly rendered HTML. Independent
review passed 49 focused JavaScript and 49 focused Python tests with no remaining
code blockers. These tests use synthetic PCM and mocked provider transports.

The first cloud CI attempt passed PostgreSQL18 but its completion suite hit the
existing120s deadline. The runner drops stderr on timeout, so its stdout alone
cannot locate the blocked test or establish a startup failure. A fresh local
run passed in2.3s. Completion-only delayed thread-stack diagnostics now write to
stdout while retaining the same deadline and assertions; the final exact CI
result is recorded separately. No production behavior was changed for this.

Exact CI/source/deploy, runtime owner/nonowner readiness and read-only ledger
results are recorded in the release artifact. No browser,
new microphone capture or paid automated provider QA is performed. Functional
real-device playback, semantic quality, first-audible latency and client-demo
readiness remain unverified.
