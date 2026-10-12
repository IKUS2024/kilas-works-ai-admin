# Live Translator latency patch and integration handoff, 2026-10-12

Prepared in an isolated clone of IKUS2024/kilas-works-ai-admin, branch
`codex/live-translator-latency-20261012`, from production/main baseline
`1565016fb928a3299a694302c07a861c6087eee2`. No push or deployment.
No paid provider request or microphone recording was made for this investigation.
The owner's confirmation that Live works is accepted; this work investigates its delay.

## Existing production evidence

Read-only Render ledger queries cover six COMPLETED owner turns from 10:53 to
11:44 UTC, after the PostgreSQL wildcard fix. Both language directions and both
existing Kilas voices appear. Only timestamps, status, durations, language tags
and branded voice names were selected. No source transcript, translation, audio,
provider voice ID, secret, user email or payment data was fetched.
Latest inspected Client Hub deployment `dep-db6c1iajnfac73d7d1eg` was LIVE at
11:14 UTC on the exact baseline above; auto-deploy was off. No service changed.

| Interval | Min | Median | Max | What it actually measures |
| --- | ---: | ---: | ---: | --- |
| Accepted turn to STT dispatch | 2.154 s | 2.575 s | 2.919 s | Local decoding, queue, checks, first provider credit GET, STT reservation/dispatch |
| STT dispatch to STT settlement | 0.575 s | 0.824 s | 1.087 s | STT upload/response plus ledger settlement, not provider computation alone |
| STT settlement to translation reservation | 0.032 s | 0.096 s | 0.174 s | Session/readiness checks and translation admission |
| Translation reservation to audio-job creation | 6.690 s | 7.449 s | 8.209 s | Translation stream, per-event checks, AI settlement, second credit GET and output reservation |
| Audio-job creation to settlement | 1.125 s | 1.561 s | 2.134 s | TTS request/full response, local MP3 duration validation and accounting |
| Accepted turn to settled audio | 10.994 s | 12.769 s | 13.703 s | Sum of the server intervals above; excludes browser upload and first audible output |

Input recordings were 5.4–14.28 seconds including silence; output was
1.52–5.52 seconds. This small sample establishes neither population p95 nor a
provider-only translation time. One separate failed turn had `attempt_limit`;
that cap was respected and was not reset or increased.

Render's scoped app-log search had no existing stage latency summaries. Its
scoped request-log search returned no Live requests, so it cannot supply upload,
polling or playback timings. Existing ledgers have no final-speech timestamp,
browser upload duration, completed-turn timestamp or first-audible timestamp.

The silence gate is configured at 3,000 ms and sampled every 50 ms. That fixed
delay was verified in offline lifecycle tests, not measured on the owner's device.
Adding it to the measured server interval implies roughly 14.0–16.7 seconds
before audio settlement, plus upload and other browser/completion overhead.
This is a structural estimate, not a measured end-to-end latency.
Polling waits 500 ms after each incomplete response (up to approximately another
500 ms plus request time after completion). Playback fetches the entire private
MP3, then awaits `decodeAudioData`, then starts a buffer source. Their actual
durations and the physical first audible sound remain unknown.

## Concrete bottleneck and narrow fix

The largest measured composite interval is translation plus its guards. The
baseline calls `check()` on every streamed delta, usage and finish event.
`sessions.check()` formerly opened a fresh `usage._connect()` connection, selected
and locked the session, selected the turn, committed and closed that connection
for EACH event. `require_ready()` also queries readiness on each event.
The cost attributable to connection churn within production's 6.7–8.2-second
composite interval is not separately recorded.

The patch replaces only the read fence with one parameter-bound LEFT JOIN on the
existing thread-local database connection. Each event still checks the same
owner, ACTIVE session, expiry and PROCESSING turn. No polling/throttling/cached
session state is introduced. The former lock was released before the check
returned; it did not span provider dispatch. Admission, completion and End keep
their original write transactions and locks. No shared DB adapter changed.

PROCESSING status polls now select the existing turn timestamp in the first
owned JOIN, removing their second query while preserving the four-minute timeout
and existing response contract. Reads are committed by the existing DB helper;
no transaction or row lock is held while waiting for a provider stream.

An offline operation-count comparison executes the original Git-baseline
functions and patched functions against a synthetic SQLite account. For 100
checks it observes 100 fresh connections and 200 transaction queries before,
versus 0 fresh write connections and 100 reusable read queries after. Each
PROCESSING poll changes from two queries to one. Local elapsed times were
524.325 ms and 23.676 ms in this single diagnostic run; these are NOT measured
production gains, a provider benchmark or a speed promise.

