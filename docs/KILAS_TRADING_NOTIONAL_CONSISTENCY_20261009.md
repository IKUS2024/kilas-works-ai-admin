# Offline notional consistency acceptance and combined review

Base: `810c8419740ec4c2d8de45f145e2d14137078142`. This continuation retains the preceding exact-decimal changes and adds one offline arithmetic acceptance check. All changes are local and uncommitted. No SDK/broker network/order calls, paid inference, strategy/risk edits, push or deployment.

## Capability and strict input contract

`parseNotionalFacts(utf8JsonText)` is a pure offline helper exported only for the existing Node test harness. It shares the report reader's 128 KiB, nesting/value-count, duplicate-key and prototype-key protections. It does not create an endpoint, UI upload form, storage slot, broker adapter or connection.

The root must contain **exactly** `schema`, `input_kind`, `units`, `specs`, `quote`, `scenarios`, `notional_cap_usd`. No private fields or capability claims are accepted.

| Field/object | Required contract |
| --- | --- |
| `schema` | `kilas-offline-notional-facts-v1` |
| `input_kind` | `SYNTHETIC_TEST_FACTS` or `HISTORICAL_DECLARED_FACTS`; neither proves broker origin |
| `units.quote_currency` | `USD` |
| `units.price_unit` | `USD_PER_TROY_OUNCE` |
| `units.contract_unit` | `TROY_OUNCES_PER_LOT` |
| `units.volume_step_origin` | `ZERO_MULTIPLES` only; other lot grids unsupported |
| `specs` | Exactly `currency_profit=USD`, `trade_contract_size`, `volume_min`, `volume_step`, `volume_max` |
| `quote` | Exactly positive `bid`, `ask`, with ask ≥ bid |
| `notional_cap_usd` | Positive decimal string exactly equal to `2000` |
| `scenarios` | One or two distinct BUY/SELL records, exactly `direction`, `volume_lots`, `notional_usd`, `cap_status`, `hypothetical=true`, `account_sizing_applied=false` |

All numeric facts are positive decimal strings: one to nine whole digits and up to eight fractional places; numeric JSON values, missing facts, zero, signs, exponent notation, nonfinite values, suffixes and excess precision are rejected. Specs require minimum ≤ maximum and both bounds aligned to the explicit zero-origin step. Every scenario quantity must be within those bounds and be an exact step multiple. Nothing is rounded onto the grid.

Gross hypothetical notional = volume lots × contract troy ounces per lot × price USD per troy ounce. BUY uses ask; SELL uses bid. The product must be exactly representable within eight fractional places and nine whole digits; rounding, overflow and precision loss are rejected. Derived and reported notionals must match exactly, and the reported status must match the unchanged USD2000 cap. Minimum-volume notionals for both directions are calculated separately. This is gross notional, not margin, SL risk, P&L or execution costs.

Successful output is `ARITHMETIC_CONSISTENT_ONLY`, containing allowlisted derived decimal strings and fixed ineligible gates: source `NOT_INDEPENDENTLY_VERIFIED`, freshness `NOT_EVALUATED`, producer `NOT_IMPLEMENTED`, policy replay only, and runtime/broker/AI/paper all false. Within-cap arithmetic grants no permission.

## Optional historical-report extension and actual compatibility

A risk record may include a new explicit reader/adapter metadata object `notional_units`, with exactly the four `units` fields above. This is **not an existing broker SDK field or asserted broker evidence**. If present, the report parser projects only the five selected existing `specs` fields, bid/ask, and six scenario fields into the strict checker. Missing, ambiguous, incompatible or inconsistent selected facts reject that report. Other report fields remain discarded, including private quote/spec additions.

If `notional_units` is absent, existing v1 reports remain viewable but the new consistency outcome is `NOT_EVALUATED_MISSING_UNITS`; no derivation or lot-grid acceptance is claimed. No units are inferred from GOLD, profit currency, tick value, synthetic engine constants or reported contract size.

Actual Library text was read in memory through supported text access and parsed with the final combined code. The supplied historical report is still accepted: BUY0.01 / USD4188.55 and SELL0.01 / USD4188.02 are BLOCKED, with cap USD2000. Its selected specs contain contract size/min/step/max and USD profit currency, but no explicit unit declaration. Therefore its consistency remains `NOT_EVALUATED_MISSING_UNITS` and every runtime/execution gate stays false. No real-report incompatibility found. Private content was not materialized, committed, uploaded to the application or retained as a fixture. This is text/schema compatibility, not byte/hash authenticity verification.

## Final tests and combined self-review

Final **94 test methods PASS, zero outstanding failures**: diagnostic/decimal/notional20, Trading38, analysis17, observation15, host-isolation4. Responsive browser suite also PASS at 1440/768/390/320: legacy missing-unit disclosure, exact cap boundary, synthetic explicit-unit derivation, invalid-step rejection, no imported private fields, zero import requests, unchanged Trading state, disabled broker/AI controls, clear/reload/rejection and all existing MOCK flows. JavaScript syntax and `git diff --check` PASS.

Initial oracle fixture run had six subcase errors: Python multiplication serialized more than eight fractional places because of redundant trailing zeros, and the strict parser correctly rejected those strings. The fixtures were canonicalized without changing their exact mathematical values. The final parser suite passes; over-precision rejection remains separately covered. No production code was loosened to make the fixtures pass.

Logs: `/tmp/trading-notional-focused.log`, `/tmp/trading-notional-browser.log`, `/tmp/notional-test_kilas_trading.py.log`, `/tmp/notional-test_kilas_trading_analysis.py.log`, `/tmp/notional-test_kilas_trading_observation.py.log`, `/tmp/trading-notional-hosts.log`.

Combined review findings:

- False acceptance: exact integer arithmetic avoids float rounding; duplicate fields, malformed/missing/ambiguous facts, wrong currency/grid/direction, mismatched notionals/statuses, unsupported product precision and private/capability claims are rejected. Even a perfectly consistent forged or synthetic payload cannot set eligibility.
- Backward compatibility: actual v1 report passes without fabricated units; its risk claims stay historical and explicitly unevaluated for arithmetic consistency. Numeric money/lot scalars are intentionally no longer accepted by the preceding decimal patch. Projection risk amounts are strings, consumed only by the local reader. The server market-only 8 KiB contract is unchanged.
- Privacy: new helpers are pure and perform no IO. Browser rendering uses text nodes; only fixed enums, bounded canonical numbers and derived values survive projection. No credential, account, balance, server/session, history or raw packet retention. No server route, auth/CSRF/tenant change or service upload.
- Safeguards: minimum GOLD remains above unchanged cap; broker/clock/profile/freshness verification remains absent, producer acceptance unimplemented, all execution disabled. Strategy, SL, risk limits, MOCK and other products untouched.

## Stop point

The bounded consistency deliverable is complete. A future phase needs independently reviewed unit/contract/lot/quote evidence and an approved adapter mapping before any actual broker acceptance claim. Do not append guessed unit metadata to the real report. Broker writes, SDK connections and runtime activation remain outside current authorization. Any later release requires cache-version review and applicable CI; no release is performed here. Parent decides the next phase; this task starts none automatically.
