# Continuous Call search repair — 2026-10-17

The user reported that search worked initially, then stopped responding to later
requests in the same Call. Work here uses code inspection, read-only production
logs and offline tests only. No provider QA was authorized or run for this repair.
GPT-6.1 Sol Ultra was used as explicitly requested.

## Production evidence before this repair

Render deployment `dep-db9kbou1egvs73fjkom0`, commit
`866a50a4695098fa2556cb01cde0ff8b8787a556`, was LIVE from 09:55:44 UTC.
Both sessions below ran on its new instance `srv-da7ti2psrm7s73dh9i2g-7ksbg`.

- Session ending 10:00:54 UTC: four activity/transcript events; one currency
  lookup rejected as `rate_time_missing`; an Indonesia tool request rejected
  before dispatch as `public_request_not_recognized` / `scope_unrecognized`.
  The FX response envelope was completed, with one completed search and one
  completed assistant message, cap 1, no error/incomplete details.
- Session ending 10:02:24 UTC: three activity/transcript events; one currency
  lookup returned `available` and its function response was sent; two later
  currency tool requests rejected as `public_request_not_recognized` /
  `scope_unrecognized`. There were no `search_busy`, `turn_already_used` or
  result-handoff failures. This supports the user's report of partial success
  followed by intra-session rejection, rather than a network outage.
- That latter session dispatched all 57,800ms of accepted audio, produced
  25,090ms of provider audio, and recorded first-audio gaps of 6,092ms, 3,905ms
  and 3,692ms after detected activity end. No first audio was recorded during
  active speech. These content-free timings do not prove physical playback
  quality, response relevance, or satisfactory conversational latency.

The actual currency pair and utterances cannot be recovered from the existing
content-free diagnostic logs. No private transcript or audio was persisted or
exposed to obtain them. The screenshot's network/source excuse is unsupported
by these logs. `rate_time_missing` identifies a rate-evidence validation stage;
its precise source date content is unavailable, so date validation is retained.

## Reproduction and changes

The baseline fails synthetic regressions for `Nilai tukar SGD/IDR hari ini?`,
explicit same-pair retry wording, generic same-topic retries, and clearing old
FX context after changing topic or entering a private turn. A six-request
news → FX → general → same general → changed general → different FX sequence
already passes in the baseline. This establishes that there is no simple
session-wide one-search cap in that tested flow; no cap is removed.

An independent offline reproduction also found an old tool waiting for a
mismatched scope could bind a later matching user turn and consume its lookup
allowance. That is a separate, reproduced race; the recent production sessions
did not record that race or a stuck-worker `search_busy` failure.

The correction recognizes Indonesian `nilai tukar` wording and retains only the
immediately selected public scope: an ISO pair, an allowlisted Indonesia topic,
or an already validated minimized public query. Explicit same-topic retries can
reuse that scope. New topics replace it; opt-out/private turns and End clear it.
Raw conversation history is never forwarded as a retry query.

Each waiting tool is bound to the user request number captured when received.
It cannot wait for a later matching request and consume that newer turn's
allowance. The one-lookup-per-turn cap, one active worker, deadlines,
reservation/settlement, and duplicate-tool-ID guard remain in place. A cancelled
or timed-out HTTP worker must finish settling before another worker dispatches;
there is no new parallel paid-work or automatic-retry path.

FX evidence failures now give a specific reason to the speech provider (missing
published date, stale date, unvalidated citation, invalid rate or mismatched
pair) and prohibit invented network/source-outage explanations. A new spoken
search request authorizes a new bounded lookup in the same Call.

Source completion/citation/freshness validation, general public-search
minimization, audio capture/playback and the End control are preserved. A
separate synthetic overlap ordering can still lose input if new activity is
artificially inserted before an older model turn completes; that ordering was
not established in these real sessions, which use frontend PCM gating and
provider NO_INTERRUPTION. This repair does not claim to fix Android overlap or
speech latency.

## Offline validation

All **137 focused Python Call tests passed in 1.614s**. The public-search module
has 50 tests, including 13 new regressions. Independent review also passed all
50 public-search tests in 0.539s and found no remaining blocking issue in scope. Coverage includes:

- Six successive requests in one Call: news → FX → general → identical general
  request → changed general request → changed FX pair, with six unique usage
  reservation keys and six settlements.
- Repeated `nilai tukar` follow-ups and explicit same-topic retries, with enum-only
  FX queries and exact previously validated general-topic keywords.
- Failed provider/response/date/quota attempts followed by a successful new
  explicit request; one attempt per request and no automatic retry loop.
- Timeout and tool cancellation, settlement/worker-slot cleanup, then a
  successful next request; End suppresses late output and rejects new dispatch.
- A waiting old tool cannot claim a new matching request; a tool arriving before
  its first transcript can still bind to that request.
- Topic/private/opt-out context clearing; inflation/unemployment rates remain
  ordinary public topics after an FX discussion.
- Selected-tool scope ownership across Indonesia-news → New York weather →
  explicit same-topic retry, plus mixed-topic hints and harmless late transcript
  fragments. A prior inferred scope cannot replace the actual selected scope.
- Specific rate-evidence failure instructions; no unverified rate is forwarded
  as findings. Existing completed-response/citation/date checks remain tested.

All HTTP/provider/usage/DB work was mocked in these tests. This is code-level
regression evidence, not real-provider or physical Android acceptance.
Test log: `/workspace/scratch/kilas-ai-call-continuous/python-tests-final.log`.
`git diff --check` passed. Only Call query/search code, its tests and this QA
note are changed.

## User acceptance

After the deployment, start a new Call and issue these requests in the same
session, waiting for each answer before the next:

1. Ask for current public news about Indonesia.
2. Ask for the current USD-to-IDR rate.
3. Say “Berapa nilai tukarnya sekarang?” then “Coba cari lagi.”
4. Change the pair with “Terus euro ke rupiah?”
5. Ask a new ordinary public topic, then repeat it or ask to search that topic again.
6. End the Call and confirm playback stops.

If evidence is unavailable, the answer should state the specific limitation.
The next explicit request must remain usable. The app must not invent an outage
or silently retry. A fresh deployment and offline tests do not establish real
user acceptance; that remains for the user's own test.
