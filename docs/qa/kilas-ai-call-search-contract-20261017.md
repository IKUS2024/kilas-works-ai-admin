# Call search response contract correction

## Captured news-case replay correction (later October 17 follow-up)

The one approved `call-search-news-20261017-0943` provider case finished with
HTTP 200 after 11,116ms but `search_not_completed`. It used one Google
connection and one OpenAI request. The call lasted 30,594ms, produced a spoken
failure, ended in 64ms and settled both reservations. No additional paid
attempt was made for this correction.

The captured response now establishes the exact shape: outer status completed,
no error/incomplete details, echoed cap 1, one completed search, one later
`searching` item, and one completed assistant `final_answer`. The later item's
three normalized source URLs all occur among the first search's 34 sources.
Every final citation also belongs to that completed search. The former guard
rejected both its `searching` status and its nonempty source list.

The Call-only normalizer now admits this narrow additional shape: exactly one
later `searching` search attempt, nonempty valid source URLs wholly contained
in the completed search, and all existing outer/final completion, ordering,
unique-ID, cap, error and final-citation provenance requirements. It retains
the earlier source-free `incomplete` exception. Failed/running/unknown items,
novel sources, absent sources, incomplete final answers and uncapped envelopes
remain rejected. The SDK's processed-call cap supports interpreting a later
attempt as ignored, but does not itself label `searching` as an ignored state;
the exception therefore requires the additional observed evidence.

The public-response fixture is stored at
`client-hub/tests/fixtures/ai_call_synthetic/news-cap-searching-20261017.json`.
Only provider item IDs were replaced with stable aliases. It is a historical
response to synthetic public audio, not an assertion that its news claims have
been independently verified.

Offline replay through the actual adapter now returns one completed search,
the identical 2,285-character answer, three citations and unchanged usage:
13,454 input tokens, 594 output tokens, including 5,028 cached input tokens.
Without the Call normalizer, that same fixture still rejects. **62 focused
search tests passed** in 0.556s, including novel/missing/invalid source,
completion/cap/error/order and unsupported-status mutations. All HTTP calls
were mocked. This proves parser replay only; no successful real-provider
spoken search answer has been verified after this correction.

The remaining sections document the earlier correction and its evidence.

No paid provider request was made for this correction. The smoke diagnostic
remains off, its expiry empty, and the already-consumed run ID is unchanged.

## Recorded evidence and its limits

The approved 05:14 UTC session on `d17d452` completed one HTTP request in 9,263ms,
HTTP 200, with one completed search item. The adapter returned
`search_not_completed`. Gemini then emitted 5,280ms of audio and a completed
truthful failure turn. Call duration was 22,692ms and End took 108ms. Both
reservations settled. The captured synthetic-only report remains at
`/workspace/scratch/kilas-ai-call-search-recovery/provider-retest-20261017.json`.

With the deployed parser, that combination identifies its guard against any
non-completed search item. The other item's exact status, overall envelope,
message/citation contents and echoed cap were not recorded. Its status must
not be retroactively called `incomplete`, `failed`, or any other specific value.
The old response cannot be replayed from the available record.

## Provider contract and narrow correction

The official OpenAI SDK documents `max_tool_calls` as a cap on **processed**
built-in calls; further model attempts can be ignored. The web-search output
schema separately includes `incomplete` among possible item statuses. A blanket
test requiring every attempted item to be completed conflates processed searches
with later attempts beyond that cap. These facts do not establish which status
occurred in the old unrecorded envelope.

Call now supplies a server-owned normalizer to the existing adapter. The optional
hook defaults to None, so other callers' parsing and requests are unchanged.
It filters only later `incomplete` attempts in this narrow envelope:

- Overall status explicitly completed; no error or incomplete-details marker;
  echoed `max_tool_calls` is the integer 1.
- Unique item IDs, exactly one completed search with actual source URLs, and
  exactly one completed assistant final answer after the ignored attempts.
- Every ignored item is explicitly `incomplete`, after the completed search and
  before the final answer, has no sources/results, and contains only ordinary
  web-search item fields. Failed, searching, running, missing or unknown states
  cannot use this exception.
- Every final URL citation belongs to that completed search's actual sources.
  Incomplete reasoning, pending unrelated tools, incomplete/empty/nonfinal
  messages and ambiguous ordering cannot use the exception.

The normalizer returns a copy that retains final text, completed sources and
all original usage; it never changes the original response. The ordinary adapter
then applies its existing citation/URL checks and dated-currency validation.
No source, freshness or final-answer completeness check is bypassed. No tool cap,
model token cap, timeout, prompt, quota or pricing change is included.

The default-off QA observer can now record bounded enum/count-only envelope
metadata and ordering on a separately approved future attempt. It records no
raw response body, IDs, query, URLs, credentials or private text and does not
make another request. No additional runtime customer logging or QA arming was
enabled for this correction.

## Regression checks

100 Call tests pass, including 12 new contract tests for the admissible cap
envelope, all unsupported tool statuses, unknown historical status, incomplete
overall responses/final messages/reasoning, missing cap evidence, missing or
foreign citations, invalid source URLs, duplicate IDs, incorrect ordering,
extra completed searches in the mixed envelope, ordinary complete responses,
no-search responses, unchanged usage, secret-safe metadata and the existing
fresh/stale currency gates. All HTTP transport is mocked; zero provider calls.

The 18 existing chat auto-search tests pass. The broader legacy tools suite has
six passes and seven route-authentication fixture failures (401). Running that
suite with the unmodified `d17d452` tools module reproduces the same seven
failures; no unrelated authentication/image behavior was changed to address them.

## Cost clarification from existing records only

| Record | Meaning |
| --- | --- |
| $0.25 AI_CALL reservation | Kilas's existing conservative envelope per Call funding period; not a supplier quote |
| $0.25 COMPLETE app estimate and 250,000 charge_micro | Existing post-dispatch app metering retains the envelope; it is not recalculated from the 22.692s run or Gemini tokens |
| $0.12 WEB_SEARCH forecast | Existing admission reservation, replaced at settlement by the configured token/tool estimate |
| $0.011598 FAILED search estimate | Configured estimate using 13,455 input tokens, 504 output tokens and one search: $0.0013455 + $0.000252 + $0.01, rounded; not an invoice |
| $0.06 approved supplier allowance | Separate planning allowance for the one bounded real-provider test; not the app reservation value |

Gemini reported 2,832 prompt, 159 response, 2,991 total, and a separate 170
thoughts counter. The saved report has no modality split or supplier dollar
charge; adding those counters or applying one price to all of them would not
establish a correct bill. The supplier invoice is unavailable. The $0.25 app
entry is therefore not evidence that Gemini charged $0.25 or that the supplier
allowance was exceeded. Exact combined supplier cost, including proof of the
$0.06 ceiling, cannot be established from these records. No billing/metering
record, allowance, balance, account plan or price map was changed.

## Remaining verification gap

This corrects a documented valid response shape offline. It does not prove that
the unrecorded live envelope had that shape, that its message contained current
cited evidence, or that the new revision delivers a relevant sourced spoken news
answer. If the old other item was failed/running or lacked the new evidence
requirements, rejection remains intentional. End-to-end success would require a
separately approved bounded provider validation with envelope metadata and
read-only verification of returned source publication dates. No paid test is
performed here. Android input/playback, Indonesian multi-turn discussion and
live FX remain unverified.

Primary contract sources checked 2026-10-17:
[OpenAI request parameters](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_create_params.py),
[OpenAI web-search item schema](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_function_web_search.py).
