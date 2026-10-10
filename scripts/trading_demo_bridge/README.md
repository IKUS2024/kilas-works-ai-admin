# Kilas read-only DEMO outbound collector v1

Base collector released at 557a084; terminal-binding patch pending serial review.
Server bridge remains disabled; this package
does not install a Windows service, create credentials, log in to another MT5
account, select another broker symbol, enable Algo Trading, or execute orders.
The only SDK operations are initialize/shutdown and account_info, terminal_info,
symbol_info, symbol_info_tick, copy_rates_from_pos. Account identity is compared
in memory only; account totals, credentials, positions and history never leave
the PC. No account IDs are included in telemetry. Token and code are memory-only.

## Operator flow, after separate action-time approval

1. Release review first: backend migration/install and service flag activation
   require owner/parent approval. Bridge code was released; migration/activation
   and this collector correction remain separately gated.
   Server operator installs only kilas_trading_bridge_v1 via the explicit
   KILAS_TRADING_BRIDGE_SCHEMA_APPLY=true command and enables
   KILAS_TRADING_BRIDGE_ENABLED=true only when approved. This is separate from
   existing Trading/schema flags. Feature defaults disabled; no automatic schema
   creation, bridge transport, pairing or credentials at startup.
2. Use the already reviewed Windows Python environment with the existing MT5
   SDK, same DEMO terminal/server XMGlobal-MT5 10, selected visible GOLD or BTCUSD.
   Supply the exact approved terminal executable and terminal data-directory paths
   using --terminal-path and --terminal-data-path. Neither is discovered or guessed.
   Before --connect, the local operator must confirm that the intended terminal
   process is already running. In Windows Task Manager > Details, inspect that
   process's executable location locally and match it to the approved EXE path;
   confirm its open terminal is on the intended DEMO/server and its Open Data Folder
   matches the approved data-directory path. Do not copy process/account details
   into telemetry or repository files. If absent, ambiguous or mismatched, stop;
   do not use this collector to launch, discover or switch terminals. This manual
   prerequisite does not add PID attestation or prevent the SDK launching a process
   if the terminal exits between the operator check and initialize.
   Initialization passes that EXE explicitly and timeout=5000 milliseconds, without
   login/password/server/portable parameters. Windows checks both paths exist before
   importing the SDK. MT5 may launch that executable if needed; initialization still
   requires action-time connection approval. There is no sdk.login call or credential
   argument; initialize may use the last saved account per the SDK documentation.
   The collector validates DEMO/server/binding and never requests account switching.
   Keep external Python trading disabled. Do not change account or symbol to
   get around a failed check. This package does not install dependencies.
3. Offline check: `python collector.py --symbol GOLD` exits without importing
   MT5 or making HTTP requests. Inspect SHA256SUMS before use.
4. When explicitly authorized to connect, sign in on https://trading.kilasworks.id,
   open Bridge DEMO, choose exactly one symbol and create pairing. Paste the
   one-use code only into the approved local foreground collector:
   `python collector.py --symbol GOLD --terminal-path "<approved terminal EXE>" --terminal-data-path "<approved terminal data directory>" --connect --minutes 5`
   Replace the two placeholders with the reviewed local paths; do not copy them
   into reports, repository files or telemetry. Missing/relative/UNC/device paths,
   traversal, alternate data streams and nonterminal executable names fail closed.
   Substitute BTCUSD only if that exact symbol/server was paired and is already
   selected/visible on the same DEMO terminal. Code is entered with getpass,
   never command-line arguments or a token file. Pairing expires after 5 minutes.
5. Observe transport, terminal declaration and market-time verification separately.
   Raw prices/candles arriving do not authorize AI, paper-from-feed or orders.
   Ctrl+C stops; token is cleared, SDK shutdown attempted, no automatic retry.
   Revoke in dashboard invalidates the token and clears the displayed market.
   Token expires after 1 hour maximum, without automatic refresh. Foreground
   run is bounded to 1–60 minutes; default 5. No persistent service/credential.