No new provider, model, reasoning setting, TTS format, language prompt or voice
selection was introduced. Credit checks remain fresh before both STT and TTS;
caching or removing them would weaken the requested billing protections.
Existing dispatch/settlement, output limits, quota/rate limits, no-retry policy,
consent, owner isolation, private media, End and echo prevention remain in place.
Streaming TTS playback was not introduced because current playback requires
validated/settled audio and a private completed result.

## Timing instrumentation

One `KILAS_LIVE_LATENCY` line per processed turn records only `outcome` and
numeric milliseconds. It does not expose content or identifiers to logs or UI,
introduce a telemetry endpoint, persist diagnostics in a table, or change
provider logging/retention settings. Diagnostic stdout failure cannot change
accounting or cancellation. An enqueue failure after slot admission also emits
the completed timing fields; an early ready/busy denial does not.

Fields: `admission_ms`, `decode_ms`, `queue_ms`, `preflight_ms`,
`credit_stt_ms`, `stt_claim_ms`, `stt_ms`, `translation_ms`,
`translation_first_delta_ms`, `translation_fences_ms`, `credit_tts_ms`,
`audio_reserve_ms`, `audio_submit_ms`, `completion_ms`, `backend_ms`.

`translation_first_delta_ms` starts immediately before opening the stream and
ends after its first delta's cancellation check. `translation_fences_ms` is the
cumulative time of translation-stage readiness/session checks. Both are nested
inside `translation_ms`; do not add them to the total. `translation_ms` also
includes AI reservation, parsing, closing and settlement. `audio_submit_ms`
includes existing TTS, MP3 validation and billing. `backend_ms` begins inside
enqueue after ready/slot checks (or at process entry for direct test calls),
and includes final fencing/cleanup. Unlisted fencing can account for the gap
between the sum of top-level stages and total. Missing fields mean that stage
was not reached; they do not mean zero latency.

These new timings are tested offline but have no production samples yet.

## Exact handoff to external Visual Codex

This patch edits no template, stylesheet or frontend module. Visual Codex owns
`client-hub/templates/kilas_translator/live.html`,
`client-hub/static/kilas_live_translator.css`,
`client-hub/static/kilas_live_translator.mjs`, and any coordinated change to
`client-hub/static/kilas_live_translator_engine.mjs`.

1. During the active session, display only the orb/animation and End, plus an
   important failure message when needed. Do not display source transcript,
   translated text, routine status text or technical processing explanations.
   Setup language/voice choices and consent remain before Start; errors such as
   exhausted credit, denied microphone permission and account/session expiry
   remain visible with `role="alert"`.
2. Remove `#live-translation` from `live.html`, the DOM-writing `onResult`
   callback in `kilas_live_translator.mjs`, and the submit handler's unconditional
   `document.querySelector('#live-translation').hidden=true`. All three must
   change together to avoid a null-element error. The backend's owned result
   response and existing retained audio-job script are unchanged by this patch;
   visual hiding is not a data-retention change.
3. Keep `#live-state` as an accessible visually hidden `role="status"`
   `aria-live="polite"` node, with concise Indonesian state announcements.
   Use the project's existing screen-reader-only utility or a scoped utility,
   not the `hidden` attribute or `display:none`, which would suppress announcements.
   Preserve its updates from `onState`. Use the orb's `data-state` for animation;
   avoid duplicate screen-reader announcements if the orb also has a changing
   image label. Give the status a useful stable accessible name and make the
   decorative orb `aria-hidden="true"` if it duplicates the live region.
   Keep End keyboard-focusable, labelled and visible during starting,
   finalizing, processing and playback. Respect reduced motion.
4. Keep state transitions and lifecycle fences: mic tracks release before
   processing/playback; listening resumes only after output ends; End immediately
   aborts local requests, stops audio/mic and rejects late restart; leaving or
   hiding the page ends the session. Keep important recoverable no-speech errors.
