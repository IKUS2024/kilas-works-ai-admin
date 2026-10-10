# Read-only DEMO bridge — disabled code release review

Integrated onto final AI main `82732b2a325bfad872f34afcaf6937be80393abe`.
Owner approved deploying code/restarting the existing service; parent delegated
the serial push/deploy after this baseline became LIVE. Bridge activation,
production migration, real pairing/token issuance, MT5/NTP runs and owner-PC
access remain outside that approval. No branch is created. Existing risk/SL/
strategy, historical upload, analyst behavior and shared auth/Finance are unchanged.

## Implemented behavior

One manually started outbound-only collector feeds actual read-only telemetry
into an isolated bridge panel. Explicit pilot pairing scopes one-hour hashed
bearer to one user/bridge/server/symbol (GOLD or BTCUSD on XMGlobal-MT5 10).
Pairing is CSRF/session protected and expires after five minutes, single-use.
Collector secrets stay in memory; no cookie extraction, credential files, login
arguments, symbol/account switching, Windows service or order API. Before/after
SDK binding checks are local; broker-account attestation remains absent.

An exact bearer-only JSON handler for exchange/telemetry runs after the existing
host guard and before form CSRF. No global app/security/auth file changed; every
existing session endpoint retains CSRF. No Cookie/query authority in bearer
requests. Token scope/pilot, sequence, one-use 10-second server challenge, expiry,
revocation and rate limits are enforced transactionally. Only the latest bounded
market projection is stored; account totals/history/identifiers/specs are rejected.
No code/token/challenge is returned by status. Pairing secrets use no-store replies.

Bridge flag defaults false; schema is separately installed only by explicit
operator command/flag. Schema is not auto-applied by app or pairing. Exactly two
additive bridge tables; existing migration0087 unchanged. Per-worker request limit
is bounded defense, not a distributed anti-DDoS guarantee.

Transport CONNECTED <=6 seconds since receipt, STALE >6–15 seconds,
DISCONNECTED >15 seconds. Terminal failure clears market; nonadvancing quote is
labeled accordingly. UI polls only after pairing in a visible browser tab and
cannot resurrect stale status across revoke/pair. Raw epoch/UTC capture claims
are shown independently. Price updates do not claim verified freshness. Clock/
profile fields are producer claims; this collector sends null, no NTP or guessed
+3h normalization. Five-second worst-case qualifying source age requirement is
retained but NEVER granted by receipt/challenge. Independent clock/profile/
source verification and producer acceptance remain outstanding. All runtime,
AI, paper-from-feed and broker flags false; analysis.market_source remains None.
BTCUSD pairing does not change MOCK XAUUSD or caps. GOLD minimum notional remains
blocked above USD2000. Historical diagnostic/import code is not expanded.

## Validation

42 new integration/security methods PASS: actual Flask routes plus real loopback
urllib HTTP collector, synthetic SDK binding, CSRF/session/pilot/host isolation,
cookie/query rejection, hash-only one-use pairing, symbol/server/token scope,
expiry/re-pair/revoke, challenge/sequence replay, bounded rate/size/schema/decimals,
private-field rejection, no credentials in status/errors, heartbeat/stale/
disconnect, first/nonadvancing/backwards ticks, disabled/schema-unavailable behavior,
and zero inference/execution. Test-only identities/tokens/DB; no live credentials.

Existing Trading38, analyst17, observation15, diagnostic20, hosts4, producer14,
preflight13, AI unified24 PASS. Current AI project regression12 PASS/1 declared
skip. Total199 PASS/1 skip. Existing Trading browser MOCK/import flows and new
bridge browser actual pairing -> synthetic collector HTTP -> unverified quote ->
revoke PASS at1440/768/390/320 with no overflow/page errors. One final bridge
browser confirmation passed after stale-response suppression. JSON Schema and
workflow YAML valid; structural sample checks, Node syntax, git diff check PASS.
PostgreSQL18 was subsequently available through a disposable loopback-only Docker
container: Trading/analyst/observation70 and bridge42 PASS (112 methods). The
harness verified exactly two additional bridge tables, idempotence and old users
readback; its isolated schema and the QA container were removed afterwards.
Final integrated checks: the same199 methods PASS/1 declared skip in isolated
processes; owner live-QA budget17 PASS with disposable PostgreSQL, including its
PostgreSQL cases. Trading PostgreSQL112 methods and both browser suites PASS.
A one-process aggregate was unsuitable because legacy suites reuse the same
fixture identity; per-process reruns match the CI isolation and all pass. The
release gate requires green CI on the committed integrated SHA before deployment.

