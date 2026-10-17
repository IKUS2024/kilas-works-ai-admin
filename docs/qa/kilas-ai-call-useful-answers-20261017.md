# Useful Call answers and quote-date evidence — 2026-10-17

Single-worker, code/offline-only repair. No paid provider QA or production data
mutation. Original spoken requests and raw failed FX evidence are unavailable.

## Established evidence

The session ending 10:45:23 UTC ran on the LIVE `b186034` instance `8rg5w`.
Two speech activities/transcript events produced five tool requests: four
public-query rejections (`scope_unrecognized`, no dispatch) and one completed
FX search rejected as `rate_time_missing`. No transport/handoff error occurred.
The screenshots show a camera comparison with a blanket verification preamble
and an FX reply demanding publication date/time then asking to try later.

The generic failure instructions explicitly labeled otherwise useful known
context as not currently verified. The FX failure instruction said “published
source date/time,” although the numeric validator already accepts a quote date
alone. Those instruction/outcome mismatches are established. The exact camera
query-rejection cause and whether the FX quote date was missing or malformed
cannot be recovered; no actual source is claimed usable without its evidence.

## Minimal changes

- An ungrounded optional lookup for a clearly stable explanation/comparison can
  hand back an explicit `established_knowledge` outcome instead of a current-fact
  failure. No query, reservation or provider request is sent. Re-formulations in
  that same spoken turn stay on the answer path; a new current-price/search
  request still gets its normal bounded lookup. Privacy, explicit-search,
  current-fact and high-stakes guards remain.
- Lookup policy distinguishes established facts from the specific missing live
  fact. Failure composition leads with supported useful content and retains
  necessary uncertainty about only the unknown, with a relevant next step.
- FX instructions separate quote as-of date/time from article publication and
  retrieval time. Date-only quotes remain valid. The existing single authorized
  search may select another dated cited source among its results; there is no
  extra HTTP/search attempt, cache, stale-rate fallback or fabricated date.
- Missing, malformed and invalid-calendar `as_of` values now carry fixed-enum
  diagnostics through Call/Chat. No source text, URL, rate, transcript or private
  identifier is logged. Invalid calendar dates remain rejected.

## Targeted verification and review

The synthetic camera case first failed because the old response had no
established-knowledge outcome. After correction it makes zero reservations or
provider calls, including a same-turn reformulation; a subsequent explicit
price search succeeds. Fresh session state is separate. These are server/tool
contracts, not proof of a model's spoken semantic quality.

**148 Call tests passed (1.651s); 25 Chat/search tests passed (0.528s).** Existing
successive searches, follow-ups, failure recovery, End, source/pair/numeric
validation and audio regressions remain covered. New timestamp fixtures accept
quote date alone and zoned timestamps, while publication/retrieval timestamps
cannot fill an absent quote date. Missing/format/calendar diagnostics are
checked for content leakage. The final two directly affected camera/session
regressions passed again after the one review's small contract clarification.
`git diff --check` passed. Logs: `/workspace/scratch/kilas-ai-useful-answer/`.

The one local review checked routing boundaries, privacy, no extra dispatch,
late-request fencing, numeric/source/date gates and unchanged metering/audio.
It corrected a price-question exclusion before the final passing checks.

## Remaining acceptance gap

Real Android comprehension, relevance and natural speech remain unverified.
The user performs live acceptance. The historical FX source body is unavailable;
this repair does not assert that its quote actually had a usable date. Necessary
current-rate disclosures remain, and unavailable evidence never becomes a rate.
