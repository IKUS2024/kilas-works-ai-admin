# BTC DEMO integration v2 — stable worker contract, disabled candidate

Replaces BTC source/analysis v1 contracts. Base main is
`689ed4e35c3ab97217ade8bfcf21cb837cfbfa78`, plus the existing uncommitted control v2
candidate. Code and fixtures only: no actual credential, grant, provider/news/PC
call, production migration, deployment or execution. Runtime analysis stays
`gpt-6.1-sol`, reasoning `medium`, service tier `default`.

## Transport

Base `/products/services/trading/control`. Control `/sync` v2 is unchanged; see
`KILAS_TRADING_CONTROL_CONTRACT_V2.md`. New worker paths are POST `/btc-evidence`
and `/btc-analysis`. JSON <=8192 UTF-8 bytes; existing separately approved
DEMO_BOUNDED_RUN_COORDINATION_V2 bearer64 lowercase hex; no cookies or query.
Unknown/missing fields, duplicate/prototype keys and nonfinite JSON reject. A
read-only bridge bearer is insufficient. Owner/session/host/CSRF boundaries remain.
Every non-200 body is exactly `{"outcome":"FIXED_ERROR_CODE"}` with no raw data.

All session, command, evidence and decision IDs are32 lowercase hex; challenge and
SHA-256 values64. Revision is integer0..2^63-2; sequence integer0..2^63-1. Lot is
the existing canonical decimal string>=0.01, subject to separate broker/risk gates.
Every JSON example below is synthetic; placeholders are not valid transmitted IDs.

## Evidence bootstrap

Exact request fields and initial example:

```json
{"schema_version":2,"session_id":"<32hex>","revision":0,"command_id":null,"instrument":"BTC","lot":"0.01","sequence":0,"challenge":null,"account_mode":"DEMO","terminal_connected":true,"market":null,"spec":null,"risk":null}
```

Always use CURRENT control revision/command/lot, which need not be0/null/0.01.
A fresh matching DEMO control acknowledgement is required first. Capture nonce
and control-sync nonce are independent. Exact bootstrap response:

```json
{"schema_version":2,"outcome":"CAPTURE_CHALLENGE_ISSUED","sequence":0,"challenge":"<64hex>","challenge_expires_at":"<UTC>","received_at":"<UTC>","execution_authorized":false}
```

Sequence is the last accepted evidence sequence, not necessarily0. A duplicate
bootstrap rejects while the nonce is fresh. After expiry, bootstrap recovers the
current sequence without resetting it or renewing session/run/lease deadlines.
After a lost successful response, recover then recapture; do not replay old data.

## Normal capture

Same exact top-level fields as bootstrap, sequence=accepted+1, challenge=returned
nonce, and populated market/spec/risk with these EXACT nested shapes:

```json
{
  "market": {
    "symbol":"BTCUSD","timeframe":"M1",
    "tick":{"time":1791633601,"time_msc":1791633601000,"bid":"60000","ask":"60010"},
    "capture":{"start_utc":"2026-10-10T12:00:00.900000+00:00","end_utc":"2026-10-10T12:00:01+00:00","start_mono_ns":100,"end_mono_ns":100000100},
    "candles":[{"time":1791633540,"open":"60000","high":"60020","low":"59980","close":"60000"}],
    "clock":null,"clock_profile":null
  },
  "spec":{"symbol":"BTCUSD","contract_size":"1","volume_min":"0.01","volume_max":"1","volume_step":"0.01","tick_cents":100,"stops_distance_cents":100,"cost_bound_cents":50,"verified_at":"2026-10-10T12:00:00+00:00"},
  "risk":{"captured_at":"2026-10-10T12:00:01+00:00","position_open":false,"protection_active":false,"daily_loss_remaining_cents":50000,"strategy_verified":true,"cooldown_clear":true,"loss_streak_clear":true,"broker_contract_sha256":"<64hex>","policy_version":"<64hex>"}
}
```

Example illustrates shape only: send exactly12 contiguous closed M1 bars. Bar time
is raw broker OPEN epoch, integer divisible by60, interval60s. Last bar closes<=tick
and less than60s earlier. Tick time/time_msc agree. Prices are positive decimal
strings that normalize exactly to USD cents; sub-cent precision rejects.

