# Call search timeout and failure-turn correction

## Evidence and diagnosis

The single approved 04:31 UTC test on `499c674` sent one normal search request
and received `provider_timeout`. It used a Call-only 8s read override, despite
the shared search adapter's 90s default and the existing one-search content
worker's 25s read budget (`agent_workers/content_worker.py`). No HTTP response or
exception subtype returned, so the precise provider/network cause is unknown.
The result does not establish that a larger timeout will make this provider
succeed. It does establish that the Call path had an unusually short allowance
for the same non-streaming web search plus model response.

The missing spoken failure was not a measured production Gemini defect: our
diagnostic explicitly threw `search_failed` on the unavailable function response
and ended the Call **64ms** after sending that response (15,742ms bridge,
15,806ms stop). It prevented observation of subsequent speech. Production's
ordinary search failure path sends the function response without ending Call.
Google's Live tool documentation also shows continuing to receive model audio
after sending a function response; no extra text prompt or TTS call is needed.

Separately, code reproduction found a real production delivery defect: the
20s lookup timer could claim a failure response during session handoff, then
discard it because the lookup deadline was already expired. A worker finishing
while that response waited could also remove its job before provider tool-ID
cancellation arrived. Another deadline race cancelled the timer after a late
result without sending any failure. These can leave a blocking tool turn without
a result, even though the HTTP worker has finished.

## Focused functional correction

- Use the existing one-search worker's **25s read** allowance with the shared
  adapter's unchanged **10s connect** timeout. No shared adapter change, retry,
  extra provider call, token-cap change, or plan/quota change.
- Bound the lookup response at **38s** from the tool call: the existing 3s
  transcript ordering allowance plus 10s connect and 25s read. A timer sends a
  truthful failure if the worker is late; late evidence cannot replace it.
- Separate lookup expiry from reply delivery. Delivery may wait through the
  existing **30s session handoff** bound, polls send-lock admission, and remains
  interruptible by End or provider cancellation. A failed transport closes with
  its normal error instead of silently abandoning a blocked model turn.
- Keep pending replies addressable by tool ID until both worker and delivery
  finish. Recheck the active request before publishing sources after a handoff.
- Both timer and provider timeouts tell Gemini to give one brief spoken failure
  in the person's language, state that current facts remain unverified, then
  wait. No automatic tool retry or invented current answer is authorized.
- Keep PCM/search on separate workers and retain normal usage reservation and
  settlement, including already-dispatched work whose result is discarded.
- Correct the default-off diagnostic to observe a completed model turn after
  **either** a success or a failure response. Record HTTP duration and safe
  connect/read timeout classification. Actual cloud speech is not replaced by
  a mock or by another paid inference.

Requests connect/read timeouts measure connection/inactivity rather than a hard
supplier execution or invoice cap. The timer bounds application response; End
discards late output and preserves ordinary settlement of dispatched work. It
cannot guarantee cancellation of work already running at the supplier.

## Offline verification

**88 Call tests passed** in 1.484s; zero network/provider calls. New focused
coverage includes a virtual 12s provider delay through the actual shared adapter
(past the old 8s budget), real Call PCM queue/dispatch while that provider waits,
source-frame ordering before synthetic output audio, actual adapter ReadTimeout
mapping, an open Call receiving the synthetic spoken failure protocol turn,
expiry during reservation, late evidence, deadline delivery through handoff,
provider cancellation after worker settlement, stale-request source suppression,
End while waiting on the send lock, and bounded delivery failure.

The diagnostic tests reproduce a failed lookup followed by a later synthetic
model audio/text turn and prove it is observed before End. A missing turn stops
after a bounded 30s observation without retry. All test provider/audio responses
are synthetic protocol fixtures, not real Gemini speech validation. The normal
Call audio capture/UI, End control, Translator, Voice Over, Finance, Group,
pricing and Creative Services are unchanged.

## One proposed live retest — NOT RUN OR ARMED

Use the same pinned Chromium-captured synthetic 5.8s English Indonesia-news
question, through the actual backend and automatic VAD. No private audio/history.

| Fence | Proposed allowance |
| --- | --- |
| Durable once ID | `call-search-indonesia-recovery-20261017` |
| Real Google connections / Call reservations | One / one |
| Search HTTP requests / WEB_SEARCH reservations | At most one / one |
| Session deadline | 75s, before normal 80s funding renewal |
| Accepted PCM | At most 40s; then snapshot heartbeat only, below the normal 60s input funding envelope |
| Model output observation | At most 15s audio and two completed turns (short preface plus final) |
| Search deadline | 38s; connect/read 10s/25s |
| Observation after either tool response | Up to 30s, within the 75s session limit |
| Provider token caps | Unchanged Gemini 1,024 / search 2,048 |
| Retry / reconnect / renewal / fallback prompt / separate TTS | None |
| Normal application forecasts | Unchanged $0.25 Call + $0.12 search |
| Supplier planning allowance | $0.06; expected roughly $0.02–$0.04 using existing configured rates, not an invoice or enforceable supplier charge cap |

The 75s limit allows the short question, normal search budget, and a spoken
response without forcing a second Call envelope. A provider handoff or prolonged
stall may still hit a fence and fail; it cannot open another socket/reservation.

Measure the transcription, exact declared tool/arguments, one constant public
query, HTTP duration/status or timeout subtype, completed search count, returned
citations and dates, relevant spoken answer or truthful timeout answer, response
latency, End, and DB settlement. On success, open returned public source URLs
read-only to verify at least one claim/publication date; do not run another
search. A truthful failure turn verifies graceful handling but **does not pass
current-news functionality**. Disarm immediately after the single attempt and
stop paid tests on any failure. FX, Indonesian multi-turn discussion and physical
Android remain outside this single retest's certification.

References: [Google Live tools](https://ai.google.dev/gemini-api/docs/live-api/tools),
[Requests timeout semantics](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts).
