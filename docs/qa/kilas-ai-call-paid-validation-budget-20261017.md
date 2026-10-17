# Paid validation budget assessment

No paid call was made while preparing this assessment or its offline tests.
The user subsequently authorized exactly one news case with acknowledged cost
uncertainty. FX and general-topic paid cases remain unauthorized.

## Implemented one-case diagnostic fences

The revised, default-off `ai_call_search_smoke.py` uses unique durable run ID
`call-search-news-20261017-0943`. Root handles deployment, arming, execution and
disarming; this worker did not arm or run a provider test.

| Quantity | Fence |
| --- | --- |
| Google connections | One; reconnect rejected |
| OpenAI Responses web-search HTTP dispatches | One; retries rejected |
| Normal reservations | One Call and one WEB_SEARCH; no funding renewal |
| Session duration | 55s from before connection; 60s whole-process alarm |
| Accepted and dispatched PCM | At most 12s / 384,000 bytes, mono PCM16 at 16kHz |
| Setup / search request / tool response | Each serialized JSON at most 8KiB, checked before forwarding |
| Outbound public search query | At most 512 UTF-8 bytes; exact fixed Indonesia-news query |
| Search output | Existing provider `max_output_tokens=2048` |
| Gemini output | Existing `maxOutputTokens=1024` per generation |
| Observed output | Existing 15s audio / two completed turns, checked after receipt |
| Cleanup | At most 4s and no later than process second 59 |

The original 5.8s synthetic capture is hash-verified before inserting 800ms of
silence at 2220ms. Original file remains unchanged. Augmented input is 6.6s /
211,200 bytes, SHA256
`3293ecbeb5c8f731bc6340b8f35113bda2280394762c6145119e57c72cb1de74`.
No new TTS or other paid generation is used. This fixture can reveal a response
before its final clause, but does not certify physical Android acoustics.

Bounded observations include provider turn timing, modality usage counts when
available, HTTP status, completion envelope, and synthetic public response
evidence for parser replay. The replay fixture excludes request input, headers
and reasoning content; at over 32KiB it is explicitly marked truncated rather
than silently producing an apparently complete fixture.

The old harness allowed 75s session, 40s input, a 90s process alarm, and 10s
cleanup. Its 15s/two-turn post-receipt checks were not provider billing ceilings.

## Conditional arithmetic, not a supplier ceiling

For the earlier three-case proposal, assuming each search bills only 128,000
aggregate input tokens and 2,048 output tokens:

- Search: `3 × (128000 × $0.10/M + 2048 × $0.50/M + $0.01) = $0.071472`.
- Audio, assuming 20s input and 15s output per case:
  `3 × (20/60 × $0.005 + 15/60 × $0.018) = $0.018500`.
- Conditional subtotal: **$0.089972**, excluding Gemini text/thinking/context
  processing, cache writes and supplier work beyond locally observed output.

[OpenAI pricing](https://developers.openai.com/api/docs/pricing) lists standard
Luna input/output at $0.10/$0.50 per million tokens, higher long-context rates,
and $0.01 per web-search call plus search-content token charges.
[Google pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.8-live)
lists Gemini audio at $0.005 input/$0.018 output per minute, and text at
$0.75 input/$4.50 output per million tokens, including thinking in output pricing.

The 128k assumption is **not proven**: the
[web-search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
describes a search context window, not aggregate billed input across processing.
Search context size is not an exact token cap. Returned-token budget accepts
only default/unlimited; its default numeric limit is not published there.
Likewise, local byte/duration and received-output limits do not establish a
whole-session bound on Gemini context reprocessing or generated work in flight.
Closing a socket cannot retroactively cancel already dispatched supplier work.

Consequently the prior $0.25 three-case allowance was a planning estimate, not a
proven ceiling. Normal application forecasts/reservations are separate from
supplier billing and cannot establish that ceiling. The practical choice was
to pause if a strict ceiling was required, or authorize a limited diagnostic
with residual billing uncertainty and reconcile returned usage afterward. The
user selected the latter for **one news case only**. No additional attempt is
authorized by a failed result or incomplete usage report.
