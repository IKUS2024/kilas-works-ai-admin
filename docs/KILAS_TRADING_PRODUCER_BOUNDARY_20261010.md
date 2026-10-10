# Market-only producer acceptance boundary — offline skeleton

Base: `810c8419740ec4c2d8de45f145e2d14137078142`, current main. Local only.

## Available interface and implemented seam

`client-hub/kilas_trading/producer.py` adds `OfflineMarketProducer(reader=None)`.
The server-owned reader contract is `reader(user) -> bytes`, specifically the
existing market-only upload v1 contract documented in
`KILAS_TRADING_OBSERVATION_UPLOAD_HANDOFF.md`. This is a new dependency seam
grounded in that repository contract; it is not asserted to be the Windows
collector's API. No default transport, SDK, account lookup, endpoint, storage,
registration or environment switch is added.

Following full text review of ReadOnlyMT5.market_snapshot, the source-grounded
`project_collector_market(market)` and `OfflineMarketProducer.from_collector`
now map an in-process server-owned `reader(user) -> market dict` to those bytes.
The mapping accepts READ_ONLY_MARKET_UNQUALIFIED DEMO results with disabled
execution flags only. It verifies tick/sample binding, bounded capture interval,
12–13 raw aligned M1 candidates and exact selected shapes, then reuses the
unchanged observation contract. Raw tick/candle epochs and acquired_end_utc are
preserved without corrections. Specs, calls, session/server identity, diagnostic
details and arbitrary root additions are never serialized. An asserted
canonical_symbol is not propagated or treated as a reviewed mapping.

`acceptance(user)` reuses `observation.parse_file` (8192-byte bound, exact fields,
duplicate/nonfinite/private-field rejection). It returns only fixed status
fields, candidate validity, candle count and missing evidence categories.
Successful schema validation returns BLOCKED/SOURCE_EVIDENCE_NOT_VERIFIED,
producer_acceptance NOT_IMPLEMENTED. Quote/capture timestamps do not prove
freshness; raw broker times are not offset or reinterpreted. Reader failures
return a fixed error without their potentially private exception content.

`snapshot(user)` implements the analyst's existing method signature and always
raises `analysis.Unavailable`. It never returns a connected analysis snapshot.
All connected/runtime/broker/AI/paper flags are false; policy_replay_only=true.
`analysis.market_source` remains None and this class is not installed anywhere.
Even current-looking UTC capture, valid candles or a within-cap quote cannot
enable a runtime gate. The eventual server reader must enforce tenant binding;
passing `user` to a callable is not authentication proof. No client approval
flags or full diagnostic report are accepted.

## Collector and policy inspection status

Three collector source files were read as complete Library text:
demo_batch_runner.py161 lines/9891 bytes, read_only_mt5_measured(1).py220
lines/16356 bytes and source_batch_diagnostic.py52 lines/4394 bytes. The ZIP
transfer previously failed; parent subsequently supplied the offline modules
as exact source data. validate_trace.py reconstruction now matches its original
24276-byte size and pinned SHA256 exactly. Original clock/source/collector suites
49 PASS and app bridge5 PASS; no module is missing for that verification.
See KILAS_TRADING_CLOCK_POLICY_VERIFICATION_20261010.md for reproduction/evidence.
No source pin was relaxed, SDK called or original policy replica substituted.

The measured reader emits string quote/OHLC, raw tick seconds/milliseconds,
raw M1 open-time candidates, bounded wall/monotonic sample and spec decimals.
USD profit/margin currency does not declare price/contract units. The collector
marks candle semantics OPEN_TIME_CANDIDATE_NOT_VERIFIED, source time UNQUALIFIED
and clock_evidence None. DemoBatchSource corrects a copy as TEST_FIXTURE for
policy replay, with producer NOT_IMPLEMENTED and all runtime gates false.
Reviewed packet/profile/lease code never converts that replay into a live source.

## Minimal missing evidence schema for review

This is a review checklist, not a new accepted JSON contract. Do not turn
unreviewed producer assertions into VERIFIED flags or store arbitrary evidence.
Every reviewed declaration needs provenance, capture/validity dates, scope and
an independent reviewer decision. Avoid account IDs, balances and credentials.

| Evidence category | Minimum explicit facts |
| --- | --- |
| DEMO_SOURCE_BINDING | Server-side proof of authorized tenant/DEMO producer scope and source health; no client-supplied connected=true substitute |
| GOLD_XAUUSD_MAPPING | Source symbol GOLD, target XAUUSD, exact broker contract identity and authorized scope |
| PRICE_AND_CONTRACT_UNITS | Quote currency, price unit, contract unit, contract size per lot; USD_PER_TROY_OUNCE/TROY_OUNCES_PER_LOT only after proof |
| BROKER_LOT_RULES | Exact decimal minimum, step, maximum lot and grid origin, applicable contract/date |
| UTC_CAPTURE_CLOCK | Independently reviewed UTC capture clock uncertainty/validity, not merely receipt time or NTP reply count |
| BROKER_TIME_PROFILE | Raw tick/bar epoch semantics, offset/DST schedule and validity interval, independently reviewed; candidate +3h is insufficient |
| CLOSED_CANDLE_SEMANTICS | Raw bar open/close semantics, timeframe, proof the selected bars are closed and transformation to UTC close time |
| CURRENT_SOURCE_FRESHNESS | Fresh authorized quote/capture and12–48 aligned closed bars for `analysis.validate_snapshot`, within its120-second gate |

Existing historical specs already include contract size, min/step/max and USD
profit currency plus bid/ask. Those figures do not independently declare units,
mapping or clock semantics. Minimum0.01 GOLD at aboutUSD4188 remains above the
unchangedUSD2000 cap, regardless of a future working feed. This boundary does
not evaluate or grant order eligibility, fees, profitability or drawdown.

The current raw market projection is complete. Original qualifier and policy
were reviewed and tested offline; they support the rejecting boundary and do
not justify runtime normalization. A future approved producer acceptance phase
needs the independent evidence above and an authorized reader/transport. Keep
analysis.market_source=None until actual current-source acceptance is proven.
Do not reanchor an original replay monotonic lease in a new runtime process.

## Validation

Fourteen offline boundary/mapping tests pass: missing/error reader, valid observation
blocked, exact user propagation/fresh projection, privacy/verification flag
rejection, malformed/oversized/REAL/report rejection, candle closure uncertainty,
and current-looking capture still unable to arm `snapshot`. A manually injected
skeleton is rejected by the existing analyst before cost reservation or HTTP.
Requests transport is forbidden in these tests. Existing regressions also pass:
analysis17, observation15, Trading38 and host-isolation4 passed in the preceding
source-grounded phase and were not redundantly repeated after a test/document
only change. Current boundary14 PASS plus prior74 regressions PASS. Separate
fake-clock assertions confirm strict integer/range/positive interval behavior
of supplied measured_capture_clock; no sleep or network was used. The original offline clock/source/collector49 and policy-to-app bridge5 now
also pass with exact pinned dependency. These54 new tests are separate from
prior application regressions, and do not establish a connected broker.

No strategy/SL/cap, MOCK, existing observation endpoint, protected products,
credentials, inference, orders, commit, push or deployment changes.
