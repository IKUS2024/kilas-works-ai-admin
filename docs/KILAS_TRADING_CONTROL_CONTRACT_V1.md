# DEMO control coordination v1 — disabled candidate, separate scope

Base path `/products/services/trading`. `KILAS_TRADING_CONTROL_ENABLED=true`
is required; default disabled. Explicit manual `kilas_trading_control_v1` schema
release is required after the already-existing bridge schema. No issuer or credential
provisioning API is included. Production scope remains unavailable until separately
reviewed authorization/provisioning. Tests insert only disposable synthetic hashes.

Control sync requires scope `DEMO_CONTROL_COORDINATION_V1`, independently approved,
owner/server/logical-instrument scoped, revocable, lifetime at most 30 minutes.
Only hashes are stored; no raw token is retained. Existing read-only bridge tokens
are never accepted (including attempted reuse of their hash in the scope table).
Read-only transport authority and flags remain unchanged. New control scope never
conveys broker execution authority. No persistent credential, renewal, configuration,
activation, order or paid model call is performed by this candidate.

## Owner APIs

Existing authenticated pilot session and host/OAuth isolation; unsupported users
including other admins/support contexts are excluded. No query parameters.

`GET /control/status` returns the fixed projection below, Cache-Control no-store.
`POST /control/desired` requires existing global CSRF via `X-CSRF-Token`, JSON:

```json
{"schema_version":1,"command_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","expected_revision":0,"desired_state":"ON","instrument":"BTC","lot":"0.01"}
```

Exact keys; schema integer 1, command ID 32 lowercase hex, expected revision integer,
desired ON/OFF, display instrument GOLD/BTC. LOT is a canonical decimal string >=0.01
(max nine integer/eight fractional digits); no broker specification or risk approval.
Only current expected revision is accepted. Exact current duplicate is IDEMPOTENT;
changed payload conflicts, superseded IDs conflict. Latest 64 sanitized receipts;
old requests fail their expected revision even after receipt eviction. One current
intent, no command queue. Lease 30 seconds; duplicate/sync never extends it.

ON requires fresh current acknowledgment: DEMO, terminal connected, policy READY,
specs_verified, risk_allowed, wait_reason NONE, matching scoped logical instrument.
All are worker claims, not broker attestation. OFF needs no readiness. Config changes
require current fresh OFF/flat acknowledgment after any prior command. RUNNING,
PROTECTING, stale/unknown state locks instrument/lot. Scope changes need separate
approved matching session; never move position management to another instrument.

## Outbound worker API

`POST /control/sync`, JSON, `Authorization: Bearer <control-scoped token>`.
No cookies/query; 8KiB maximum. Existing read-only token always 401. Independent
one-use challenge/sequence, no inbound Windows port. Bootstrap exactly:

```json
{"schema_version":1,"sequence":0,"challenge":null,"ack":null}
```

Bootstrap once per control session, after stopping entries, fences old intent OFF.
Worker restart must stop entries and obtain a separately approved new session;
never replay persisted ON. Subsequent exact request:

```json
{"schema_version":1,"sequence":1,"challenge":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","ack":{"revision":0,"command_id":null,"actual_state":"OFF","instrument":"BTC","lot":"0.01","account_mode":"DEMO","terminal_connected":true,"position_open":false,"protection_active":false,"specs_verified":false,"risk_allowed":false,"policy_state":"UNSET","wait_reason":"STRATEGY_UNAVAILABLE"}}
```

All booleans strict. States OFF/PROTECTING/RUNNING/BLOCKED. Account DEMO/UNKNOWN;
REAL rejected. Policy UNSET/READY/BLOCKED. Wait reason NONE/MODEL_UNAVAILABLE/
STRATEGY_UNAVAILABLE/NEWS_UNVERIFIED/RISK_BLOCKED/DEMO_UNVERIFIED/TRANSPORT_UNAVAILABLE.
No account ID, masked ID, balance, quote, history, order/ticket ID, raw symbol suffix,
credential, arbitrary field or free-text error. Open managed position requires
protection_active and PROTECTING/RUNNING. RUNNING requires applicable ON lease and
DEMO/READY gates; model/news/strategy unavailable must not report RUNNING.

Ack identifies the last intent actually received. Known prior revision may be
acknowledged to pull latest intent; that historical ack never displays as current
RUNNING or permits executing old intent. Expired ON cannot report RUNNING. Response
contains only latest intent; acknowledge its revision on next sync. Initial prior
null bootstrap acknowledgment is permitted only OFF/flat. Unknown/evicted intent
or unsafe authenticated acknowledgment fences entries and consumes the challenge.

