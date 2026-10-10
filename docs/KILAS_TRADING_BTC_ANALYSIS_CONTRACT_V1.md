# BTC DEMO model integration — historical v1 candidate

Superseded by `KILAS_TRADING_BTC_INTEGRATION_CONTRACT_V2.md`; use its exact schemas,
receipt timing, autonomous news assessment and runtime handoff.

Base main 689ed4e35c3ab97217ade8bfcf21cb837cfbfa78. This code is uncommitted,
not deployed, not activated. Production catalog-only check was independently
verified by parent browser at 2026-10-10T11:42:50Z (PRESENT/200/exact model match Yes);
that evidence does not certify inference or execution. No paid request was run.

## Exact worker request

POST https://trading.kilasworks.id/products/services/trading/control/btc-analysis
Authorization: Bearer <separately approved 64 lowercase hex control token>
Content-Type: application/json; no cookies/query,8192 byte UTF-8 bound. The exact
endpoint has token/scope/owner checks instead of browser session CSRF. All other
Trading owner routes retain their session/pilot/host/CSRF protections unchanged.
Read-only bridge tokens never grant analysis. Global and per-session cost/request
limits still apply. No upload, URL, account field, client prompt or model selection.

```json
{"schema_version":1,"operation_key":"synthetic-operation-123","session_id":"dddddddddddddddddddddddddddddddd","revision":0,"command_id":null,"instrument":"BTC","lot":"0.01","evidence":{"market_id":"11111111111111111111111111111111","news_id":"22222222222222222222222222222222","spec_id":"33333333333333333333333333333333"}}
```

Exact keys at both levels. Integer schema 1, integer revision 0..2^63-2, command_id
32 lowercase hex or null matching current intent. Session/evidence IDs 32 lowercase hex.
operation_key 16..80 ASCII alphanumeric/underscore/hyphen. Instrument BTC only;
lot canonical decimal string through existing control validator (minimum 0.01).
Must match latest fresh control-session intent/lot/instrument. Fresh ACK must
report DEMO and connected. Model proposals may be requested while OFF under
explicit analysis approval; OFF still blocks execution. No worker ON is created.

## Concrete trusted server adapters (disabled; no accepted production records)

The concrete bounded adapter is now wired. Its ingestion, public collector,
reviewed-producer handoff and news coverage extension are specified in
`KILAS_TRADING_BTC_SOURCE_CONTRACT_V1.md`. No grant, collection or activation runs
automatically. Runtime authorization remains separately unconfigured.

`approval_source.session(user_id, session_id)` returns exactly:

```json
{"user_id":123,"session_id":"32 lowercase hex","instrument":"BTC","server":"XMGlobal-MT5 10","created_at":"UTC timestamp","expires_at":"UTC timestamp","model_analysis_allowed":true,"policy_version":"64 lowercase hex reviewed policy digest","max_loss_cents":1000,"max_requests":1}
```

All sample cap/duration/user values are synthetic, not owner approval. Session
lifetime 1..300s, within existing scoped credential expiry; no renewal. Explicit
max_requests 1..10, enforced atomically with durable cost reservation. Explicit
max_loss_cents 1..2000, at most 1% of unchanged USD2000 notional ceiling; this is a
conservative dollar-loss ceiling, not a claim of 1% actual account equity. Scope
DEMO_BOUNDED_RUN_COORDINATION_V2 remains owner/server/BTCUSD-bound and independently
approved; its max_run_seconds is still unset without separate owner approval.
A control token alone does not grant model-analysis or runtime authority.

`evidence_source.resolve(user_id, session_id, evidence_ids)` returns immutable
approved market/news/spec records plus sanitized risk context. It must enforce
owner/session provenance and producer acceptance, not trust submitted IDs or JSON.
`evidence_source.latest(user_id, session_id)` returns latest verified quote/risk
context for post-model validation. No client upload or read-only diagnostic report
is adopted as this adapter. Adapters must reject revoked/unaccepted records.
Return exactly these nested schemas (examples are synthetic):

