# demo_batch_runner.py — read-only source review

Complete Library text reviewed:9891 bytes,161 lines, no pagination remaining.
Only text was read. No ZIP retry, materialization, imported collector code,
SDK/NTP request, orders or runtime activation. This review adds documentation
only; existing local code patches are preserved.

## Verified output and interface facts

- `collect_attached(sdk, reader, transport, c, session_id, profile)` calls
  `reader.market_snapshot()` and requires READ_ONLY_MARKET_UNQUALIFIED.
  Each market includes `tick`, `specs`, `sample`, `candles`; full field/type
  contracts are defined elsewhere and cannot be inferred from this runner.
- The used sample keys are exactly acquired_start_utc, acquired_end_utc,
  acquired_start_mono_ns and acquired_end_mono_ns. The runner passes raw
  `candles[].time` into `DemoBatchSource.observe_batch` with a diagnostic
  cycle's batch. It does not itself normalize bar times or prove closure.
- At the second acquisition, it rechecks DEMO session, compares every captured
  specs value against a fresh SDK symbol_info result, collects risk evidence,
  checks session/quote raw_time_msc binding, then collects an uncorrelated
  one-hour history. These are code checks; their successful operation is not
  independently established by reviewing source.
- `collect_diagnostic` produces `collection`, including cycles. The report
  envelope also includes markets, risk_evidence, history, raw_attempts,
  ntp_datagrams_sent, clock_results and input_kind DEMO_OBSERVATION.
- READ_ONLY_DEMO_DIAGNOSTIC_CAPTURED requires two clock results and the last
  status READ_ONLY_VALIDATED_FIXTURE. The source comment explicitly calls this
  historical diagnostic replay with no live lease. All runtime/broker/AI/paper
  flags are false; producer_acceptance remains NOT_IMPLEMENTED.
- The profile is a temporary candidate +10800-second offset, not permanent
  broker/DST proof. Profile construction does not independently verify its
  economics, clock semantics or broker mapping. Account class is explicitly
  NOT_INDEPENDENTLY_VERIFIED. History completeness and costs/drawdown assessment
  are not claimed.
- `main` writes report.json/report.sha256, adds finished_utc, shutdown outcome
  and source hashes, and prints only a small status envelope. No standalone
  schema_version=1/kind=DEMO/source_symbol=GOLD market-only exporter is visible
  in this source. The imported risk module's implementation is not reviewed.

## Match to the existing app boundary

The app's `producer.OfflineMarketProducer` accepts only the existing8192-byte
market-only v1 bytes contract through a server-owned `reader(user)`. This
runner's full report is incompatible and must stay rejected by that boundary.
It also has account/history/transport diagnostics that must not be submitted
to this service. Reading a report through the separate browser-local diagnostic
view does not produce an accepted runtime snapshot.

The desired analyst interface is still `snapshot(user)` with connected DEMO,
canonical XAUUSD, explicit UTC capture/quote, integer USD cents per ounce and
12–48 UTC-close candles. Neither those transformations nor trusted source
registration are implemented by the runner. `analysis.market_source=None`
remains correct. Do not wire its historical report directly into the analyst
or infer GOLD mapping, economic units, bar closure or the +3h adjustment.

## Smallest next source reads

1. **read_only_mt5_measured.py**: defines ReadOnlyMT5, verify_session and
   market_snapshot; needed for actual quote/spec/candle field types, raw time
   semantics, sample timing and privacy extraction boundary.
2. **source_batch_diagnostic.py**: defines DemoBatchSource, connect and
   observe_batch; needed to determine its actual returned projection, clock
   decisions and distinction between replay validation and current lease.

After those two, follow their actual imports rather than inventing schema.
The runner also directly imports **clock_batch_offline.py** (policy/profile,
Decimal/APIS/UTC helpers) and **collector_diagnostic.py** (collection/cycle
contract). These are the next required policy/clock sources if the two primary
files delegate acceptance to them. **demo_risk_evidence_20261007.py** is needed
before assessing its account calculations or risk-evidence economics; it is
not needed to start mapping a sanitized market-only candidate. No raw report,
account IDs, credentials, balance or history is needed for these source reads.

## What remains evidence rather than code

Source review cannot verify DEMO tenant binding, broker unit/contract and lot
grid declarations, GOLD→XAUUSD mapping, broker epoch/DST semantics, operational
clock assurance, fresh current quote or closed candles. These remain missing
independent facts; the October9 capture is historical. GOLD minimum0.01 at
aboutUSD4188 still exceeds the unchangedUSD2000 cap. No source adapter makes
that order eligible. No further stub or parser changes were made in this review.

## Follow-up: the two primary sources are now reviewed

Complete Library text was subsequently read for read_only_mt5_measured(1).py
(220 lines/16356 bytes) and source_batch_diagnostic.py (52 lines/4394 bytes).
The filename suffix is the actual attachment name, not a renamed source pin.
No original Windows byte hashes were verified or modified.

ReadOnlyMT5.market_snapshot emits string bid/ask and OHLC, raw integer tick
time/time_msc, sample wall/monotonic bounds,12–13 selected M1 bar candidates and
specs. Contract/lot/point/tick values are decimal strings, stop/freeze levels
integers, profit/margin currencies USD. Those currencies alone do not declare
price or contract units. Source asserts canonical_symbol XAUUSD but marks raw
time UNQUALIFIED, candle open-time semantics candidate/not verified and
clock_evidence None. That canonical string is not independent mapping proof.

DemoBatchSource delegates qualification and normalization to clock_batch_offline
and its exported policy; it changes a corrected copy to TEST_FIXTURE and returns
policy_replay_only=true, runtime/broker false and producer NOT_IMPLEMENTED.
The collector's internal freshness arithmetic does not grant current runtime
acceptance. clock_batch_offline.py is the concrete next dependency to inspect,
followed by the policy module it actually imports. This module is unnecessary
for the implemented raw observation projection; it is essential before any
attempt to reuse its clock/profile normalization.

The source-grounded projection and server-owned from_collector reader seam are
now implemented in producer.py, with tests and details in
KILAS_TRADING_PRODUCER_BOUNDARY_20261010.md. They preserve raw times, discard
private/diagnostic fields and remain BLOCKED. Final source-grounded phase:
13 boundary/mapping +74 existing regressions =87 PASS, diff-check PASS. No
collector imports/SDK calls, endpoint/source activation or parser polish.

## Final policy verification

The previously requested policy sources were supplied by parent. The complete
validate_trace.py reconstruction matches24276 bytes and original SHA256 pin;
49 original offline clock/source/collector tests and5 app bridge tests pass.
No remaining source-transfer blocker for these suites. Current evidence and
remaining real-runtime gates are documented in
KILAS_TRADING_CLOCK_POLICY_VERIFICATION_20261010.md. Production source remains
None; verified replay semantics cannot authorize a live producer or GOLD order.