No connection is started without --connect. The service URL is fixed HTTPS;
there are no redirects, cookies, arbitrary URLs or automatic proxy credential
discovery. A proxy-only network may fail; do not alter firewall or bypass it.

## Terminal binding and Python trading gate

The reported terminal installation directory must equal the pinned executable's
parent, and terminal data_path must match the separately pinned data directory.
Installation/data/common-data paths, build, name and company stay bound in process
memory, checked around account/symbol/tick/bar reads. A change stops before emitting
market data. Account DEMO mode, exact server and stable local account identity are
still required. Paths/account identity are never sent or printed. This is SDK
identity checking, not OS PID/process attestation or cryptographic broker proof.
The 5000ms timeout is the SDK connection timeout, not an external native-process
watchdog; no real Windows timeout/terminal capture was run for this patch.

tradeapi_disabled=True means the terminal's external-Python trading prohibition.
Algo Trading/trade_allowed=False is a separate state and does not imply that flag.
Official MetaQuotes docs describe the Python prohibition blocking trading calls;
it does not prohibit read-only quotes/account/terminal information. Therefore this
gate is defense in depth, not a technical prerequisite of this collector's read
allowlist. We retain it without an override. The SDK allowlist remains exactly
initialize/shutdown/terminal_info/account_info/symbol_info/symbol_info_tick/
copy_rates_from_pos; no trading/order/history APIs or setting changes are added.

Recommended action-time option: owner explicitly approves checking/enabling
"Disable automatic trading via external Python API" in the intended terminal,
while keeping Algo Trading off. This changes a terminal-wide setting and may
affect other Python trading scripts; the collector never makes that change.
Alternative, not implemented: owner-approved policy change to allow read-only
collection with the Python prohibition unset, relying on the execution-free call
allowlist. It removes an independent trading barrier and requires separate review
and authorization. Do not switch settings or bypass the retained gate to connect.

