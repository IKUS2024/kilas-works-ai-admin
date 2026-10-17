# Single approved public-news Call validation — 2026-10-17

One synthetic public-news case ran at 09:49:32–09:50:03 UTC on main
`a360c3be3e1ea99812acb9dba6e708e0e438210f`. No retry, FX case, or general-topic
paid case followed. The result was **failed search delivery**, not a successful
sourced spoken answer.

| Measurement | Observed |
| --- | --- |
| Duration | 30,594ms |
| Gemini connections / OpenAI HTTP requests | 1 / 1 |
| Input accepted / dispatched | 384,000 / 384,000 bytes; matching hashes |
| Synthetic utterance with inserted 800ms pause | 6.6s |
| Provider activity starts / ends | 1 / 1 |
| First audio during active speech | 0 |
| Search HTTP status / elapsed | 200 / 11,116ms |
| First audio from test start / after provider activity end | 19,836ms / 12,188ms |
| Received speech audio | 10,580ms |
| Source frames | 0 |
| End latency / post-End frames | 64ms / 0 |
| Call / search settled; worker finished | All true |

Recognition captured the core question, “What is the latest news in Indonesia?”
It did not transcribe the fixture's final instruction to search/name a source.
Gemini spoke a truthful inability-to-verify response. The microphone upload
matched the accepted stream, but this does not prove perfect transcription,
physical Android playback, or a 1.5–2s conversational response gap.

## Evidence-backed adapter failure

OpenAI returned outer `completed`, no error/incomplete details, `max_tool_calls=1`,
one completed search, a later `searching` search item with sources, then a
completed assistant answer. The adapter rejected the later item as
`search_not_completed`. Offline inspection found all three later source URLs and
all five final citations normalize to URLs already in the first completed
search's 34 URLs. The response fixture was captured completely (8,499 serialized
bytes), using only approved synthetic public input/output, without credentials,
request headers, private conversation or reasoning text.

## Usage and cost reconciliation

OpenAI reported 13,454 input tokens (5,028 cached), 594 output tokens (75 reasoning
included), 14,048 total. At published $0.10/M uncached input, $0.01/M cached input,
$0.50/M output and one $0.01 search, the usage-based estimate is **$0.01118988**.
The app recorded **$0.011642**, using its input rate without a cache discount,
and settled WEB_SEARCH as FAILED because delivery failed. Failed delivery does
not erase supplier work.

Gemini reported 3,417 prompt tokens, with details for 2,541 text and 454 audio;
291 response tokens, with details for 270 audio; and 191 thoughts tokens.
Modality details do not fully reconcile with totals. At $0.75/M text input,
$3/M audio input, $4.50/M text/thinking output and $12/M audio output, the known
modality subtotal is $0.00650775. Assigning every prompt and response token the
higher modality rate and additionally charging thoughts gives **$0.01460250**.
Combined with the OpenAI estimate that is approximately **$0.026**. This is
conservative arithmetic over reported usage, not an invoice or guaranteed
supplier ceiling; unreported usage and the token-detail discrepancy remain.
Pricing references: [OpenAI](https://developers.openai.com/api/docs/pricing),
[Google](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-live).

The app separately retained its **$0.25 Call reservation/estimate** (usage COMPLETE;
voice operation UNKNOWN with finished timestamp 09:50:02.688952 UTC). It is not
measured supplier cost. No billing or reservation policy was changed.

## Disarm and limits

The run flag was set to `off` and expiry cleared immediately after the result.
Disarm deployment `dep-db9k9p8m7kps73dnbudg` became LIVE at
09:51:27.175260 UTC; startup at 09:51:28 confirmed `paid_qa:false` and
`public_search_live_verified:false`. No further paid attempt is authorized.

The subsequent parser correction must be assessed using offline replay. A
successful provider-spoken sourced response after that correction, physical
Android turn-taking/echo, and broad Indonesian/English multi-turn usability
remain unverified by this single test.
