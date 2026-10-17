# AI Call public search intent rejection, 08:59 UTC

## Production evidence

Read-only Render application logs for service `srv-da7ti2psrm7s73dh9i2g`,
filtered to `KILAS_AI_CALL_SEARCH` since 08:44 UTC, returned one event at
`2026-10-17T08:59:15.590928327Z`:

```json
{"activity_end":3,"activity_start":3,"available_replies":0,"cancelled":0,"failures":{"public_request_not_recognized":1},"function_responses_sent":1,"fx_intents_seen":0,"lookup_completed":0,"lookup_started":0,"opt_outs":0,"public_intents_seen":0,"reply_delivery_failed":0,"schema_rejected":0,"tool_calls":1,"transcript_events":3,"unavailable_replies":1}
```

The tool was requested, but the local intent gate rejected it before a provider
lookup started. The unavailable function response was delivered. This event
does not implicate the provider response parser, source checks, HTTP status or
timeout handling. There is no successful sourced lookup in this event.

The screenshot contains the assistant fallback only. The exact user utterance
and transcript fragments are unavailable; no claim is made that any fixture
below reproduces the historical wording. No private prompts, recordings,
provider secrets or transcript content were retrieved or logged.

## Reproduced code defect and correction

Executed the baseline public-intent function directly from commit
`5063aa1a2dd55e53ebc3824c366f00cd7be3156f` and compared it to the patch:

| Synthetic phrase | Baseline | Patch |
| --- | --- | --- |
| Cari informasi terkini tentang Indonesia. | None | general |
| Bagaimana Indonesia sekarang? | None | general |
| Search for information about Indonesia. | None | general |

The existing general gate required a conditions/news keyword even for these
supported current-country or explicit public-information requests. New patterns
bind information/questions directly to Indonesia, require current wording or
an explicit search where applicable, and still return only an allowlisted topic.
Location-only statements, personal-account questions and personal-information
requests do not qualify through the new patterns. Opt-out remains authoritative.

Added fixed-enum `intent_rejections` counters to distinguish no transcript,
unrecognized scope, mismatched scope, active speech, opt-out, a previously used
turn, unsettled text and cancellation. These contain no speech, tool arguments,
URLs or user identifiers. Existing failure codes and function responses remain
compatible. Diagnostic snapshots copy the counters to prevent caller mutation.

No ASR-fragment separator heuristic was added: inserting a separator would
damage valid fragments split inside a word. Tests cover an ordinary multi-event
request with its existing whitespace. The production fragment boundaries remain
unknown.

## Offline verification and limits

Command: `/tmp/kilas-call-venv/bin/python -m unittest discover -s client-hub/tests -p 'test_kilas_ai_call*search*.py'`

Result: **52 tests passed**, 0.501s. All lookup responses are fixtures; tests mock
provider HTTP or the lookup adapter and database/usage operations. No paid
provider call was made. Added tests verify accepted/rejected phrases, fragmented
request dispatch with only server constants, one reservation/settlement and
function response, and privacy-safe rejection reasons without lookup dispatch.
The suite also exercises the unchanged cap/completion/citation contract and
timeout handling through the actual adapter with synthetic HTTP responses.

Parent verification after the edits: **107 Python Call tests passed** in
1.592s and **42 Node tests passed** in 360.883ms, with zero provider calls.

Only Call public-intent parsing, its diagnostic counters and related tests/docs
changed. Captured audio handling, user-speaks-first behavior, one-search cap,
quota/account policy, source verification and timeouts are retained. The
`activity-public-fx-v3-capped-complete` provider contract is unchanged.

Real sourced search and subsequent spoken delivery remain unverified. This
patch fixes demonstrated supported-phrase false negatives; the aggregate
production log alone cannot establish the exact lexical or event-order cause
of the 08:59 request. No commit, push or deploy was performed by this worker.
