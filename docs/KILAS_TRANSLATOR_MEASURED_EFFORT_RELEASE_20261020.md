# Measured short-utterance Translator optimization, 2026-10-20

## Exactly four real calls, completed

Campaign `translator-latency-owner-20261020-v1` completed on Render deployment
`dep-dbbiiu61egvs7385mp8g`, commit `9e2753f6`, using existing credentials in
place. Its persistent row is COMPLETED, attempts=4, reserved_micro=40000,
four complete results. There were no retries, fallback, STT/TTS or fifth call.
The prior authorization ceiling was USD 0.10; the pre-dispatch conservative
four-call ceiling was $0.033424. No customer credit/quota/Finance data changed.

All calls: `gpt-6-luna`, Chat Completions streaming strict JSON, Standard
`service_tier=default`, n=1, unchanged production prompt, 3500 maximum
completion tokens **including reasoning**. Order: ID low, ID none, EN none,
EN low, counterbalancing which effort runs first for each direction.

| Source → target | Effort | HTTP headers ms | TTFT ms | Total ms | Input / completion / reasoning tokens |
| --- | --- | ---: | ---: | ---: | --- |
| id → en | low | 8526.0 | 8743.1 | 11863.6 | 386 / 122 / 52 |
| id → en | none | 1881.1 | 1884.9 | 2277.1 | 386 / 65 / 0 |
| en → id | none | 1457.7 | 1478.4 | 2052.8 | 400 / 91 / 0 |
| en → id | low | 1967.7 | 1979.3 | 2475.8 | 400 / 181 / 85 |

Standard estimated costs, respectively, are $0.0000996, $0.0000711,
$0.0000855 and $0.0001305: **$0.0003867 total**. A conservative estimate
using cache-write input pricing and 2.2x tier/regional margin is **$0.0009372**.
These use actual reported token counts; they are estimates, not a supplier
invoice. Full reservations are retained, not refunded into customer balances.

Raw synthetic outputs and measurements are in
`KILAS_TRANSLATOR_REASONING_BENCHMARK_RESULTS_20261020.json`.

## Quality and diagnosis

Both settings preserved the full semantic checklist on both samples:

- Indonesian: Rina **not Budi**, **not Friday**, Monday 26 October 2026,
  Rp125,000, and a question about whether shipping is included.
- English: **two boxes, not three**, Rina, Monday 26 October 2026,
  125,000 **rupiah, not dollars**, **2.5 kilograms per box**, repeated
  “Wait, wait”, and confirmation of shipping cost **first**. The question
  remained a question; no invented answer or missing final clause.

Manual review found both none translations complete and idiomatic. The ID
none output's trailing space is handled by the existing `strip()` validation.
No model-based grading call was made.

The first parsed SSE frame followed headers by about 1–3 ms, and initial
content followed promptly. Most TTFT elapsed **before HTTP headers**, ruling
out local 512-byte fill or JSON-frame parsing as the dominant delay in these
four calls. This includes connection/network/supplier queue and generation;
it does not isolate any one of them. Low used 52/85 reasoning tokens; none
used zero and was faster in both pairs. The unusually slow first low call is
confounded by first-call/network/queue variation. Two samples per setting
cannot establish a p95, all-language quality parity or end-to-end realtime.

## Focused production change

`translation_profile` selects `none` only for a complete, ordinary id/en
utterance of **at most 250 characters and at least five words**, classified
EASY/NORMAL by the existing local classifier. Other selected languages,
long/very short/complex utterances and clause-context/draft reconciliation
retain low. This is an effort selection boundary, **not an input limit**:
speech is never truncated, rejected or shortened by it. Output budget,
faithful prompt, strict schema, ambiguity checks, per-event End/authority
checks, billing/settlement and no-retry behavior remain unchanged.

The existing v4 model, current voices, all languages, audio pipeline and
Start–Stop/End UI remain unchanged. No global Chat routing/effort changes.
The numeric latency log includes `translation_effort_none` so later production
observations can distinguish which effort actually ran without logging speech.

The temporary startup hook is removed after measurement, and its flag is
cleared on the final deployment. The persistent consumed claim is retained
for audit and permanently denies re-arm/replay. No further paid validation
is authorized or performed. Final production startup/read-only verification
does not claim a physical-device audio run or a measured whole-call latency.

## Regression verification

114 targeted Python tests and three actual Chromium browser tests passed with
mocked suppliers: effort boundaries, full source/output, existing ambiguity
error without retry, metering, per-event authority/cancellation, incremental
reconciliation, complete finish-before-TTS, stream transport, language contracts,
ordinary Chat settings and Start–Stop/End. The separate native PostgreSQL
concurrent four-call guard test also passed before the real campaign.
These are targeted checks, not a claim that the entire legacy suite is green.
Finance revision `4d7f3181` was fetched and preserved before the final push.
