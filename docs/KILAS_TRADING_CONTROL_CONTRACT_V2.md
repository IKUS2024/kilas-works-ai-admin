# DEMO control v2 — implemented disabled candidate

This document describes the uncommitted v2 review patch, not a production activation.
Original control-only base: main ffe5df9d695439cea61071f62ace0699c1a4579f.
Cumulative release base: main689ed4e35c3ab97217ade8bfcf21cb837cfbfa78.
Control flag defaults OFF; UI switch remains disabled. The control module introduces
no worker issuer, pairing/exchange, credentials, live broker connection, model call
or orders. Its execution authorization is always false. The separately gated BTC
analysis/evidence path is specified in KILAS_TRADING_BTC_INTEGRATION_CONTRACT_V2.md.
Risk caps, SL/strategy and analysis.market_source=None remain unchanged.

## Authority and installation

New scope: DEMO_BOUNDED_RUN_COORDINATION_V2. Credentials are independently approved
owner/session/server/instrument scoped, hash-only, revocable, maximum lifetime 1800s.
No read-only bridge token or reused hash can authorize control. Scope fixes DEMO
server XMGlobal-MT5 10 and logical GOLD or BTCUSD; actual broker symbol mapping
requires separate local verification. max_run_seconds is nullable with no default;
NULL blocks ON. The 300s engineering ceiling is not owner execution approval.

Explicit offline migration helper applies immutable v1 then additive v2 SQL inside
the existing transaction/advisory lock, with checksums. Never runs on request/boot.
V2 uses separate credentials/controls/receipts tables: v1 rows/scopes/ON are not copied.
Missing prerequisites, existing untracked tables, tracked column drift or checksum
mismatch fail the transaction. Partial DDL and release records roll back together.
No production migration or provisioning is authorized by this patch.

## Exact requests

Base path /products/services/trading. Owner status GET and desired POST retain
existing authenticated pilot/host protections; desired retains global CSRF. No query.
Worker sync is the exact control endpoint exempted from session CSRF; bearer only,
no cookie/query, JSON Content-Type, bounded shared rate protection. The separate BTC
contract specifies two additional exact worker endpoints with the same boundary.
All JSON objects reject unknown/missing keys, duplicates/prototype keys and nonfinite
values; UTF-8 limit 8192 bytes. Errors never return request/raw exception/token text.

POST /control/desired (exact keys):

```json
{"schema_version":2,"command_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expected_revision":0,"desired_state":"ON","instrument":"BTC","lot":"0.01","run_seconds":120}
```

120 is a synthetic illustration, not an approved owner duration. schema_version
strict integer2; command_id 32 lowercase hex; expected_revision integer0<=n<2^63-2;
desired_state ON/OFF; instrument GOLD/BTC; run_seconds strict integer, ON 1..300
and<=separately approved scope cap, OFF exactly 0. Full run must fit scope expiry.
Lot canonical decimal string >=0.01, <=100000000, up to 9 integer/8 fractional digits;
no numeric JSON, exponent, whitespace, leading zeros/redundant trailing fraction zero.
This parser bound is not broker-volume/risk approval. ON requires fresh matching
DEMO/connected/READY/specs/risk/wait NONE OFF+flat report and scoped instrument.
Config changes after a command require fresh current OFF+flat. Active ON cannot be
reissued. Exact latest duplicate is idempotent and never renews deadlines; changed,
superseded or wrong-revision commands conflict.64 sanitized receipts; no replay queue.

POST /control/sync Authorization: Bearer <64 lowercase hex scoped token>.
Bootstrap once per session (stop entries first):

```json
{"schema_version":2,"sequence":0,"challenge":null,"ack":null}
```

Subsequent exact request:

```json
{"schema_version":2,"sequence":1,"challenge":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","ack":{"revision":0,"command_id":null,"actual_state":"OFF","instrument":"BTC","lot":"0.01","account_mode":"DEMO","terminal_connected":true,"position_open":false,"protection_active":false,"specs_verified":false,"risk_allowed":false,"policy_state":"UNSET","wait_reason":"STRATEGY_UNAVAILABLE"}}
```

sequence strict integer0<=n<2^63, subsequent exactly previous + 1. Challenge one-use,
64 lowercase hex, expires 10s. Minimum sync interval 1s, recommended 2s. ack revision
integer0..current; command_id current or known prior intent; null initial prior ack
only OFF+flat. Historical ack delivers newest intent, never displays current RUNNING.
actual_state OFF/PROTECTING/RUNNING/BLOCKED; UNKNOWN output only. account_mode
DEMO/UNKNOWN, REAL rejected. policy_state UNSET/READY/BLOCKED. wait_reason input
NONE/MODEL_UNAVAILABLE/STRATEGY_UNAVAILABLE/NEWS_UNVERIFIED/RISK_BLOCKED/
DEMO_UNVERIFIED/TRANSPORT_UNAVAILABLE. Five flags strict JSON booleans. Open managed
position requires protection_active and PROTECTING/RUNNING. RUNNING additionally
requires ready gates and applicable live ON deadline. No account identifiers,
balances, history, quotes, raw aliases, tickets, credentials or arbitrary fields.

