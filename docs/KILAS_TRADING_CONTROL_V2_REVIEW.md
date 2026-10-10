# Historical control v2 design proposal

This proposal is retained as design history. The implemented disabled candidate is
described by `KILAS_TRADING_CONTROL_CONTRACT_V2.md`; the implementation and test
evidence supersede references below to v1-only code or missing v2 implementation.

The tested, disabled v1 implementation remains unchanged. Its 30-second `expires_at`
currently limits the whole ON run; it is not yet a bounded-autonomous-run interface.
Do not ship v1 as that interface or have a worker silently reinterpret `expires_at`.
This document proposes precise v2 changes for review; no route, credential, production
migration or execution is created by it.

## Exact current v1 constraints

Paths under `/products/services/trading`; status GET uses existing authenticated pilot
session; desired POST adds global CSRF; sync POST uses only separately approved
DEMO_CONTROL_COORDINATION_V1 scope, never read-only bearer/cookie authority.
- schema_version: integer 1, not bool/string. Extra/missing fields rejected.
- desired_state: ON | OFF; instrument: GOLD | BTC (display keys, not broker aliases).
- actual_state input: OFF | PROTECTING | RUNNING | BLOCKED. UNKNOWN is output only.
- account_mode: DEMO | UNKNOWN. REAL rejected, never normalized to DEMO.
- policy_state: UNSET | READY | BLOCKED.
- wait_reason input: NONE | MODEL_UNAVAILABLE | STRATEGY_UNAVAILABLE |
  NEWS_UNVERIFIED | RISK_BLOCKED | DEMO_UNVERIFIED | TRANSPORT_UNAVAILABLE.
  Additional output-only reasons: CONTROL_DISABLED | WORKER_OFFLINE.
- terminal_connected, position_open, protection_active, specs_verified, risk_allowed:
  strict JSON booleans, not 0/1/string/null.
- command_id: exactly 32 lowercase hex; nullable only in bootstrap acknowledgment/
  projection. Known prior receipt ID+revision may be acknowledged to pull newer intent.
- expected_revision: integer 0 <= n < 2^63-2. ACK revision integer 0..current revision.
- sequence: integer 0 <= n < 2^63; bootstrap 0 once/session, thereafter exact previous+1.
- challenge: null only bootstrap; otherwise exactly 64 lowercase hex, one use, <10s.
- bearer: exactly 64 lowercase hex; control-scoped hash only, not existing read-only hash.
  Control scope lifetime at most 1800 seconds; revoked/expired/future-created invalid.
- lot: string matching `[0-9]{1,9}(\.[0-9]{1,8})?`, >=0.01 and <=100000000,
  exactly canonical Decimal fixed notation. No signs/exponents/leading/trailing spaces,
  leading zeros, redundant trailing fractional zeros or numeric JSON type. `0.01`,
  `0.1`, `1` accepted grammatically; `0.010`, `1.0`, `01`, `1e-2` rejected.
  This is a parsing bound, NOT accepted broker volume/risk. Approved min/max/step,
  contract/notional/SL/risk gates remain separately required; no limit is relaxed.
- UTF-8 JSON object, duplicate/prototype keys and NaN/Infinity rejected; 8192-byte limit.
  Worker forbids cookies/query. JSON Content-Type required. Desired forbids query too.
- Freshness <=6s (negative age invalid). Initial v1 command lease 30s, duplicate/sync
  never extends it. Min worker sync interval 1s, recommended 2s; bounded shared rate.
- Open managed position requires protection_active=true and PROTECTING/RUNNING.
  RUNNING requires DEMO, connected, READY, specs/risk true, wait NONE and applicable ON
  lease. Current projection additionally requires latest matching ack. Historical ack
  never projects current RUNNING. Unsafe authenticated ack consumes/fences challenge.
- configuration change requires fresh current OFF+flat acknowledgment; protecting,
  running, stale/unknown locks instrument and lot. No blind queue or position migration.
- execution_authorized is always false. Server coordinates intent, not broker permission.

## Proposed v2: bounded autonomous run plus renewable short transport lease

Version bump to schema_version=2 prevents v1 worker timestamp reinterpretation.
New dedicated scope proposed: DEMO_BOUNDED_RUN_COORDINATION_V2; do not relabel an
existing token or grant it additional authority. Provisioning requires separate review.

An owner approval manifest must specify max_run_seconds and session expiry. No such
execution-duration approval is manufactured here. Proposed engineering ceiling is
300s (five minutes), not evidence that five minutes of execution is currently approved.
Missing approved cap/policy keeps ON blocked. An approved smaller cap always wins.

Desired v2 request, same owner/CSRF endpoint (only after reviewed v2 implementation):

```json
{"schema_version":2,"command_id":"32 lowercase hex","expected_revision":0,"desired_state":"ON","instrument":"BTC","lot":"0.01","run_seconds":300}
```

run_seconds strict integer; ON: 1..min(approved cap,300), OFF: exactly 0.
Reject insufficient scope lifetime rather than silently shorten the requested run.
ON starts its hard owner-intent deadline at acceptance, NOT first worker ACK: time
spent awaiting pickup consumes the duration and cannot become an indefinitely queued run.
Require fresh current worker readiness and safe configuration before acceptance.
A re-issued ON cannot restart/extend an active run. Exact duplicate is idempotent.
Only a new explicit owner command after a confirmed safe stop may start another run.

