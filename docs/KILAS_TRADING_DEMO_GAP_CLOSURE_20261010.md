# Trading DEMO evidence gap closure

Current main base810c8419740ec4c2d8de45f145e2d14137078142. Offline review only;
no connection, orders, cap/strategy edits, inference, commit/push or deployment.
Other Kilas products/modules unchanged. Local patches preserved.

Latest parent-verified October10 capture supersedes the older next-step access
blocker: executor recovered, all10 source hashes match,59 local offline tests
pass, clock8/8 replies, but identical~8h18m-old ticks fail freshness and the
minimum lot still exceedsUSD2000. Overall UNAVAILABLE, shutdown completed,
no retry/orders. See KILAS_TRADING_LATEST_DIAGNOSTIC_READINESS_20261010.md.
Do not repeat the procedure below until parent reviews broker session hours and
separately authorizes any new capture. The procedure is retained as reference.

## Evidence resolved now

The October9 diagnostic report was read completely as Library text (1771
lines, reported68665 bytes), parsed in memory and reduced to selected market,
status/spec and risk arithmetic facts. No account identifiers, balance/equity,
history, credentials or raw NTP packets were persisted. Text compatibility is
not byte/hash authenticity or independent proof of the SDK/broker observations.

| Fact | Code plus historical evidence now established | What is still required |
| --- | --- | --- |
| DEMO read binding | ReadOnlyMT5.__verify requires terminal connected, account trade_mode integer0, USD currency, pinned server and stable internal account/terminal identity; each read has pre/post checks. Both recorded markets declare DEMO and disabled execution. | A new capture with the same checks passing now; source/tenant authorization must be bound server-side. Historical declarations do not prove today's session. Account class remains NOT_INDEPENDENTLY_VERIFIED; do not infer Standard from server. |
| Symbol and numeric contract | The read facade requires returned spec.name GOLD. Both historical specs are identical: trade_contract_size100, volume_min0.01, volume_step0.01, volume_max50, trade_tick_size0.01, point0.01, trade_tick_value1, USD profit/margin currencies. | Independent broker evidence explicitly declaring price currency/unit and contract unit per lot, plus current spec consistency. Gold alias XAUUSD is hardcoded by source, not independently verified mapping. |
| Lot grid/price arithmetic | Minimum/max are exact step multiples; recorded quote values conform to the0.01 tick. Second BUY0.01*100*4188.55=4188.55 and SELL0.01*100*4188.02=4188.02 match reported formula notionals. Both exceed the unchanged2000 cap. | Confirm economic units and current spec/quote. Under this reported formula, the minimum lot would require price<=2000 to fit that cap; at captured prices there is no eligible minimum GOLD order. Account sizing/leverage does not bypass a notional cap. |
| Advancing observations | Two market samples, each12 M1 candidates; tick time_msc advances2348ms. Each positive wall/monotonic acquisition interval passes the reviewed2s/50ms bound on selected facts. | New observations from the same authorized process; an old advancing pair is not a fresh producer lease. |
| Operational clock model | Report says two four-attempt batches, eight successful replies, WAIT then READ_ONLY_VALIDATED_FIXTURE. Reported uncertainty about78.844ms/81.977ms (rounded second82ms). Exact pinned clock/source/collector code was independently tested offline:49 PASS plus5 app bridge PASS. | Fresh same-process bracketed evidence, no reuse/reanchor of old monotonic marks, and reviewed operating assurance. Historical packet qualification itself was not recomputed in this gap review. NTP remains unauthenticated; count/error bounds are not broker timezone proof. |
| Broker epoch/profile | Source explicitly uses a temporary candidate+10800 profile and marks source UNQUALIFIED/CANDIDATE_PROFILE_NOT_BROKER_VERIFIED. The historical clock result is replay only. | Independent server/API epoch and DST/validity-window evidence. A new trace may show behavior in one window, but cannot establish a permanent DST schedule by itself. |
| Candle semantics | Facade selects raw M1 open-time candidates using raw+60<=tick, contiguous rows and lag<60; policy names this FIXTURE_OPEN_TIME_HYPOTHESIS. App preserves raw bar epochs without shifting or claiming closure. | Independent API/broker OPEN/CLOSE semantics, then fresh bounded quote/bars to verify alignment/closure under an approved profile. |