```json
{
  "market": {
    "id":"32 lowercase hex", "kind":"DEMO", "provider":"TRUSTED_BTC_V1",
    "symbol":"BTCUSD", "timeframe":"M1", "captured_at":"UTC timestamp",
    "quote_time":"UTC timestamp", "bid_cents":6000000, "ask_cents":6001000,
    "clock_verified":true, "profile_verified":true,
    "candles":[{"time":"UTC close timestamp","open":6000000,"high":6002000,"low":5998000,"close":6000000}]
  },
  "news": {
    "id":"32 lowercase hex", "provider":"TRUSTED_NEWS_V1",
    "as_of":"UTC timestamp", "valid_until":"UTC timestamp", "verified":true,
    "event_risk":"LOW", "sentiment":0,
    "coverage":"BTC_EDITORIAL_ONLY", "risk_review":"SERVER_REVIEWED",
    "articles":[{"id":"32 lowercase hex","published_at":"UTC timestamp","title":"bounded source text"}]
  },
  "spec": {
    "id":"32 lowercase hex", "symbol":"BTCUSD", "verified":true,
    "contract_size":"1", "volume_min":"0.01", "volume_max":"1",
    "volume_step":"0.01", "tick_cents":100, "stops_distance_cents":100,
    "cost_bound_cents":50, "verified_at":"UTC timestamp"
  },
  "risk": {
    "captured_at":"UTC timestamp", "position_open":false,
    "protection_active":false, "daily_loss_remaining_cents":50000,
    "strategy_verified":true, "cooldown_clear":true, "loss_streak_clear":true
  }
}
```

Market actually requires 12..48 contiguous closed M1 bars; sample shows shape only.
Prices strict positive integer USD cents<=100000000 with consistent OHLC, bid<=ask.
Initial/latest quote/risk age<=5s, future timestamps rejected; verified clock/profile
mandatory. TEST_FIXTURE accepted only inside Flask testing context. Candles end
within 65s before quote. Spread<=unchanged 20bps. News verified, age/validity<=300s;
event_risk LOW/HIGH/UNKNOWN, sentiment integer -1/0/1. Coverage is explicitly
BTC_EDITORIAL_ONLY; risk_review is UNREVIEWED/SERVER_REVIEWED. Only a separately
SERVER_REVIEWED+LOW assessment can pass; public collection alone remains UNKNOWN. 1..3 articles, each title 1..240
chars and publication age <=3600s. News text is data, never instruction. Spec age
<=300s; canonical positive Decimal contract/volume specs, integer tick>=1 and stop
distance>=0. Cost bound integer>=0 or null; null blocks proposals/entries. Producers
must substantiate commission+slippage+swap upper bounds; unknown costs remain unknown.
Risk flags strict booleans; daily remaining loss 0..unchanged 50000 cents, no balance,
account identifier, credential, arbitrary fields or raw history accepted. Evidence
JSON <=12000 bytes. Provider labels name adapters, not a new connected integration.

## Model and independent gates

Existing server-owned Sol6.1 Medium/default route; fixed metadata GET and Responses
POST helpers, redirects off, no retries/tools, store=false. Body contains only
market/news evidence, fixed BTC instructions and existing strict decision schema:

```json
{"decision":"BUY","reason":"bounded text","invalidation":"bounded text","stop_cents":5981000,"target_cents":6041000}
```

Decision BUY/SELL/WAIT; reason1..400chars, invalidation<=240chars; BUY/SELL SL+TP
positive integer cents, WAIT bothnull. Model must return expected model/tier,
completed status and bounded usage. Wrong protocol/accounting holds reservation
and blocks reuse. Existing USD5/month, USD0.25/day, 10/day and token bounds retained.
Rates/policy expiry retained; no provider compatibility claim from fixtures.
Durable event stores only hashes, fixed source metadata, budget/model result;
raw market/news/risk/approval reports and account data are not stored by this route.
Session-bound operation IDs prevent cross-session adoption. Repeated same request
has no second paid call; changed evidence/intent with reused key conflicts. Identical
intent/evidence fingerprint excludes operation_key to prevent duplicate inference.

Deterministic gates before and after model: volume min/max/step, LOW event risk,
strategy/cooldown/loss-streak verification, no open position, known cost bound,
notional ask*lot*contract<=unchanged 200000 cents. BUY stop<ask<target; SELL target<bid<stop.
Stops/targets obey broker distance/tick grid, stop distance<=existing 5% price bound.
Worst loss = abs(entry-stop)*lot*contract + verified total cost upper bound must
fit explicit approved per-trade and remaining daily caps. Model never relaxes caps
or supplies broker specs/risk authority. GOLD requests always fail BTC_ONLY.

