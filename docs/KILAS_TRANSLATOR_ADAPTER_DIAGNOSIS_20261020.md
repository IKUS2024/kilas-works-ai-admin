# Translator adapter diagnosis, 2026-10-20

Follow-up to the read-fence release `79470ed2`. No paid provider request was
performed. This release corrects an observability gap; it does not claim a
measured improvement in supplier response time.

## Findings from code, existing logs and read-only accounting

- `translation()` directly calls `_openai` once, with `stream=True`,
  `event_chunk_size=1`, strict JSON schema and a fixed `low` reasoning effort.
  It does not enter the shared Chat fallback/router. There is no retry loop,
  timer sleep, classifier API call or high-effort promotion in this path.
- Requests uses connect/read timeouts `(10, 90)`. Those are timeout limits,
  not deliberate waits. Its normal one-shot HTTP adapter has no configured
  paid-request retry. JSON validation happens only after the finish event;
  output is intentionally complete before speech generation, preserving the
  full utterance, corrections and ambiguity checks.
- One-byte input already avoids Requests' default 512-byte fill. Actual
  Requests/urllib3 local pipe tests demonstrate that the first complete SSE
  frame arrives before a delayed tail, with multibyte Chinese/Arabic text
  intact. Instrumentation does not change that behavior.
- The adapter previously hid initial role-only SSE frames. The existing
  translation first-event metric therefore began with the first normalized
  content/usage/finish event, not necessarily the first network SSE frame.
  There were no HTTP-header, raw-frame or reasoning-token measurements.
- Four accounting rows matching the existing 07:48–07:51 turns show 349–393
  input tokens and 33–186 completion tokens. This rules out an oversized
  prompt for these samples. Completion tokens do not identify the reasoning
  portion; neither accounting nor old logs can attribute the 2.02–16.95-second
  first-output wait to reasoning, supplier queue, connection/network or parser.
  There is no post-08:13:43 latency sample as of this investigation.

Official model reference checked on 2026-10-20:
<https://developers.openai.com/api/docs/models/gpt-6-luna> documents both `low`
and `none`, and standard input/output rates $0.10/$0.50 per million tokens.
Support for `none` alone does not prove faithful translation parity. Production
reasoning, model, output budget, prompt and request schema remain unchanged.

## Instrumentation correction

Translator alone opts into numeric adapter timings. Shared Chat callers retain
the same request, event sequence and diagnostic-clock behavior. New fields in
the existing sanitized latency log:

- `translation_http_headers_ms`: dispatch to returned HTTP headers, including
  connection/network and supplier wait; not isolated inference duration.
- `translation_first_sse_line_ms`: dispatch to first decoded line, which may be
  a comment/heartbeat and is not literally time to first TCP byte.
- `translation_first_sse_event_ms`: dispatch to first parsed JSON SSE frame,
  including role-only frames formerly invisible to translation().
- `translation_first_content_ms`: dispatch to first nonempty content delta,
  before authority checks. No content is published before the existing check.
- `translation_reasoning_tokens`: nonnegative integer from supplier usage if
  supplied; absent means unknown. It does not alter ledger totals or settlement.

No content, headers, credentials, request identifiers or transcripts are logged.
The adapter's requests, event sequence, usage totals, timeout behavior, stream
cleanup and all per-event authority checks remain unchanged. There is no
configuration, migration or new dependency.

## Offline verification

68 targeted tests passed. These include seven new adapter tests and four actual
Requests/urllib3 pipe tests. The fake clock separates headers at 100 ms, a
role-only frame at 200 ms and content at 2000 ms. This verifies metric semantics,
not real supplier latency. Instrumented/uninstrumented requests and normalized
events compare equal. Other tests cover malformed optional reasoning details,
unchanged usage totals, EOF parsing, malformed SSE closure, timeout without retry, closing the same
response on cancellation, full multibyte text, and the existing realtime,
continuation, early-text, progressive and language contracts. No paid calls.

## Minimal paid benchmark proposal — NOT authorized or executed

If ordinary traffic does not supply observations, request a **single campaign
of at most four text-only calls, ceiling USD 0.10**, with existing credentials
and no plan/key/quota changes. Use the same production runtime/network and the
same Luna model, strict schema, prompt and 3500-token output budget. Compare
`low` versus `none` once for each of two fixed synthetic inputs:

1. Indonesian to English: a short correction preserving a name, negation,
   date, amount and question, e.g. “Nama saya Rina, bukan Budi. Bukan hari
   Jumat; jadwalnya Senin, 26 Oktober 2026. Totalnya Rp125.000. Apakah sudah
   termasuk ongkir?”
2. English to Indonesian: several sentences with a correction, names, dates,
   units and repeated words, checked against an explicit semantic checklist.

Before dispatch, pin the current published model/rates and Standard service
tier, reject any drift, cap serialized prompt/schema at 8192 UTF-8 bytes plus
4096 tokens of conservative framing margin (12000 input tokens total), and
reserve the full campaign ceiling in the existing applicable funding guard.
Four full completions at current Standard rates are bounded by
`4 * (12000*0.10 + 3500*0.50)/1e6 = $0.0118`; even a conservative 2x service
and 10% regional factor is $0.02596, below the proposed $0.10 authorization.
Reject any rate/tier outside the pinned bound. A durable single-use campaign
and four-attempt counter must be enforced before dispatch, with no retry,
fallback or re-arm; unknown spend consumes its full reservation. Do not grant
customer credit or change any quota to make the test run. If the existing
funding/runtime access cannot support this, report that blocker before spending.

Record header/frame/content/finish timings, usage including reasoning tokens,
schema/direction and semantic preservation. Two samples per effort can identify
gross problems but cannot establish a p95 or a realtime guarantee. No STT or
TTS is needed to isolate translation. An audio end-to-end benchmark would
require its own separately reviewed scope/cost; this proposal does not fund it.
Changing production effort to `none` requires acceptable semantic results,
not merely a faster mocked response. No such change is made here.