V2 status/desired/sync retain v1 non-time projection fields. Replace v1 expires_at with:
- command_expires_at: min(issued_at+30s,run_expires_at). Initial pickup deadline only.
- run_seconds: accepted owner-approved duration (0 when OFF).
- run_expires_at: fixed issued_at+run_seconds, also bounded by scope/approval expiry.
- worker_lease_expires_at: min(last valid sync+6s,run_expires_at,scope expiry).
- run_status: NONE | PENDING | ACTIVE | ENDED. ENDED is latched and not revived by sync.

No v2 `expires_at` compatibility alias: workers must migrate explicitly.
First current RUNNING ACK must arrive before command_expires_at. After pickup,
passing this delivery timestamp does NOT end the acknowledged run. Hard run deadline
and short worker lease govern it. Sync never extends command pickup, run or scope expiry.

Worker sync request keeps the exact v1 ack field set, with schema_version=2; response
adds the new time/run fields plus the same challenge/sequence/outcome. API intent still
is not broker execution authorization; no inference/signals/orders are added by it.
Owner-approved local runtime policy remains a separate necessary authority.

Transport renewal is the existing ~2s sync: valid current-scope, current-revision ACK
renews worker_lease_expires_at by at most 6s, capped by immutable hard deadline.
This is NOT another ON, entry signal, order or scope renewal. There is no automatic
owner/run renewal endpoint and no browser heartbeat extending a run.

Browser closure is not loss of the explicit bounded owner authorization. Worker must
still verify the latest owner intent through sync. OFF/revision change, missing/uncertain
intent, disabled API, revocation, scope/run expiry, negative clock age or missed short
worker lease immediately stops entries. A missed lease latches ENDED: reconnect/sync
cannot resume the old run. A new explicit owner command and safe fresh OFF/flat state
are required; no queue/replay/restart of persisted ON. Duplicate old IDs cannot renew.

Worker computes monotonic deadlines from response timestamp differences minus full
request latency (never extend deadlines because of local wall-clock changes).
At latest known worker_lease deadline stop entries even if a response is pending;
continue approved protection/exits. New valid response may update a still-live soft
lease but never resurrect one already missed. Server must enforce the same gap fence
before processing incoming ack, not refresh away an observed >6s gap.

Model/strategy/news temporarily unavailable reports BLOCKED (flat) or PROTECTING,
with its fixed wait reason, and no entries/RUNNING. Heartbeats may keep transport
live inside the unchanged hard run deadline; unavailable policy never renews entry
permission. Resuming evaluation requires current validated policy/analysis/news,
not cached stale model output. Astra/news execution is separate from this design.

## Code-only short-lived provisioning design (not implemented/registered)

Future reviewed owner workflow may introduce separate `/control/pair` and
`/control/exchange`; neither is available now. Existing read-only `/bridge/*` is
unchanged and cannot grant control or execution scope.

1. Approval manifest binds current verified owner identity, exact DEMO server,
   logical instrument, broker mapping-verification requirement, reviewed local
   runtime/risk policy version, approved max_run_seconds and session expiry.
   Undefined policy/cap or REAL account never qualifies. Manifest is authority,
   not a freely client-selected flag. No accountnumber/balance/history.
2. Explicit owner session+CSRF action after approval creates a new one-use pairing
   code (<=120s), stores only its hash/approved scope. Idempotent pairing action ID
   avoids duplicate grants. Never convert/copy a read-only token or existing scope.
3. Manually started local worker verifies pinned DEMO terminal/server locally and
   enters code through protected getpass with no echo fallback; fixed TLS URL,
   no redirects or arbitrary URL configuration, no raw account metadata uploaded.
4. One-use exchange atomically consumes code and returns a freshly generated scoped
   token (max30min, bounded by approval) once; server retains hash only. Token held
   in worker memory; no local file, browser storage, startup service, registry task,
   scheduler or refresh token. No automatic renewal/repair/re-pair.
5. New session atomically revokes prior control grant and fences intent OFF; emits
   no order or execution authorization. Owner revoke/expiry likewise fences entries.
   Protection remains local and must not depend on keeping this credential alive.

No pairing/exchange handler, issuer, CLI provisioning command or secret is created
by this design task. Adoption and issuance require separate review and authorization.

## Migration / failure / recovery plan (no production action now)

- Keep feature disabled and bridge OFF. No on-boot/request migration or provisioning.
- Preserve immutable v1 SQL and recorded checksum if installed anywhere. V2 must be a
  new forward migration/ledger name, never edit an applied v1 checksum or stamp drift.
- Future approved preflight checks prerequisites, ledger/checksum and expected columns
  read-only. Missing base bridge schema, partial untracked tables or shape drift is a
  blocker; do not silently bless existing tables via IF NOT EXISTS or delete evidence.
- After separate authorization, apply required migrations in dependency order using
  the existing transaction/advisory-lock pattern. Validate shape/constraints and then
  record checksum in the same transaction. No secret/data dump or account data migration.
- DDL/validation/checksum failure rolls back transaction. Flag stays OFF, no scope
  issuance. Fix via a reviewed forward repair; do not reset ledger or trading data.
- If later runtime release fails, disable control first, revoke its short-lived scopes
  through the approved owner/operator route, and stop entries locally while preserving
  protection. Roll back app code as reviewed; additive schema/receipts may remain
  inert. No destructive drop of history, positions, approved risk data or shared tables.
- Replay recovery requires fresh approved scope, OFF bootstrap, safe OFF/flat ack and
  new explicit command. Do not restore raw token, persist ON or replay old receipts.

Review blockers: approved run cap/manifest, v2 implementation/testing, scoped issuer
review/authorization, manual release plan, and local runtime-policy integration.
Current v1 tests remain evidence for v1 only, not proof of the proposed v2 run semantics.
