# Accepted BTC source adapters — historical v1 candidate

Superseded by `KILAS_TRADING_BTC_INTEGRATION_CONTRACT_V2.md`. The old wire schema,
memory-only storage and mandatory clock/manual-news gates below are historical.

Base main 689ed4e plus uncommitted v2/BTC model candidate. No deployment, flags,
credentials, actual provider/news request, PC access, migration or runtime grant.
Actual adapter classes/functions are wired, replacing empty injection points.
Approval/runtime permission remains a separate reviewed handoff, never minted here.

## New proposed permission and destinations

Worker-to-service data destination only:
https://trading.kilasworks.id/products/services/trading/control/btc-evidence
New explicit KILAS_TRADING_BTC_EVIDENCE_ENABLED flag default false. Requires
existing separate DEMO_BOUNDED_RUN_COORDINATION_V2 bearer plus approved analysis
session and accepted producer/profile/contract record. Existing read-only scope,
observations upload and bridge payload contracts remain unchanged. No cookies,
query, client account ID/balance/history/credentials/URLs/prompts/arbitrary fields.
Owner/host authorization and bounded transport-rate defenses stay in force.

The only proposed public news destination is fixed:
https://www.coindesk.com/arc/outboundfeeds/rss/
KILAS_TRADING_BTC_NEWS_ENABLED default false. No external request was made; URL
availability/redirect/production content has not been verified. Collector sends
only fixed public Accept/User-Agent headers, no owner data, token or server key.
No alternate destination, redirects, retries, discovery, schedule or paid feed.

## Exact ingest request

POST, bearer 64 lowercase hex, JSON <=8192 bytes. Exact top-level fields:

```json
{"schema_version":1,"session_id":"32 lowercase hex","revision":0,"command_id":null,"instrument":"BTC","lot":"0.01","sequence":1,"account_mode":"DEMO","terminal_connected":true,"market":{"symbol":"BTCUSD","timeframe":"M1","tick":{"time":1791633601,"time_msc":1791633601000,"bid":"60000","ask":"60010"},"capture":{"start_utc":"2026-10-10T12:00:00.900000+00:00","end_utc":"2026-10-10T12:00:01+00:00","start_mono_ns":100,"end_mono_ns":100000100},"candles":[],"clock":{"status":"PRODUCER_CLAIM_ONLY","offset_seconds":"0","uncertainty_ms":"1"},"clock_profile":{"profile_id":"synthetic-clock-policy","candidate_offset_seconds":0,"evidence_ref":"synthetic-reviewed-proof"}},"spec":{"symbol":"BTCUSD","contract_size":"1","volume_min":"0.01","volume_max":"1","volume_step":"0.01","tick_cents":100,"stops_distance_cents":100,"cost_bound_cents":50,"verified_at":"2026-10-10T12:00:01+00:00"},"risk":{"captured_at":"2026-10-10T12:00:01+00:00","position_open":false,"protection_active":false,"daily_loss_remaining_cents":50000,"strategy_verified":true,"cooldown_clear":true,"loss_streak_clear":true,"broker_contract_sha256":"64 lowercase hex","policy_version":"64 lowercase hex"}}
```

Example shapes are synthetic; market.candles must actually contain exactly 12
closed raw M1 bars with exact time/open/high/low/close keys. Raw time is broker bar
OPEN epoch, integral minute, contiguous 60s; tick.time_msc//1000==tick.time.
Existing bridge.validate_market validates exact schema, price/OHLC, capture elapsed
wall/monotonic duration<=2s with<=50ms disagreement, closed-bar ordering and profile
field shapes. Typed schema 1, sequence 1..2^63-1 exactly previous+1. Strict session,
revision/command/instrument/lot match current fresh DEMO+connected worker intent.
No REAL account, test-fixture flag, producer-supplied verified flag or mixed fields.

A separately accepted server profile normalizes tick epoch by subtracting the
approved offset; bar close UTC=raw bar open-offset+60. This is not inferred from
broker suffix or an unverified +3h candidate. Source clock claim offset<=0.25s,
uncertainty<=250ms and exact approved profile/proof/offset required. Existing actual
producer_acceptance NOT_IMPLEMENTED or candidate/unverified profile is rejected.
Captures/ticks/risk must be current<=5s; future/duplicate capture rejected. Prices
convert exactly to integer USD cents, extra fractional precision rejected.

Spec keys exact as shown. Positive canonical contract/volume decimals, broker
volume step, integer tick/stop constraints; cost bound integer>=0 or null. Null
never becomes zero and blocks risk. Spec hash uses canonical sorted compact JSON
of spec keys EXCEPT verified_at (no verified/id allowed in input); SHA256 must match
server-accepted broker contract and risk.broker_contract_sha256. Policy digest must
match reviewed server acceptance. Spec age<=300s. Open position without protection
rejects ingestion. Risk facts remain producer reports; accepted provenance does not
constitute independent broker attestation. Server independently gates decisions.

## Exact ingest response

```json
{"schema_version":1,"outcome":"EVIDENCE_ACCEPTED","session_id":"32 lowercase hex","sequence":1,"evidence":{"market_id":"server32hex","spec_id":"server32hex","news_id":null},"coverage":"BTC_EDITORIAL_ONLY","risk_review":"UNREVIEWED","execution_authorized":false,"received_at":"UTC timestamp"}
```