Sources: [initialize](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py),
[terminal_info](https://www.mql5.com/en/docs/python_metatrader5/mt5terminalinfo_py),
[terminal path properties](https://www.mql5.com/en/docs/constants/environment_state/terminalstatus),
[Python trading prohibition](https://www.mql5.com/en/book/advanced/python/python_install).

## Exact HTTP contract

Base: https://trading.kilasworks.id/products/services/trading/bridge
Transport is JSON UTF-8, <=16384 bytes, no query strings or Cookie header.
No secret in URL. Responses Cache-Control:no-store. Schema rejects extra and
duplicate keys, nonfinite numbers, invalid size/type/value and execution claims.

- POST /pair: existing pilot session + CSRF; exact {symbol,server} JSON with
  X-CSRF-Token, or those fields plus csrf_token as multipart form. Returns
  {pair_code,bridge_id,expires_at,symbol,server}. Pair code 32 lowercase hex chars,
  128-bit random, single-use, 5-minute expiry. One new pairing per 30 seconds;
  re-pair immediately invalidates the old token and market snapshot.
- POST /exchange: no cookie/Authorization; exact {pair_code,symbol,server}.
  Pairing's server is exactly XMGlobal-MT5 10, symbol GOLD or BTCUSD. Returns
  {token,expires_at,challenge,challenge_expires_at,sequence:0,symbol,server}.
  Token 64 lowercase hex chars, 256-bit random, expiry 1 hour. Stored server-side
  only as SHA256 digest, scoped to pilot user, bridge, server and symbol.
- POST /telemetry: Authorization:Bearer <token>; exact payload in schema.json.
  Sequence equals previous+1; server_challenge equals issued challenge. Challenge
  64 hex chars is single-use, expires in 10 seconds; each valid message rotates
  it. At least 1 second between messages. Response {outcome:RECEIVED_READ_ONLY,
  sequence,challenge,challenge_expires_at,runtime_eligible:false,
  broker_execution_allowed:false,ai_analysis:false,paper_execution:false}.
- GET /status: existing pilot session. No token authority to read dashboard.
  Sanitized latest market/status only, never code/token/challenge or account ID.
- POST /revoke: existing pilot session + CSRF; {} JSON or csrf_token-only form.
  Clears credential hashes and market; response {outcome:REVOKED}.

Error responses fixed {outcome:<code>}: 400 cookie/query rejected, 401 credential/
scope invalid or revoked, 409 payload/replay/expired challenge, 413 size, 415
wrong content type, 429 rate limit, 503 schema/storage unavailable, 404 disabled
or wrong host/pilot. Do not automatically retry uncertain requests. Exchange and
telemetry are handled only by isolated bearer middleware ahead of form CSRF;
host guard still runs first. All existing CSRF/auth endpoints remain unchanged.
Per-worker request abuse limit 60/minute per remote IP, bounded to 1024 IP keys;
not a distributed anti-DDoS service. Scope/sequence/rate/challenge/token mutations
are serialized with DB transactions across workers. One bridge/snapshot per pilot.

## Telemetry and source qualifications

MARKET requires terminal_connected:true, account_mode:DEMO, selected symbol,
M1, exactly 12 contiguous positive raw OHLC bars ending before the raw tick,
and a <=2 second acquisition whose UTC elapsed/monotonic interval differ <=50ms.
Tick integer time/time_msc must agree. Bid/ask and OHLC are bounded positive
decimal strings; ask>=bid and low<=open/close<=high. Raw candle times are minute
aligned; final candle close trails raw tick by <60 seconds. Cross-field arithmetic
is checked by backend beyond structural JSON Schema. HEARTBEAT requires
market:null; collector uses UNKNOWN/disconnected on terminal read failure and
then stops. SDK DEMO/server/local identity are rechecked before/after each read.

Clock and clock_profile are null in this collector. Optional bounded clock
metadata/profile summary is only a producer claim; neither an approved broker
profile nor independently verified NTP. Full constructed clock_profile/windows
and raw clock packets are NOT this schema. No server-side trusted profile exists
in this release. No timezone subtraction or normalization is inferred.

Heartbeat/market every ~2 seconds. Receipt <=6s: transport CONNECTED; >6s–15s:
STALE; >15s: DISCONNECTED. Terminal failure clears the market. Identical time_msc
is NONADVANCING_OR_FIRST_OBSERVATION; decreasing time_msc rejects. An advancing
tick is still UNVERIFIED_CLOCK_PROFILE. A late challenge requires manual re-pair.
Status response includes source_max_age_seconds:5. The unchanged qualifying
freshness requirement is worst-case source age plus clock uncertainty <=5s;
recent receipt/challenge/capture claims cannot prove it. Fresh qualification is
never granted here because trusted source-time evidence remains absent.

All runtime, AI, paper-from-feed and broker gates remain false; analyst source
remains None. Existing upload contract 8192 bytes, diagnostic browser import,
MOCK paper controls, cap USD2000 and risk/SL/strategy are unchanged. Pairing BTCUSD
does not change the paper XAUUSD instrument or authorize different risk settings.
Minimum GOLD .01 lot above cap remains separately BLOCKED. Transport telemetry
is an operational connection, not independent broker attestation/readiness.

## Verification and release handoff

36 synthetic HTTP/security integration tests passed, including real loopback
urllib->Flask transport and fake SDK bindings. Browser pairing/collector/revoke
passed at 1440/768/390/320; existing MOCK/import responsive suite also passed.
No real MT5/NTP or production tokens were used. PostgreSQL CI harness includes
the bridge suite and verifies only two additive bridge tables; native PostgreSQL
is not available locally and remains a release check. See repo review notes for
final regression counts and exact files. This package contains no private report.