## Complete responses

GET /control/status exact projection (illustrative timestamp):

```json
{"schema_version":2,"enabled":false,"desired_state":"OFF","effective_desired_state":"OFF","actual_state":"UNKNOWN","actual_state_source":"WORKER_ACK_NOT_BROKER_ATTESTATION","worker_fresh":false,"revision":0,"command_id":null,"instrument":"BTC","lot":"0.01","issued_at":null,"command_expires_at":null,"run_seconds":0,"run_expires_at":null,"run_started_at":null,"worker_lease_expires_at":null,"run_status":"NONE","end_reason":"NONE","received_at":"2026-10-10T12:00:00+00:00","ack_received_at":null,"execution_authorized":false,"off_behavior":"STOP_ENTRIES_KEEP_PROTECTION","wait_reason":"CONTROL_DISABLED","account_detail":null}
```

Desired success adds outcome DESIRED_ACCEPTED/IDEMPOTENT. Sync success adds exactly:

```json
{"outcome":"BOOTSTRAPPED","sequence":0,"challenge":"64 lowercase hex","challenge_expires_at":"ISO 8601 UTC"}
```

Non-bootstrap outcome ACK_ACCEPTED. Timestamp fields are ISO 8601 UTC or null.
run_status NONE/PENDING/ACTIVE/ENDED. end_reason NONE/OFF_REQUESTED/
SESSION_REPLACED/WORKER_RESTARTED/CREDENTIAL_UNAVAILABLE/CLOCK_DISCONTINUITY/
RUN_DEADLINE/PICKUP_EXPIRED/WORKER_LEASE_EXPIRED/UNSAFE_ACK. wait_reason adds
output-only CONTROL_DISABLED/WORKER_OFFLINE. No v1 expires_at compatibility alias.
Fresh scoped connected DEMO report permits account_detail exactly:

```json
{"account_mode":"DEMO","broker":"XM","platform":"MT5","server":"XMGlobal-MT5 10","verification":"WORKER_REPORT_ONLY"}
```

The short UI account line labels worker report; default says target offline/unverified.
It never presents this as broker attestation or exposes an account number.
Responses use no-store. Always execution_authorized:false, even effective ON/RUNNING.

## Deadlines, durable stop and recovery

ON acceptance fixes run_expires_at=issued_at+run_seconds (pickup consumes duration),
command_expires_at=min(issued_at+30s,hard deadline), initial soft lease=min(last fresh
ack+6s,hard deadline,scope expiry). Current valid ack before pickup marks ACTIVE and
sets run_started_at once (intent pickup, not order evidence). Subsequent valid sync
renews soft lease<=now+6s bounded by immutable hard/scope deadlines. Passing pickup
once ACTIVE does not end run. Pending prior OFF reports cannot extend pickup.

Scope failure, backwards clock, hard deadline, pending pickup expiry or missed
worker lease latches ENDED before accepting a refresh. Rejected expired challenges
and revoked credentials still commit the stop latch. Replayed same-session bootstrap
also ends a live run; new session fences old desired OFF. Late ack/reconnect cannot
revive ENDED. Fresh OFF+flat and a new explicit owner command are necessary.
No automatic duration/scope renewal, browser heartbeat or persisted ON replay.

OFF stops entries, retaining approved protection/exits; no blind position closure.
Model/news/strategy unavailable uses BLOCKED when flat or PROTECTING when managing,
fixed wait reason; transport can remain live only inside unchanged hard deadline.
Worker must use monotonic deadlines minus full request latency, stop by latest
known soft deadline even if response pending, and treat uncertainty/disabled/revoked/
expired API as no-entry. Server intent is not local runtime/broker authority.

Errors return only {"outcome":"FIXED_CODE"}.401 credential;404 disabled/pilot/host;
409 validation/revision/replay/unsafe ack;413 size;415 JSON;429 rate;503 schema/service.
Global CSRF/host/login retain existing 400/redirect behavior. Duration-specific codes
INVALID_RUN_DURATION/RUN_DURATION_UNAPPROVED/INSUFFICIENT_SCOPE_LIFETIME;
RUN_ALREADY_ACTIVE/RUN_REQUIRES_FLAT_OFF_ACK/RUN_ENDED are new. Existing fixed
command/config/ack/scope/readiness/replay codes remain. A 409 supplies no new challenge;
stop entries and re-establish separately approved session, never blind retry.

Remaining release prerequisites: independently approved run cap/policy, reviewed
scoped issuer/manual provisioning, worker integration, explicit migration/release
approval. None is manufactured or executed here.