news_id is nullable until a fresh server-collected record exists. When available,
IDs can be copied unchanged into the BTC analysis request. Client cannot create
IDs or upload news. All IDs opaque server generated, scoped to one accepted owner
session. Exact replay/invalid sequence/capture rejects; no raw payload retained.

## Concrete server adapter and reviewed record handoff

btc_sources.accepted_sources is the real approval/evidence adapter. It has no HTTP
issuer or grant route. install_reviewed(manifest,acceptance) accepts a previously
reviewed nonsecret model-session manifest (same model contract) plus exactly:

```json
{"producer_acceptance":"ACCEPTED","clock_verified":true,"profile_verified":true,"profile_id":"reviewed bounded ID","evidence_ref":"reviewed proof ID","candidate_offset_seconds":0,"broker_contract_sha256":"64 lowercase hex","policy_version":"same reviewed 64 hex policy digest"}
```

The handoff must independently validate actual owner/session, trusted producer,
clock/profile/broker mapping, contract/cost evidence and local policy before calling
this internal method. Worker cannot invoke it. These records are not credentials
or additional owner permission. No actual owner record was installed in this task.
Only one reviewed session may be resident; duration<=300s, cap/expiry mandatory.
Session credential remains separately reviewed and checked against its own expiry.

Memory-only, locked cache: at most 64 immutable market/news/spec records for one
active session, plus latest sanitized risk/one feed and nonsecret approval. No DB
migration, raw report persistence, filesystem/token/browser storage, account IDs,
balances/history or general upload. Access purges expired/backwards-clock sessions;
service restart loses acceptance and data and fails closed. Evicted IDs fail; no
silent replay/refetch. resolve/latest validate owner/session and current review.
Revocation removes accepted session. Existing credential/pilot revocation is checked
on every route and before/after model; no scope renewal or credential provisioning.

## Public collector coverage and independent risk review

btc_news.collect performs fixed GET only if explicitly enabled: connect 5s/read 10s,
redirects off, no retry,<=262144bytes and 15s streaming bound. Require HTTP200 RSS,
reject DOCTYPE/entity syntax, malformed/oversized XML and >100 items. Select 1..3
unique Bitcoin/BTC title items published<=3600s, no future dates; HTML text stripped,
whitespace normalized, title<=240chars. Ignore arbitrary links/descriptions/fields.
Only normalized title/publication/content IDs retained; raw XML discarded.

Coverage is BTC_EDITORIAL_ONLY. It omits comprehensive economic calendars,
sanctions/geopolitics, broker notices, every exchange and full real-time news.
Verified means fixed-source parsed/fresh transport, never all factual claims true
or complete coverage. Fresh feed valid<=300s; neutral sentiment 0 is no assessment.
Every fetched feed starts event_risk UNKNOWN, risk_review UNREVIEWED. Never infer
LOW from lack of a headline. No automatic model/entry permission from RSS.

Server-side collect_news stores this normalized record with a new opaque feed ID.
No browser page load, ingestion request or import automatically collects news.
No scheduler or production call was added. The source resolves only collected and
fresh records; unavailable/expired feed blocks analysis. Future explicit operator
collection authorization and endpoint availability still need review.

A separate reviewed event-risk evidence record may be passed to the internal
review_news(user,session,record) method, exact keys:

```json
{"news_id":"server feed 32 hex ID","policy_version":"reviewed 64 hex policy digest","coverage":"BTC_EDITORIAL_ONLY","event_risk":"LOW","sentiment":0,"expires_at":"UTC timestamp"}
```

This is not a client-submitted API or RSS classification. Independent reviewed
risk assessment must explicitly cover/accept the declared limited coverage. It
must match current feed/policy/session and expire within feed and session. LOW in
fixtures is synthetic, not an actual market claim/owner approval. Review may be
HIGH/UNKNOWN instead. Changed/revoked/expired review invalidates old LOW records.
Only SERVER_REVIEWED+LOW can pass the analyst news gate; coverage label remains.

## Model adapter schema extension and end-to-end trace

Analysis request/response v1 shapes unchanged. Internal news schema now additionally
requires coverage BTC_EDITORIAL_ONLY and risk_review UNREVIEWED/SERVER_REVIEWED.
Model receives these declared limitations. Actual adapters are wired and empty
until reviewed handoff; runtime_authorization_source remains separate/unconfigured.
All feature flags still default false; no execution or broker order handler added.

Synthetic trace traverses actual transport and parsers:
1. Approved synthetic session/producer/contract (no actual scope issuance).
2. Fake fixed RSS GET through real collector ->UNKNOWN/UNREVIEWED.
3. Actual bearer ingress ->server IDs; analysis ->NEWS_RISK_BLOCKED, no fake model call.
4. Explicit synthetic server risk review; next fresh actual ingress ->reviewed IDs.
5. Actual analysis route ->fixed fake model catalog/response ->PROPOSAL_READY;
   execution_authorized=false. Duplicate request performs no second fake inference.

Tests also cover malformed/oversized feed, redirect refusal, absent BTC coverage,
stale/future articles, safe text, unaccepted profile, mixed private fields, REAL,
wrong contract/policy, replay, precision, ownership/ID isolation, revocation/restart,
bounded cache and session expiry. No live SDK/NTP/news/inference/order tests.