Successful sync rotates challenge, deadline 10 seconds, advances sequence exactly
one and returns server receive timestamp. ~2-second sync; minimum once/second.
Credential expiry unchanged. Lost/expired challenge or uncertain write: stop entries,
inspect/re-establish approved session; no blind retry. A 409 supplies no new challenge.

## Complete response schemas

Owner status fields (timestamps actual ISO8601 UTC, or null as shown):

```json
{"schema_version":1,"enabled":false,"desired_state":"OFF","effective_desired_state":"OFF","actual_state":"UNKNOWN","actual_state_source":"WORKER_ACK_NOT_BROKER_ATTESTATION","worker_fresh":false,"revision":0,"command_id":null,"instrument":"BTC","lot":"0.01","issued_at":null,"expires_at":null,"received_at":"2026-10-10T12:00:00+00:00","ack_received_at":null,"execution_authorized":false,"off_behavior":"STOP_ENTRIES_KEEP_PROTECTION","wait_reason":"CONTROL_DISABLED","account_detail":null}
```

Desired success: same fields plus `outcome`: DESIRED_ACCEPTED or IDEMPOTENT.
Sync success: same fields plus all of:

```json
{"outcome":"BOOTSTRAPPED","sequence":0,"challenge":"64 lowercase hex","challenge_expires_at":"UTC timestamp"}
```

Subsequent sync outcome ACK_ACCEPTED. Projection state UNKNOWN is server-derived,
not a valid worker actual_state. Stale/absent ack yields WORKER_OFFLINE; disabled
flag yields CONTROL_DISABLED. Otherwise wait_reason is the fixed worker reason.
Fresh account_detail (never accountnumber):

```json
{"account_mode":"DEMO","broker":"XM","platform":"MT5","server":"XMGlobal-MT5 10","verification":"WORKER_REPORT_ONLY"}
```

Account metadata requires fresh valid scoped DEMO/connected worker report. Visible
short line labels it as a worker report. Disabled/offline says target DEMO/XM/MT5 is
unverified/offline, never hard-coded as a current connection. Switch remains disabled.

## Fail-closed semantics, errors and limits

Only latest matching ack <=6 seconds old, valid current lease/scope and DEMO/READY
gates can project RUNNING. Desired ON alone, old revision, stale/offline ack, revoked/
expired credential, negative clock age or failed readiness never shows RUNNING.
Response always `execution_authorized:false`: intent is not an order or broker
permission. Server has no broker/account/market facts to independently approve
lot/notional sizing. Keep all existing risk/SL/one-position/spec/quote checks. No
signals are invented here; Astra + validated-news policy is separate.

OFF, lease expiry, API disabled, credential failure, uncertainty or model/strategy/
news unavailable stops new entries; keep approved existing protection/exit management.
Do not blindly close positions or abandon stops. Model/strategy unavailable reports
BLOCKED (flat) or PROTECTING (managed position), with fixed wait reason and no entries.
Local monotonic deadline must cap server lease minus request latency; clock anomaly
fails closed. Consume intent revisions without turning every ON/lease refresh into
another order. Re-check broker one-position state before every decision.

Errors have only `{"outcome":"FIXED_CODE"}`: 401 credential/scope/expiry/revocation,
404 disabled/pilot/host, 409 invalid payload/revision/replay/unsafe ack, 413 size,
415 JSON, 429 rate, 503 missing schema/service. Global CSRF retains its existing
400 response; host/login middleware retains normal redirects. Known codes include
INVALID_CONTROL_CREDENTIAL, COMMAND_ID_CONFLICT, COMMAND_SUPERSEDED,
REVISION_CONFLICT, CONFIGURATION_LOCKED, CONFIGURATION_REQUIRES_OFF_ACK,
WORKER_SCOPE_UNAVAILABLE, WORKER_NOT_READY, BOOTSTRAP_REPLAY,
REPLAY_OR_EXPIRED_CHALLENGE, ACK_COMMAND_MISMATCH, ACK_SCOPE_MISMATCH,
REAL_ACCOUNT_REJECTED, PROTECTION_REQUIRED, RUNNING_GATES_REJECTED,
RUNNING_LEASE_REJECTED, CONTROL_RATE_LIMIT and CONTROL_UNAVAILABLE.

No release, credential issuance, runtime activation or production migration in this task.