Useful arithmetic/source conclusions are now closed: the code already has
DEMO/stable-session read guards, historical ticks advanced, numeric specs are
present/consistent and the recorded cap failure is reproducible. None needs
another generic parser or synthetic stub. Economic unit/mapping and broker-clock
provenance require independent evidence rather than another inferred flag.

## Minimal next verification procedure

First, parent reviews existing broker/instrument evidence for the exact server
and GOLD contract: USD price unit, contract unit and size per lot, min/step/max
and grid, GOLD↔XAUUSD economic identity, tick/bar epoch semantics and applicable
UTC/DST validity windows. Do not relabel profit currency as price unit or infer
troy ounces solely from100. Parent already has the ZIP; no owner source reupload
is needed. Code/profile approval is separate from proof of those facts.

After that review, one fresh manually initiated read-only verification on the
already configured owner Windows host is sufficient to check *current capture*
behavior. This task does not run it. The existing executable procedure is:

```bat
cd /d "D:\kilas trading"
python demo_batch_runner.py --read-only-demo --once
```

The existing runner checks source pins and exactly one already-open terminal,
attaches once, performs two bounded observations/eight scheduled NTP attempts,
rechecks session around reads/requests and shuts down in finally. It performs
read-only account/history and hypothetical calculator diagnostics as well;
it is not a minimal market-only exporter. Keep its original pins and behavior,
do not enable external trading or add retries/loops. Never submit its full
report.json to the application or model; it contains private diagnostics.

For the narrow market adapter check, parent consumes only an allowlisted market
projection from that new report, locally where the report exists. Choose the
exact fresh report path printed by that invocation, not an old/latest-file glob.
The implemented API is:

```python
from kilas_trading.producer import project_collector_market, OfflineMarketProducer
from kilas_trading.observation import parse_file

# report is read locally in memory; no report upload or raw retention.
market = report['markets'][-1]
market_only_bytes = project_collector_market(market)
observation = parse_file(market_only_bytes)
status = OfflineMarketProducer(lambda user: market_only_bytes).acceptance(pilot_user)
```

This requires the reviewed app patch in the consuming Python workspace; it
does not install anything on the owner's PC or register a live source. The
projection is bounded by the unchanged8192-byte observation contract. It drops
session/server identity, specs/calls/diagnostic details and never reads risk or
history data into the app projection. Expected status remains BLOCKED,
producer NOT_IMPLEMENTED, source_time/freshness unverified/unknown, all gates
false. Use only existing pilot/auth/CSRF upload protections for any separately
authorized manual observation upload; no new bridge credential or transport.

Capture pass criteria: final capture status success, SDK shutdown COMPLETED,
both session guards pass, two advancing tick/sample pairs, identical current
allowed spec values or an explicit stop on change, valid bounded clock batches
and consistent raw M1 candidates. If any check fails, stop with the fixed
diagnostic outcome; no reconnect/repin, invented candles or cap changes.
These criteria prove a new diagnostic capture, not current live lease when
the report is later imported. The original +1s monotonic lease cannot survive
file transfer into another process. A fresh report also does not fix missing
independent units/DST/candle provenance.

The subsequent implementation gap is trusted producer acceptance and authorized
market-only reader/transport to snapshot(user), with consumption freshness and
approved transformations. That phase is not activated by this review. Keep
analysis.market_source=None and all runtime/AI/paper/broker gates false.

## Validation and limits

New bounded assertions on selected historical facts pass: DEMO/disabled flags,
equal specs, exact lot grid, advancing ticks, capture timing agreement, eight
reported replies and both exact cap/formula outcomes. These are content
consistency assertions, not another original validator suite or broker call.
Completed boundary14, application regressions74, original offline49 and bridge5
were not redundantly repeated. Diff-check passes for this documentation-only
deliverable. Unknown costs, net P&L and drawdown remain unassessed. No economic
claim or trading readiness follows from a successful diagnostic capture.