Begin capture AFTER nonce receipt, finish within2s, reach server within its <5s
challenge window. UTC claims must have positive<=2s delta matching monotonic duration
within50ms; absolute PC UTC need not be proven. Server checks capture duration<=elapsed
challenge time+50ms. This bounds transport/capture from an accepted producer; it is
not independent proof that the producer is truthful or absolute broker-clock proof.
Broker epoch labels remain relative; no candidate +3h subtraction occurs.

Optional clock exact shape is
`{status:"PRODUCER_CLAIM_ONLY",offset_seconds:"0",uncertainty_ms:"1"}`;
optional clock_profile exact shape is
`{profile_id:"candidate-id",candidate_offset_seconds:10800,evidence_ref:"review-ref"}`.
The existing bridge validator's string/range limits apply. Normalized clock/profile
verification remains false, with time_basis RECEIPT_BOUNDED, regardless of claims.

Spec contract/volume values are canonical positive decimal strings. Tick is positive
integer cents; stops distance nonnegative integer cents. Cost bound is nonnegative
integer cents or null. Unknown commission/slippage/swap bound must remain null and
blocks proposal/entry; do not guess zero. verified_at is a shape-checked producer
claim; server spec approval time comes from the reviewed manifest. Contract hash is
SHA-256 of sorted compact JSON of spec EXCLUDING verified_at (and normalized id/verified).
Changed contract/cost facts require reviewed acceptance, not a worker claim.

Risk booleans are strict; captured_at exactly equals capture.end_utc. Daily remaining
loss is integer0..50000 cents, not account balance. Open position requires protection.
No account ID, balance, history, login, ticket, secret, URL, news, prompt or arbitrary
field may be submitted. Exact successful response:

```json
{"schema_version":2,"outcome":"EVIDENCE_ACCEPTED","session_id":"<32hex>","sequence":1,"challenge":"<next64hex>","challenge_expires_at":"<UTC>","evidence":{"market_id":"<32hex>","spec_id":"<32hex>","news_id":null},"coverage":"BTC_EDITORIAL_ONLY","risk_review":"UNREVIEWED","tick_liveness":"UNCONFIRMED","execution_authorized":false,"received_at":"<UTC>"}
```

news_id is null until fresh news is available, otherwise32hex. risk_review is
UNREVIEWED/SERVER_REVIEWED. First capture is UNCONFIRMED; a subsequent strictly
advancing time_msc is VERIFIED. Frozen tick proof ages out after5s despite repeated
uploads; backward ticks reject. Keep capture and heartbeat current during inference.

## Analysis

Exact request, operation_key16..80 letters/digits/underscore/hyphen:

```json
{"schema_version":2,"operation_key":"worker-operation-123","session_id":"<32hex>","revision":1,"command_id":"<32hex>","instrument":"BTC","lot":"0.01","evidence":{"market_id":"<32hex>","news_id":"<32hex>","spec_id":"<32hex>"}}
```

IDs resolve only within accepted owner/session records. Schema1 rejects. HTTP200
has exactly these fields (decision may be null):

```json
{"schema_version":2,"outcome":"PROPOSAL_READY","instrument":"BTC","model":"gpt-6.1-sol","reasoning":"medium","decision":{"decision":"BUY","reason":"Synthetic example only","invalidation":"Synthetic example only","stop_cents":5981000,"target_cents":6041000,"news_risk":"LOW"},"news_coverage":"BTC_EDITORIAL_ONLY","risk_state":"PASSED","execution_authorized":false,"checked_at":"<UTC>","session_id":"<32hex>","operation_key":"worker-operation-123","revision":1,"command_id":"<32hex>","evidence":{"market_id":"<32hex>","news_id":"<32hex>","spec_id":"<32hex>"},"decision_id":"<32hex>","authorization_expires_at":null}
```

Decision exact fields as above. BUY/SELL/WAIT; reason1..400 chars; invalidation<=240;
BUY/SELL SL+TP positive integer cents, WAIT bothnull; news_risk LOW/HIGH/UNKNOWN.
decision_id=first32hex SHA-256 of sorted compact canonical complete request. Exact
retry keeps the ID and makes no second inference call. Reusing operation_key with
changed evidence/intent rejects. Echoed evidence is immutable model evidence; final
validation also checks newer accepted quote/risk and matching news/spec/candles.

