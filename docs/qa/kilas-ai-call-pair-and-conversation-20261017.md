# Call currency interpretation and conversation policy — 2026-10-17

The user reported another failed FX answer and an off-topic language-choice
response after commit `210497efe63c3982cedda2f821aed46e0740ee49` was LIVE.
This repair uses GPT-6.1 Sol Ultra, read-only runtime evidence and offline tests.
No new paid QA, private transcript capture, or production data mutation occurs.

## Latest runtime evidence

The session ending **10:19:07 UTC** ran on production instance
`srv-da7ti2psrm7s73dh9i2g-g9k2k`, the instance started for commit `210497e`.
It recorded five speech activities/transcript events and five completed replies:

- One Indonesia search was `available`, with a completed response, one completed
  search, a redundant later search item, and a completed final answer. The
  previous bounded cap normalizer admitted that captured envelope.
- One FX tool request was rejected **before dispatch** with
  `public_request_not_recognized` / `scope_mismatch`. The parser recognized a
  currency pair, but it differed from the model's proposed base/quote arguments.
  No FX provider search occurred. No source-date, network, or handoff failure
  was recorded for that FX request.
- Accepted/dispatched audio both totalled 114,800ms; provider audio 54,610ms;
  five turns, zero interruptions. This does not establish transcription
  accuracy, physical playback, or response relevance.

The exact utterance and currency pair were not retained in the existing
content-free logs. The screenshot alone does not establish which parser case
occurred, or why the model asked about changing language. The earlier
`rate_time_missing` session is a different failure stage. It supplies no basis
to relax source-date validation for this latest failure.

## Reproduction and correction

An offline harness reproduces the exact pre-dispatch failure signature using
synthetic speech `Berapa rupiah untuk 100 dolar?` and correct tool arguments
USD→IDR: the old parser returns IDR→USD, then rejects with `scope_mismatch`,
without a reservation or provider dispatch. The existing special case reverses
only `untuk satu/1`, missing larger explicit amounts. Equivalent English forms
and mixed named currencies (`dollar Singapura/Australia/Hong Kong`) reveal
additional Call-only pair interpretation gaps. These are proven defects matching
the runtime stage; the actual user's wording remains unknown.

Call setup and checkpoint resumption both use `ai_call.setup()`, not the
Translator's target-language setup. They contain no `translationConfig`, target
language setting or client-content transcript injection. A two-turn synthetic
session and checkpoint handoff test verify that isolation. There is no evidence
of Translator state leaking into Call.

The conversation instructions now retain the established language unless the
person explicitly requests a change; mere foreign words, topic/language names
or quotations do not authorize a language menu. They ask for practical options,
tradeoffs and a next step using prior constraints, one focused clarification
only when needed, and continued help after a lookup failure. The former wording
that called every resumed setup a “new conversation” was removed. This addresses
an instruction gap/conflict; it does not prove the screenshot's unknown input
caused that behavior, or that a live model will now answer semantically well.

The Call-only correction handles quote-first explicit amounts and supported
regional dollar names, preserves strict pair comparison and one-unit outbound
queries, and asks one short direction clarification when a mismatch remains.
Bounded diagnostics retain only the last eight requested/recognized ISO pairs;
no raw utterance, arbitrary tool arguments, amount or customer identifier is
logged.

## Additional text-chat failure

The user explicitly added normal AI Chat search to scope. The screenshot shows
a prior SGD/IDR result followed by a failed repeat query. Read-only usage
records show completed WEB_SEARCH operations at 10:21:27, 10:21:44 and 10:22:10,
then a failed operation at 10:22:28. The application log at **10:22:33 UTC**
records **`KILAS_SEARCH_FAILURE code=rate_invalid`**. This differs from the Call
pair mismatch and from an unfinished-search envelope. It reached rate-number
validation after JSON/pair parsing; the actual failed value is not retained.
The displayed prior rate is not independently verified here.

The shared parser rejects unambiguous grouped decimal strings `14,107.80` and
`14.107,80`. The proposed narrow correction canonicalizes only complete
both-separator formats with valid three-digit grouping and bounded fraction
precision, then runs the existing positivity, magnitude, source-date and
citation checks. Canonical decimal strings keep their meaning; ambiguous
single-comma values, malformed grouping, currency units and nonfinite/negative
values remain rejected. A specific rate-invalid Chat error distinguishes that
limitation from an outage. No cache, automatic retry, normalizer expansion or
source/date relaxation is introduced. This is a reproduced numeric validation
defect; the unknown real response may have failed for another invalid value.

## Offline verification

- **145 Call tests passed in 1.607s**, including 55 public-search tests, three
  conversation setup/wire tests, repeated-search state, source contracts and
  existing audio protocol coverage.
- **23 Chat/search tests passed in 0.553s**: 18 existing auto-search tests plus
  five new rate-evidence tests. Full adapter tests verify one request, exact
  normalized arithmetic, usage preservation, and rejection of altered pair,
  missing/stale/future dates and unmatched/missing source URLs.
- Independent GPT-6.1 Sol Ultra review approved the coordinated patch before
  commit and confirmed the numeric boundary and rejection cases. `git diff
  --check` passed.
- Broader `test_kilas_ai_tools` ran 13 checks with seven authentication failures
  (HTTP 401 before the tested tool route). The same seven failures reproduce on
  an untouched archive of prior commit `210497e`; they are not regressions from
  this patch. No authentication or unrelated tool change is included.

Logs: `/workspace/scratch/kilas-ai-pair-conversation/call-tests.log`,
`chat-tests-isolated.log`, `tools-tests.log`, `tools-tests-baseline210.log`.
All provider HTTP/socket, usage and DB activity under the focused tests is
mocked or uses existing disposable test fixtures. No real provider validation
or production data mutation was performed. No date/source validator, paid-work
cap, billing policy, cache/retry policy or audio behavior is weakened.

## Acceptance limit

Offline tests cannot establish relevant real spoken answers or physical Android
conversation quality. The user will run live acceptance. Start a fresh Call,
state a concrete problem and constraints, ask a follow-up without repeating them,
then ask a current-rate question and a new public topic. Mere mention of a
language should not trigger a language menu; an explicit language-change request
should still be followed. If retrieval fails, the reply should explain the
actual limitation and continue helping with the underlying problem.