Locks are released while HTTP is pending: OFF/revocation/heartbeat need not wait.
Recheck scoped approval, flags, paper pause/kill, evidence and policy before paid
POST; after response recheck all again, including immutable source identity and
fresh latest quote/risk. Original proposal evidence maximum age 30s; latest quote
and risk maximum 5s. Changed news/spec/closed-bar batch blocks. Quote movement>
existing20bps bound blocks. Latest entry/SLTP loss is recomputed from fresh quote.
Worker must run v2 sync independently during inference; a missed 6s control lease
never renews because the model returned. Missing/slow/new-position data fails closed.

## Runtime gate (implemented, default false)

`KILAS_TRADING_BTC_RUNTIME_ENABLED` must explicitly equal true, plus a separately
reviewed `runtime_authorization_source.authorization(user_id,session_id)` must
return exactly:

```json
{"user_id":123,"session_id":"32 lowercase hex","command_id":"32 lowercase hex","revision":1,"policy_version":"same 64 hex reviewed digest","expires_at":"UTC timestamp","runtime_eligible":true,"broker_execution_allowed":true,"policy_replay_only":false,"server":"XMGlobal-MT5 10","instrument":"BTC"}
```

Authority binds user/session/current command+revision/policy/server/BTC; expiry
cannot exceed model session. Current control must be ACTIVE, matching fresh ACK
RUNNING/effectiveON and current hard/soft leases. All independent risk/data/model
gates must pass. Then only this analysis response can report execution_authorized
true; no order is emitted. Existing control projection remains false. Local worker
must additionally enforce reviewed terminal identity/DEMO/broker mapping, quote,
one-position, cost, SL/TP and protection policy and consume each decision once.
No runtime adapter/config exists in this candidate, so actual responses remain false.
A truthy client flag or token never creates this authority.

## Response and errors

Successful protocol response exact fields (example is proposal-only):

```json
{"schema_version":1,"outcome":"PROPOSAL_READY","instrument":"BTC","model":"gpt-6.1-sol","reasoning":"medium","decision":{"decision":"BUY","reason":"Synthetic BTC-only proposal","invalidation":"Synthetic","stop_cents":5981000,"target_cents":6041000},"risk_state":"PASSED","execution_authorized":false,"checked_at":"UTC timestamp"}
```

risk_state PASSED only PROPOSAL_READY; otherwise BLOCKED. Decision object or null.
Outcome gates: VOLUME_BLOCKED/NEWS_RISK_BLOCKED/POLICY_BLOCKED/POSITION_OPEN/
COSTS_UNKNOWN/NOTIONAL_CAP_BLOCKED/MODEL_WAIT/SLTP_BLOCKED/LOSS_CAP_BLOCKED/
MODEL_RESULT_UNAVAILABLE/MODEL_PREFLIGHT_UNAVAILABLE/POST_MODEL_GATE_BLOCKED/
MODEL_ACCOUNTING_BLOCKED. All failures have execution_authorized=false.
Rejected transport/validation/auth returns only fixed outcome code under existing
control handling:404 disabled/host,401 invalid credential,400 cookie/query,
409 schema/scope/approval/evidence/operation/cap,413 size,415 JSON,429 rate,
503 schema/adapter/budget service exception. Responses no-store; no raw exceptions,
provider output, credential, account identifiers or arbitrary error messages.

## Provisioning handoff — not implemented, not authorized now

1. Review and release v2 additive schema and transport separately. No production
   migration has run. Do not upgrade existing read-only tokens. Use a separately
   authorized hash-only, short-lived owner/DEMO server/BTC session provisioner;
   no issuer/pair/exchange is supplied here. No credential was generated.
2. Owner must explicitly approve duration/max requests/per-trade loss/reviewed
   policy digest and paid-analysis budget. Inject immutable approval record for
   that exact session, lifetime<=300s, not a freely client-selected policy flag.
3. Review secure producer acceptance for the market/news/spec/latest-risk adapter:
   current DEMO identity, broker mapping, verified UTC/profile, trusted news provenance,
   complete costs and daily/cooldown/loss-streak facts. No price/news fabrication or
   diagnostic-capture promotion. Existing candidate +3h clock profile stays unverified.
4. Configure disabled-by-default analysis flag plus existing Trading AI flag only
   after explicit inference authorization. Keep OPENAI_API_KEY on server. Windows
   uses approved scoped transport only, no OpenAI key or inbound PC service.
5. Runtime still separately needs reviewed local worker policy/manifest and explicit
   runtime flag/authorization adapter. With those absent, false is intentional.
   OFF/expiry/revocation stop entries while existing approved protection continues.

This task changes code/tests/contracts only. No push, commit, deploy, production
migration, configuration, provider call, PC access, orders or new credentials.