Fresh UNREVIEWED editorial news reaches the model without mandatory manual LOW
review. LOW means only within BTC_EDITORIAL_ONLY, not global/macro/calendar coverage.
HIGH/UNKNOWN, empty articles or known source HIGH block entries. Valid empty RSS is
empty/UNKNOWN; malformed/failing/stale feed blocks analysis. Fixed proposed RSS
endpoint has not been contacted or verified; collection defaults disabled.

When enabled and an approved session exists, both bootstrap and normal captures
invoke news collection if no fresh nonempty record is cached. Missing or valid
empty news retries at most once per30s across web workers, using persisted session
backoff. Collection happens outside the source-state transaction so independent
control sync remains responsive. Configured fetch limits are no redirects,
5s connect/10s read timeouts,262144 bytes and an elapsed15s check between chunks.
These are transport limits, not a guaranteed total wall-clock deadline.

A slow retry can exhaust the current5s capture challenge and return
CAPTURE_WINDOW_EXPIRED. Recover with bootstrap, use its last accepted sequence,
then capture again after the new nonce. The cached news is reused; no run, lease,
credential or approved-session expiry is extended. Empty news always blocks entry.

PROPOSAL_READY/PASSED alone is not execution permission. Other outcomes have BLOCKED
risk_state, including COSTS_UNKNOWN, NOTIONAL_CAP_BLOCKED, VOLUME_BLOCKED,
POLICY_BLOCKED, POSITION_OPEN, TICK_LIVENESS_UNCONFIRMED, NEWS_RISK_BLOCKED,
MODEL_WAIT, SLTP_BLOCKED, LOSS_CAP_BLOCKED, MODEL_PREFLIGHT_UNAVAILABLE,
MODEL_RESULT_UNAVAILABLE, MODEL_ACCOUNTING_BLOCKED and POST_MODEL_GATE_BLOCKED.
Unknown/error outcomes mean no entry. authorization_expires_at is null unless
execution_authorized true. Its bound is the earliest of manifest/credential/runtime
expiry, hard run deadline, soft worker lease, capture-challenge issue+5s and tick
advance receipt+5s. Final context is checked for both fresh and cached results.

## Local worker integration

1. Keep independent control sync responsive while evidence/model calls run. Use
   current intent everywhere. OFF stops entries immediately and retains managed
   protection. A matching ready OFF/BLOCKED acknowledgement may obtain the first
   grant during ACTIVE ON; do not claim RUNNING before eligibility.
   Pace sync around2s and capture around3s, leaving bootstrap/model request headroom
   within the existing shared60 requests/minute/IP/per-process limit. Do not run
   both loops every2s; any rate-limit response stops entry until freshness recovers.
2. Bootstrap evidence; capture after nonce; establish advancing tick time; obtain
   non-null news ID; submit IDs to model. Refresh capture during inference. No
   report/fixture substitution or self-issued producer approval.
3. Require schema2, matching echoed context, PROPOSAL_READY/PASSED, BUY/SELL,
   execution_authorized true and unexpired authorization. Consume decision_id once.
4. Use a RECENT FAST authenticated sync/evidence clock sample: record local monotonic
   send S and server received_at T. At local monotonic M, conservative server-now
   upper bound is T+(M-S), plus worker drift/scheduling margin. Reject regressing or
   discontinuous samples. No absolute PC UTC/broker offset proof is needed. Using
   the slow model request's full RTT is conservative but may unnecessarily expire
   valid results; use the heartbeat sample obtained while inference was running.
5. Immediately before entry recheck current owner ON/session/revision/command,
   immutable run/lease bounds, local DEMO/server/symbol/spec identity, current tick,
   no conflicting position, stop/freeze/tick rules, SL/TP, costs and all caps. Any
   timeout/uncertainty stops entries and preserves protection. No service response
   removes the final local gate or authorizes REAL execution.

## Actual server handoff, separately authorized

