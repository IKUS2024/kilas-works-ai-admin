# GOLD DEMO observation upload — v1

## Destination and authentication

UI: `https://app.kilasworks.id/products/services/trading`, section **Observasi market · unggahan DEMO**. Use the owner's existing verified `irvankarnavi@gmail.com` login; choose the market-only JSON file and click **Unggah observasi DEMO**. Other owner/admin accounts receive 404. No new token, grant or persistent exporter bridge exists. This executor does not operate the owner's PC or hold their production browser session.

Endpoint: `POST /products/services/trading/observations/upload`, HTTPS, `multipart/form-data`, exactly one file part named `observation`, optional form field `csrf_token` carrying the existing session's CSRF token (or existing `X-CSRF-Token` header). Existing cookies/authentication and CSRF checks are required. No JSON-body, arbitrary URL, account sync or unauthenticated upload endpoint. Do not copy cookies, tokens or passwords into chat. Prefer the owner's existing browser upload instead of manufacturing credentials for an exporter.

With `Accept: application/json`, success returns HTTP200 `{outcome:"OK", message:..., duplicate:false|true, ai_analysis:false, paper_execution:false}`. Validation/rate/disabled returns409; oversized request413; missing CSRF400; nonpilot404; logged-out request rejected by existing auth/CSRF policy; uncertain storage503. Normal browser form submission uses303 back to Trading and a flash message. Re-uploading the identical validated file is idempotent.

## Exact file schema

UTF-8 JSON object, no BOM, duplicate keys, nonfinite JSON numbers or extra fields. File size 1–8192 bytes; total multipart request ≤16384 bytes. Filename is ignored and no file is saved on disk. Required fields:

| Field | Type and boundary |
| --- | --- |
| `schema_version` | integer `1` (not boolean/string) |
| `kind` | string `DEMO`, declared by the exporter; the app cannot independently verify terminal account mode |
| `source_symbol` | exact string `GOLD`; canonical mapping remains unknown |
| `bid`, `ask` | decimal strings ≤24 characters, finite positive ≤100000000, ask ≥ bid; use fixed decimal notation |
| `time` | original tick integer seconds, >0 and <10^15; do not convert timezone |
| `time_msc` | original tick integer milliseconds, >0 and <10^15; `time_msc // 1000 == time` |
| `observed_at_utc` | ISO timestamp with explicit zero UTC offset (`Z` or `+00:00`), ≤40 characters; record the PC's separately verified UTC observation clock, not the tick epoch |

Optional fields must appear together: `timeframe` is `M1`, `M5` or `M15`; `candles` has 1–48 objects with exactly `time`, `open`, `high`, `low`, `close`. Candle `time` is the untouched integer epoch (same range); bars must be ascending at the selected 60/300/900-second interval. OHLC are positive fixed decimal strings ≤24 characters with ≤8 decimal places and ≤100000000; low ≤ all values, high ≥ all values. Do not reinterpret candle epoch as UTC or claim a bar is closed. Candle time semantics remain unverified.

The following illustrates types with **synthetic documentation values**, not verified XM prices/time. The local worker must export actual allowlisted DEMO observations, not this example:

```json
{
  "schema_version": 1,
  "kind": "DEMO",
  "source_symbol": "GOLD",
  "bid": "2500.10",
  "ask": "2500.30",
  "time": 1791298800,
  "time_msc": 1791298800123,
  "observed_at_utc": "2026-10-06T12:00:00+00:00",
  "timeframe": "M1",
  "candles": [
    {"time": 1791298740, "open": "2500.00", "high": "2501.00", "low": "2499.00", "close": "2500.20"}
  ]
}
```

Only prices, raw market times and the observation UTC receipt clock are allowed. Exclude account numbers/IDs/names, terminal paths, balances, equity, margin, positions, orders, passwords, tokens, logs and broker telemetry. Do not upload a REAL-account export. Extra fields are rejected at every object level. Exporting only these market fields is the local worker's task; do not read/serialize the whole MT5 account/terminal object. This release does not initiate any PC export or actual upload.

## Server state and retention

Every accepted snapshot is permanently observation-only: `event_time_utc=null`, `source_time_status=unverified`, `freshness=unknown`, `canonical_symbol=null`, `mapping_status=unknown`, `candle_time_semantics=unverified`, `ai_analysis=false`, `paper_execution=false`. The server adds `received_at_utc` independently. Neither receipt clock proves quote freshness. There is no three-hour correction, inferred offset or GOLD alias. The existing analyst rejects this shape and its market source remains unavailable. Order endpoints reject observation input. Existing synthetic MOCK replay is separate and still usable.

One latest snapshot per pilot is stored in the existing Trader events table at action `MARKET_OBSERVATION`, operation key `market-observation-current-v1`. A new upload replaces that snapshot after ≥30 seconds; identical retries do not write another row. This is latest-upload storage, not historical tick audit/streaming or necessarily the latest market tick. Replaced snapshot contents are not retained by this feature; normal platform backups are unchanged. Account lock serializes concurrent uploads; ownership/feature gates are rechecked in the transaction. No migration, Finance write or shared AI usage mutation.

`KILAS_TRADING_OBSERVATION_ENABLED=false` disables upload and its button. Default enabled for this explicitly authorized deployment; disabling does not erase the last observation. `KILAS_TRADING_ENABLED=false` hides the entire pilot feature. Code rollback is the prior deployed `f5a40445c0ca9cb988b705c24b68aae75e213af4`; preserve the one observation row/additive Trader tables, no destructive SQL needed.

## Verification and next phase

Local PASS: 70 SQLite and 70 disposable PostgreSQL18 tests (including concurrent/idempotent uploads, retention/rate, permissions, CSRF, private-field and malformed/candle/size rejection, no provider calls/orders); functional paper browser at1440/768/390/320 and real local file-upload flow at1440/320 with unknown-time state and disabled AI; Finance16, foundation28, Assist9 and AI24 regressions. No actual owner data, paid model call or production test order/upload used. Remote CI/Render evidence is recorded separately after deployment. The executor cannot claim signed-in production browser acceptance.

Owner's Connect/Disconnect and automatic-analysis/entry requirement is recorded for a **future phase**, not implemented here: Connect/Disconnect controls data connection; separate Start/Pause AI explicitly arms bounded analysis and DEMO/paper automation; WAIT is valid and trades are never forced. Disconnect does not close positions; show loss-of-management warning and preserve existing protective stops. No always-on bridge, inference or order execution is enabled by this release. Authoritative source clock/DST semantics, instrument mapping, secure connection design and project model availability/budget gates still block that next phase. Real-money/broker order authorization is absent.
