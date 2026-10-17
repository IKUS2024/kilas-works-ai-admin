# Call search and turn timing follow-up

## Observed production failure

The 09:20:41 UTC session on `3bed990` reported five tool calls: three dispatched
lookups, one completed available reply, two `search_not_completed` failures,
one `scope_mismatch` rejection and one `search_busy` rejection. All five function
responses were delivered. There were two public intents and two FX intents.
The old aggregate log cannot map these outcomes to Indonesia news or SGD/IDR.
An available adapter reply does not establish a correct spoken answer.

The same close record reported 201.6 seconds accepted and sent, 79.95 seconds
of output, twelve turns and one provider interruption. It has no event timeline
or microphone waveform. It cannot establish why speech sounded interrupted.

## Scope and verification limits

The user authorized ordinary public-information searches beyond Indonesia and
FX. Call now has a separate minimized public-topic lookup. Its query uses only
the current turn, with short grounded keywords and sensitive-pattern rejection.
No private history is forwarded. Existing dedicated FX validation, source
checks, completion requirements, one-search cap, accounting and deadlines remain.
Recovery is a concise query before dispatch and a useful, honest next step after
failure; a new paid attempt requires a new user request, not an automatic loop.

Per-attempt diagnostics record bounded kinds, outcomes and response-envelope
enum/count metadata, never raw queries, answers, source URLs or transcripts.
The two incomplete-search envelopes from the old session are unavailable; this
revision does not guess their shape or relax the parser to accept them.

Added separate bounded provider-event timing: first audio while reported speech
is active, or milliseconds after a received activity-end event. Only the last
eight first-audio samples and aggregate counters are retained. These are event
receipt timings, not physical phone speech-end or speaker-onset measurements.
No VAD, PCM, playback, microphone-mute or automatic-opening behavior is changed.
In particular, the existing 1200ms provider silence setting is not proof of the
requested physical 1.5–2s turn gap. Early speech remains unresolved pending
real timing evidence; this diagnostic is not presented as an audio fix.

## Offline validation

After the final privacy changes, **118 Python Call tests passed** in 1.530s.
Parent verification: **42 Node tests passed** in 382.073ms. Zero paid provider
calls were made; actual-adapter tests substitute synthetic HTTP responses.
`git diff --check` passed.

New coverage includes public topics outside the original scope, keyword
grounding in the current turn, opt-out, private identifiers/contact requests,
credentials, URL/instruction rejection, generic-currency bypass prevention,
one dispatch/reservation/settlement per turn, actual-adapter cited success and
incomplete rejection without retry, and the eight-attempt metadata bound.

Keyword grounding and sensitive-pattern checks are conservative safeguards,
not a complete semantic privacy classifier. Ambiguous/unsafe requests ask for
a public-only formulation; translated synonyms or topics omitted from the
current turn are not silently reconstructed from conversation history.

## Proposed bounded paid acceptance — not authorized or run

Three sequential synthetic-only cases: Indonesia news, SGD/IDR, and public
information outside those topics. Each permits one Gemini `gemini-3.8-live`
connection and one OpenAI `gpt-6-luna` Responses web-search request. Maximum
60 seconds per case / 180 seconds total; no retries, reconnects, funding renewal
or additional search. Retain existing max 2048 search output tokens and 1024
Call output tokens. Stop on cap violation or a failure requiring another paid
attempt. Record envelope statuses, sources/dates for synthetic results, output
timing against fixture speech, End latency and settled usage. Include a pause
inside one fixture to measure premature response before its final clause.

Proposed conservative supplier planning allowance: **$0.25 for the suite**.
Existing normal application forecasts are **3 × ($0.25 Call + $0.12 search) =
$1.11**, not the supplier bill. Published Google audio rates checked on October
17 are $0.005/input minute and $0.018/output minute; configured search rates are
$0.10/M input, $0.50/M output plus $0.01/tool call. Text/context charges and
supplier billing are additional; the allowance is not an enforceable invoice
ceiling. Provider work already dispatched may finish after local cancellation.
No plan, balance, credentials or quota is changed by this proposal.

Google pricing reference:
https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-live

Even a passing synthetic provider test would not verify the user's Android
microphone/AEC/speaker acoustics. That physical-device acceptance remains separate.