## Package for PC worker

Collector package is local, readable and ZIP-validated. Contains collector.py,
exact structural schema.json, operator README.md and SHA256SUMS, no private files.
ZIP SHA256: `90475f0d9a52b0c411b67e91717a3b1046fb0103e1c8b7d1789e31a2ebdeaccf`.
Path: `/workspace/trading-bridge-delivery-20261010/kilas-demo-bridge-v1.zip`.
Library save result is reported separately; never assume a Library item exists
from this local path. Consumer owns download/materialization in its own workspace.

Action-time approval still required for production migration/flag activation,
real pairing/token issuance and starting collector --connect. Owner explicitly approved deploying bridge code/restarting the existing service,
while activation and real pairing remain pending. Final AI release SHA has been supplied and verified before this integration. See package README for exact HTTP
contracts, values and operator flow. No further historical scaffolding proposed.

Library create succeeded: `kilas-demo-bridge-v1.zip`, library_file_id
`libfile_8dee861449e08191bb8090995016d4bb`, file_id
`file_00000000d9f48207b340cdb3caa65b03`, version0,9596 bytes.
The consumer must materialize this resolved Library item locally; do not assume
this executor path exists on the PC. Full metadata is preserved outside git.

Visual inspection found an inherited dark pairing hover. Fixed only in
.trading #trading-bridge; browser verifies computed light background/dark text.
No global theme or other product styles changed.

## Exact modified/new files

- `.github/workflows/kilas-trading-qa.yml`
- `client-hub/kilas_trading/bridge.py`
- `client-hub/kilas_trading/bridge_routes.py`
- `client-hub/kilas_trading/bridge_store.py`
- `client-hub/kilas_trading/routes.py`
- `client-hub/migrations/kilas_trading_bridge_v1_postgres.sql`
- `client-hub/migrations/kilas_trading_bridge_v1_sqlite.sql`
- `client-hub/static/kilas_trading.css`
- `client-hub/static/kilas_trading.js`
- `client-hub/static/kilas_trading_bridge.js`
- `client-hub/templates/kilas_trading.html`
- `client-hub/tests/test_kilas_trading_bridge.py`
- `client-hub/tests/test_kilas_trading_bridge_browser.py`
- `client-hub/tests/test_kilas_trading_postgres.py`
- `docs/KILAS_TRADING_DEMO_BRIDGE_REVIEW_20261010.md`
- `scripts/trading_demo_bridge/README.md`
- `scripts/trading_demo_bridge/collector.py`
- `scripts/trading_demo_bridge/schema.json`

## Security review before serial release

Closed two time edge cases: UTC acquisition must be positive and <=2 seconds
in addition to matching monotonic duration; a future server receipt is now
DISCONNECTED/SERVER_CLOCK_DISCONTINUITY instead of being clamped to age zero.
Pair code/token/challenge are not valid before their server issuance window.
Six additional regression methods cover these time cases and simultaneous
exchange/duplicate telemetry; exactly one request consumes each credential or
challenge on both SQLite and PostgreSQL. No freshness/profile trust was granted.

No changes to app.py/security.py, Finance, analyst, observation, engine, store
or existing schema0087. Dedicated bearer authorization is confined to the two
new endpoints after the existing host guard; other requests retain session/CSRF.
Native integrated checks are complete. Release keeps `KILAS_TRADING_BRIDGE_ENABLED`
OFF and does not apply the separately gated production bridge migration. Existing
AI live/transcription/owner-QA flags stay OFF, content projects ON and demos OFF;
this release does not modify environment variables.
The Library collector ZIP/code/schema remain the previously verified artifact;
its initial test notes predate this additional backend security/PG review.
