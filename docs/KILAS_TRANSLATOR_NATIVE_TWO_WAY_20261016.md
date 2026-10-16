# Native Translator automatic pair — 2026-10-16

This records the initial buffered pair release. The later
[progressive audio follow-up](KILAS_TRANSLATOR_PROGRESSIVE_AUDIO_20261016.md)
removes its forced first-playback drain wait while preserving cached v1 sessions.

This work continues the explicit requirement for automatic English–Indonesian
translation in both directions within the same logical session, without a
manual direction switch. Kilas/ElevenLabs voices remain outside active scope.

The preceding fixed-target gate release is verified LIVE at
`f728f76973b07c46466a90db9fabd1bf2fa5f4d2`, Render deployment
`dep-db8su4ui0phs738tegr0`. Its browser-free CI run 38865884149 passed 16 Python
suites, 242 Node tests and PostgreSQL 18. That release alone is still one-way.

## Provider composition and boundaries

The [official Live Translation guide](https://ai.google.dev/gemini-api/docs/live-api/live-translate)
defines one target per connection. With echoTargetLanguage=false, input already
in that target should produce no speech. The [Live API contract](https://ai.google.dev/api/live)
does not allow changing setup on an open connection. A single existing socket
therefore cannot implement the requested automatic pair.

The new composition uses the same model, provider, native acoustic voice and
server-held key in two opposite-target sockets. Each accepted input sample is
broadcast identically to both. One authenticated, owner-bound logical session
and one logical turn own both sockets. There is no language-classifier call,
paid retry, replay, custom voice, new credential or supplier billing change.
Actual provider language suppression and translation quality are not established
by synthetic transport tests.

A fresh explicit two-way consent marker and server session marker distinguish
this mode from cached one-way forms and existing one-way sessions. Existing
active sessions are not converted or force-ended. Ownership, disabled-account
checks, existing quotas, output bounds and owned End remain authoritative.

## Speech, ordering and cost

The client continues capture and processing during speech. The local endpoint
is 32000 silent PCM16k samples: two seconds, measured from input samples with
100ms native frames. It is not a total response-time promise.

Each two-way physical turn ends automatically at this endpoint. Both sockets
drain within their existing four-to-six-second bounded output window and the
original 90-second lease. Output is held until both close, then grouped into
contiguous per-stream runs in first-observed-stream order. This prevents
alternating word-sized PCM chunks from opposite streams. Accepted samples keep
their per-stream order and are retained across pause/resume and renewal.

This introduces extra EOS/drain latency. The continuous translation model does
not promise a final utterance marker. Without a qualified provider marker,
tail_confirmed remains false; semantic final-word completion is not asserted.
If one utterance mixes both languages without a pause, first-observed-stream
order does not establish semantic sentence order. Simultaneous speakers and
rapid code-switching remain limitations.

Both physical leases reserve atomically before either connection can dispatch:
USD0.50 total at the existing USD0.25-per-socket conservative reserve. The shared
USD10 cap includes every historical gml operation. Parent and capacity rows
settle atomically; any possible dispatch retains the entire pair reserve. No
historical rows, campaign policy, quota or balance are reset. Aggregate accepted
output per physical pair and customer audio reservation stay at the existing
90-second bound. Before another pair can reserve, the client checks its total
accepted pending PCM. At 90 seconds of prior backlog it blocks new paid admission
and drains the accepted queue after local quiet; at most one current bounded
90-second pair can remain in addition, keeping the total below 180 seconds.
Player capacity applies backpressure and never silently discards a buffered tail.
With USD1.15 historically retained at 07:16:54 UTC, USD8.85 remains: at most 17
full paired reservations, with the remainder preserved.

The active view remains the orb, concise status and End. Pair selection, consent
and usage disclosure appear before Start. Headsets are recommended. Local echo
matching retains uncertain mixtures; actual Android acoustics are unverified.

## Validation status

Implementation and local validation are complete. All 19 Python suites passed,
including 14 paired-relay, 16 paired-budget and 14 paired-route tests. All 259
Node tests passed, including 17 pair lifecycle/capacity cases and four DOM tests
using actual rendered Flask HTML. Native PostgreSQL 18 concurrency tests include
weighted pair races and a malformed first handshake retaining the full reserve.
Ruff E9/F and diff checks passed. Independent review found no remaining concrete
blocker after cancellation, End publication and held-capacity races were fixed.

These are offline protocol and state-machine results, not proof of real language
recognition, bidirectional speech semantics, device acoustics or audible tails.
Exact final CI, commit, deployment, read-only ledger and runtime readiness evidence
will be recorded in the cloud release artifact after the verified release.
No browser tests, new microphone capture, paid provider QA, secret reads or
production data resets are authorized or used for verification.