5. This integration retains the current 3,000-ms silence threshold, as explicitly
   instructed in the follow-up. The earlier recommendation of 1,500 ms is a
   planning estimate only and must not be applied in this patch. In a separately
   coordinated future change to
   `kilas_live_translator_engine.mjs`, change the `SilenceGate` default
   `silenceMs=3000` to `1500` only after explicit coordination. Update the exact boundary
   tests and mocked browser expectations/cache version together. Do not change
   the RMS threshold or truncate audio samples. Leading silence still never
   dispatches; new voice resets the timer; one utterance finalizes once.
   Pauses >=1.5 seconds can split thoughts, and speech resumed during processing
   is not recorded while echo prevention holds the mic off. Keep 2.0 seconds
   if the owner's natural pauses regularly split sentences; 3.0 seconds is
   gentler for long pauses but adds more fixed wait. The proposed 1.5-second
   reduction is arithmetic, not a measured live speed improvement. This backend
   patch leaves the currently approved three-second setting unchanged.
6. Update browser assertions that currently expect translated text and visible
   state text to assert no visible transcript/translation, a working live region,
   orb state/animation and End. Retain important error, consent, selected voices,
   language-pair, privacy and lifecycle tests. Coordinate any change to
   `client-hub/tests/test_kilas_live_translator.py`: this patch adds tests there,
   and its existing UI assertions still describe the baseline display.

For future measurement integration, collect monotonic local numeric marks for
last voiced sample, finalize, blob callback, POST start/ack, first COMPLETED poll,
audio fetch completion, decode completion and audio-source scheduled start.
Compute silence, capture flush, upload/admission round trip, status visibility,
download/decode and speech-end-to-output-scheduled delays. POST round trip includes
server admission/decoding and cannot isolate uplink alone. Do not export recordings,
transcripts, session URLs or identifiers or show technical timings in the session.
Buffer-source scheduling is a proxy, not proof of physical audibility; distinguish
that from a later owner-observed first sound/hardware output latency. This phase
did not implement browser timing because Visual Codex owns that module.

## Target, validation and remaining gates

Initial acceptance target for short (roughly 2–8-second) utterances on a stable
connection: median <=10 seconds from final voiced sample to first audible output,
with <=12 seconds p95 as a later larger-sample target. Both are engineering goals,
not achieved results or forecasts. Measure stages before choosing another change;
if provider/credit time dominates after connection reuse, this patch alone may
not meet the target. Keep language/voice quality and cancellation acceptance equal
or better. No reduction in those protections is authorized to meet the target.

Offline checks PASS: 21 Live Translator backend tests (16 baseline plus 5 new),
23 dictation/STT tests, 52 shared Audio tests and 24 JavaScript lifecycle tests
(12 Live, 12 recorder). Providers are mocked; local FFmpeg validation is real.
The 100-check baseline operation-count diagnostic passes. Existing Audio tests
emit non-fatal temporary-file ResourceWarnings on Windows; assertions pass.
The joined read's PostgreSQL SELECT shape was exercised read-only against an
existing owned production session, returning its ENDED/completed metadata.

Full native PostgreSQL regression is authored in
`client-hub/tests/test_kilas_audio_postgres.py` but not run: no disposable local
PostgreSQL executable/container is available. Its safety gate requires explicit
loopback PostgreSQL, so production/staging was not substituted. Run the existing
Live Translator QA PostgreSQL job during coordinated integration before release.
This is a remaining validation gate, not a passing native-concurrency claim.
UI browser suites were not rerun for this backend patch; UI remains concurrent
Visual Codex work. Physical microphone, uplink, first audible output, live speed
gain and hardware/browser voice quality were not re-tested in this phase.
Existing production timing records were read; no paid test or repeated failed
request was dispatched, no quota/balance record changed, and no deployment made.

Exact repository files changed:

- `client-hub/kilas_ai/live_translator.py`
- `client-hub/kilas_ai/live_translator_store.py`
- `client-hub/tests/test_kilas_live_translator.py`
- `client-hub/tests/test_kilas_audio_postgres.py`
- `docs/KILAS_LIVE_TRANSLATOR_LATENCY_20261012.md`

The isolated patch can be applied to the coordinated branch after reviewing for
concurrent changes. Do not apply an entire checkout over shared main. Runtime
and read-fence changes are independently reversible; no schema rollback,
provider configuration or data reset is required.

## Offline integration validation follow-up

Fetched upstream main advanced to
`afec593fde8dca7f9e6071404d171c83f4742aef`, with UI commits `1e7558f3`
and `afec593f`. Its changed files include the Live template/stylesheet and shared
UI tests. None of the five files in this patch overlap that upstream diff.
AGENTS.md and the runtime/provider/accounting files inspected are unchanged.
The original local commit `84be4a0430f0ce57d19cbfb9aaf753f244b09181` remains
preserved in the original isolated clone. It cherry-picked without conflict into
a separate task-owned worktree at `integration-validation`, based on `afec593f`.
The final integration patch is exported relative to that newer base; use that
patch instead of the initial export. No shared or external UI checkout was used.