Concrete `btc_sources.accepted_sources` is wired to approval/evidence/runtime
interfaces. It starts empty. There is no HTTP issuer or automatic provisioning.
After separately approved provisioning, the server-only handoff is
`accepted_sources.install_reviewed(manifest, acceptance)` with exact objects:

```json
{"user_id":1,"session_id":"<32hex>","instrument":"BTC","server":"XMGlobal-MT5 10","created_at":"<UTC>","expires_at":"<UTC>","model_analysis_allowed":true,"policy_version":"<64hex>","max_loss_cents":1000,"max_requests":1}
```

```json
{"producer_acceptance":"ACCEPTED","clock_verified":false,"profile_verified":false,"profile_id":"candidate-profile","evidence_ref":"reviewed-producer-reference","candidate_offset_seconds":10800,"broker_contract_sha256":"<64hex>","policy_version":"<same64hex>"}
```

Examples are not approved user/duration/loss/request settings. Manifest<=300s and
within credential expiry; max_requests1..10 and max_loss_cents1..2000. Selected
limits need approval. ACCEPTED means reviewed producer/contract/policy for this
receipt-bounded path, not absolute clock/profile proof. Historical NOT_IMPLEMENTED
diagnostics cannot become accepted by upload or copying examples.

### Evidence-only sessions

The same server-side manifest also accepts the exact permission combination
`model_analysis_allowed:false, max_requests:0, max_loss_cents:0`. Mixed permissions,
boolean budgets and nonzero evidence-only budgets reject. The normal model-approved
combination still requires true and both existing positive budgets.

Evidence-only admission needs CONTROL and BTC_EVIDENCE enabled; BTC_ANALYSIS, AI,
BTC_NEWS and BTC_RUNTIME may all remain disabled. The worker schema2 payload is
unchanged. Require credential `max_run_seconds=NULL`, desired OFF, no pending/active
run, and a fresh matching OFF/flat DEMO acknowledgement. Recheck this boundary under
the source transaction before rotating a nonce or storing a capture. An approved
60-second exchange uses credential and manifest expiry; it never issues ON.

Evidence-only ingestion never fetches or attaches news, even if the global news
flag changes; news_id stays null. It returns execution_authorized false. Analysis
and runtime-grant installation reject this manifest even if their flags are later
enabled. Unknown cost bounds, false strategy booleans and zero remaining-loss
context remain valid evidence; reviewed owner/session/spec/policy provenance and
all capture validation still apply. No zero values confer model or loss authority.

Separate runtime permission is installed once per approved session by
`accepted_sources.install_runtime_authority(user_id, session_id, grant)`:

```json
{"user_id":1,"session_id":"<32hex>","policy_version":"<same64hex>","expires_at":"<UTC within manifest>","runtime_eligible":true,"broker_execution_allowed":true,"policy_replay_only":false,"server":"XMGlobal-MT5 10","instrument":"BTC"}
```

Command/revision are derived from current ACTIVE owner ON, not fixed in the grant.
No token elevation occurs. Control projection always has execution_authorized false;
only a fully gated BTC result may grant bounded eligibility. No server order runs.

## Shared storage and limits

One sanitized state record in existing tenant kilas_trading_events uses action
BTC_SOURCE_STATE_V2, key btc-source-state-v2, <=262144 bytes, <=64 immutable records,
one approved pilot session. Existing DB transaction/advisory locks serialize web
workers; process memory is not authority. Nonces are hash-only. No new schema,
migration, service or raw report/RSS/account/history/balance/credential retention.
Expired state is ineligible immediately and purged lazily on next access. Restart
loads original sequence/expiry and never renews command/run/lease.

Control/BTC analysis/evidence/news/runtime and existing AI flags all default off.
No non-fixture flag was changed. USD2000 notional, SL/strategy, USD5 monthly,
USD0.25 daily,10 daily requests and risk caps remain unchanged. Existing
analysis.market_source=None, MOCK, disabled UI,8KiB market upload and other products
remain unchanged. Real automation still requires PC schema2 integration/tests,
reviewed producer/spec/cost/policy facts, approved scoped budgets/authority and
parent-reviewed release/activation. Production remains689ed4e.
