# Approved bounded Translator benchmark, 2026-10-20

Owner approved at most four synthetic text translations, total <= USD 0.10,
comparing low/none reasoning. No STT/TTS, retry/fallback, fifth call or quota/
plan changes. V4 and voices stay unchanged. This implements that one campaign;
it does not change production translation effort.

## Execution and spending boundary

The local environment has no provider/Render API credentials, Render MCP has
no remote-command action, and an SSH `true` probe stopped at an existing system
SSH configuration permission error. No SSH configuration or credentials were
changed. The approved benchmark instead runs on the existing Render service
through a separately flagged startup runner, using credentials in place.

`KILAS_TRANSLATOR_LATENCY_BENCHMARK` must exactly equal
`translator-latency-owner-20261020-v1`, on Render service
`srv-da7ti2psrm7s73dh9i2g`, PostgreSQL, verified Luna, existing key/project and
the existing approved owner identity. It expires at **2026-10-20 10:00 UTC**.
An independent metadata table holds one fixed campaign primary key. Atomic
claim consumes the entire campaign; restarts never resume or re-arm it.
All four USD 0.01 reservations commit before the first provider request.
Each irreversible attempt increments under row lock before dispatch. Crashes,
unknown acknowledgements and errors keep the full reservation. The first
provider error stops remaining calls. There is no public trigger or UI route.
No customer billing, credit, quota, historical data or Finance table changes.

## Pre-dispatch cost proof

- Fixed model `gpt-6-luna`, endpoint `/v1/chat/completions`, Standard
  `service_tier=default`, `n=1`, no tools/audio/images, no redirect, retry zero.
- Entire serialized JSON request <= 8192 UTF-8 bytes. A byte-BPE upper bound
  plus 8192-token protocol margin reserves **16384 input tokens** per request.
- `max_completion_tokens=3500` bounds visible output **and reasoning**.
- Four fixed cases only: short Indonesian low, same Indonesian none, longer
  English none, same English low. This counterbalances order; two per setting
  cannot establish p95, all-language parity or end-to-end realtime latency.
- Official model pricing checked 2026-10-20: input $0.10/M, output $0.50/M,
  cache-write input 1.25x; conservatively count all input at $0.125/M, then
  multiply by 2.2 for extra tier/regional margin despite pinned Standard tier.
- Worst case per request, in micro-USD:
  `ceil((16384*0.125 + 3500*0.50)*2.2) = 8356`.
  Four-call bound **33424 micro-USD = $0.033424**, below the irreversible
  **$0.04 reservation** and authorized **$0.10 cap**. `preflight()` checks all
  four full payloads and the ceiling before claiming or sending anything.
- Missing usage consumes the entire reservation; no fabricated refund or retry.
  Reported Standard cost is an estimate, not a supplier invoice. Conservative
  cost includes the additional margins above.

References:
<https://developers.openai.com/api/docs/models/gpt-6-luna>
<https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create>
The API reference explicitly includes reasoning in `max_completion_tokens`.

## Prompt, output and verification

The unchanged production prompt was extracted to a pure `translation_system`
helper used by both paths. Exact equality against the previous HEAD prompt was
verified for id/en and en/id. Production requests, effort and output budget
remain unchanged. Synthetic samples include names, negation, a corrected day,
date, rupiah amount, quantities, units, repetitions and questions. Actual output
must be reviewed for these facts, natural speech and language direction before
considering an optimization. A faster answer with semantic loss is unacceptable.

The runner records numeric HTTP/SSE/TTFT/total timing, model/tier/effort, usage
including reasoning when supplied, estimated costs and synthetic output in its
own metadata row and bounded tagged logs. No credentials or private speech.
Requests must finish completely with valid schema, usage and matching model.

80 offline tests passed (12 benchmark contracts plus 68 existing Translator
contracts). A separate actual local PostgreSQL test raced eight workers then
two later restarts: exactly four mocked requests, 40000 micro-USD reserved,
four results and terminal COMPLETED; no later request. Local transport tests
verify one POST, no redirects/retry, timeout/error closure and complete usage.
These tests made **zero paid calls**. They establish guards, not API latency.

Finance commit `d5df8c65` was fetched and fast-forwarded before implementation.
The benchmark patch does not edit any Finance file. The flag must be cleared
after measurement; the durable consumed claim remains permanently non-reusable.