On this newer base, the Live suite now has 26 passing tests: five further
connection/lifecycle cases were added. They exercise known-closed cached
PostgreSQL connection replacement; half-open SELECT recovery that observes End;
bounded one-time connection recovery with no retry of ordinary SQL/data errors;
late completion/End from an old session leaving a newer session intact; and End
at translation completion fencing TTS while completed AI usage stays recorded.
The driver tests run the existing real DB helper with mocked transport and the
installed psycopg2 exception classes; they are not native PostgreSQL tests.
The stale-session case also checks the reusable SQLite connection has no active
transaction after the read. Existing boundary cases cover End during STT,
translation and TTS; no downstream dispatch after cancellation; dispatched cost
retention; empty speech; duplicate turns; owner/expiry fences; four-attempt caps;
credit denial before STT/TTS and finite output allowance under the QA exemption.

Latest offline validation: 26 Live backend + 23 STT/dictation + 52 shared Audio
+ 24 JavaScript lifecycle tests PASS, 125 total. Shared Audio assertions pass on
the newer upstream UI baseline. Five added follow-up tests initially included
an incorrect expected AI ledger enum (`COMPLETED`); it was corrected to the
actual `COMPLETE`, then the full Live suite passed. No runtime behavior was
changed in this follow-up; additional edits are tests and this documentation.

No local PostgreSQL/psql/initdb/pg_ctl, Docker/Podman executable, PostgreSQL
installation under Program Files, or PostgreSQL/Docker service was found.
No software was installed or persistent access changed in this follow-up.
Full disposable-loopback PostgreSQL regression remains unavailable here and
must pass in the existing CI job before deployment. That CI is not triggered by
this local-only task. UI/browser suites still belong to the coordinated Visual
Codex work; silence remains exactly 3 seconds. Live gains and first audible output
remain unmeasured. No push, deploy, provider request or microphone capture.

Copy-paste handoff for Visual Codex:

> Integrate only the supplied `kilas-live-translator-latency-integration.patch`
> into your current UI work. Its base is `afec593f`; it changes only the five
> files listed above, with no UI or provider/configuration changes. First run
> `git apply --check <full-patch-path>`, then `git apply <full-patch-path>` if
> clean. Do not overwrite files or replace your checkout. If you edited
> `test_kilas_live_translator.py`, merge its added runtime tests with your UI
> assertion updates; stop on any conflict and resolve only the overlapping
> hunks. Preserve 3,000-ms silence and your upstream UI changes. Complete the
> orb + End display using the exact DOM/live-region instructions above, keep
> important visible errors, consent/privacy, Kilas Male/Female, billing and
> lifecycle behavior. Run the 26 Live, 23 STT, 52 Audio and 24 JS checks plus
> the existing disposable PostgreSQL CI job before a coordinated release.
> The <=10-second median first-audible goal has not been demonstrated; do not
> claim production gains from the offline operation counts.

## Owner-owned release preparation

The owner subsequently asked this task to handle latency integration and the
remaining PostgreSQL check directly. External Visual Codex retains broad UI
ownership; the earlier handoff instructions above are historical coordination
notes, not a transfer of current release responsibility.

Freshly fetched main is `beba0238cd7e0f9b58a46d99948b8a3030bed9b1`.
It still contains the original per-event write-connection read fence, so the
latency patch was not already integrated. Its changes since `afec593f` do not
overlap the five patch files. The isolated integration branch was rebased onto
that main without conflicts; UI files match upstream exactly. All 125 focused
offline checks were rerun and passed on this newer base. No runtime change was
added beyond the previously reviewed latency patch.

Local disposable PostgreSQL remains unavailable. The existing Live Translator
and Audio QA workflows already provision disposable PostgreSQL 18 services and
execute the native regression with an explicit loopback safety gate. Client Hub
auto-deploy is confirmed off. The authorized normal main update can therefore
start those existing checks without deploying. Native PostgreSQL and complete
required CI results must be confirmed on the exact pushed SHA before any release.
No credential/configuration, provider/model, billing/quota or 3-second silence
change is authorized or included. Production gains remain unmeasured.
