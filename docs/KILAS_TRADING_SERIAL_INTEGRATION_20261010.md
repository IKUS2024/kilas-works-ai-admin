# Trading serial integration review — October 10, 2026

Integrated the preserved Trading patch onto verified AI release
`aa06a7edb6cc142776dce1b6dc1400b81342320f` by fast-forward, with no conflict or
changes to AI, Finance, shared auth, broker runtime or strategy. Owner explicitly
authorized serial commit/push, CI verification and release to the existing
Render service after the AI release. No branch creation or force update.

Browser diagnostics remain local, bounded to 128 KiB and extracted through the
existing safe parser. Exact decimal comparisons prevent rounded USD2000 cap
acceptance. Recorded minimum lot formulas must match explicit report units;
those units are still independently unverified. The offline preflight reuses
that parser, the unchanged 8192-byte market-only contract, and hash-pinned
original offline clock policies. It retains no private report. Included report
fixtures are synthetic. No SDK/network broker transport is installed.

Connection in the app, fresh broker prices and blocked orders have separate
labels. Successful replay or a read-only screenshot cannot grant source freshness,
verified broker profile, producer acceptance or execution. `analysis.market_source`
remains None. Runtime, AI, paper and broker execution remain false; USD2000 cap,
SL/strategy and MOCK are unchanged. The latest supplied failed capture is
UNAVAILABLE with stale ticks and minimum-lot notional above cap; no retry occurred
here. Weekend closure is plausible, exact account sessions unverified.

## Local validation

230 tests passed, 3 declared skips. Trading/status/parser/producer/preflight and
host isolation: 121 passes. Finance, connection, AI unified: 49 passes. Additional
AI content/listening and production foundation under pytest: 60 passes, 3 skips.
The first extra-suite invocation used unittest with missing pytest and therefore
did not execute those tests; pytest was installed only into the disposable
workspace environment and the correct runner passed. No product code changed.
Browser regression passed at 1440/768/390/320, including MOCK lifecycle, disabled
connection controls, safe diagnostic rendering, unchanged source state and zero
diagnostic import requests. Node syntax and git diff check passed.

Local PostgreSQL tools are unavailable; existing Trading QA PostgreSQL CI remains
the release gate. No live MT5/NTP, inference, orders or owner-PC access. Parent
owns the production browser check after release. CI and Render results will be
reported with the exact release SHA, separately from this pre-commit evidence.

## Exact files in this change

- `.github/workflows/kilas-trading-qa.yml`
- `client-hub/static/kilas_trading.js`
- `client-hub/templates/kilas_trading.html`
- `client-hub/tests/test_kilas_trading_browser.py`
- `client-hub/tests/test_kilas_trading_diagnostic.py`
- `client-hub/kilas_trading/producer.py`
- `client-hub/tests/test_kilas_trading_producer.py`
- `client-hub/tests/test_kilas_trading_preflight.py`
- `client-hub/tests/fixtures/trading_preflight_synthetic.json`
- `scripts/trading_diagnostic_preflight.py`
- `client-hub/tests/fixtures/trading_clock_policy/README.md`
- `client-hub/tests/fixtures/trading_clock_policy/clock_batch_offline.py`
- `client-hub/tests/fixtures/trading_clock_policy/source_batch_offline.py`
- `client-hub/tests/fixtures/trading_clock_policy/validate_trace.py`
- `docs/KILAS_TRADING_CLOCK_POLICY_VERIFICATION_20261010.md`
- `docs/KILAS_TRADING_COLLECTOR_SOURCE_REVIEW_20261010.md`
- `docs/KILAS_TRADING_DECIMAL_ACCEPTANCE_20261009.md`
- `docs/KILAS_TRADING_DEMO_GAP_CLOSURE_20261010.md`
- `docs/KILAS_TRADING_LATEST_DIAGNOSTIC_READINESS_20261010.md`
- `docs/KILAS_TRADING_NOTIONAL_CONSISTENCY_20261009.md`
- `docs/KILAS_TRADING_PREFLIGHT_20261010.md`
- `docs/KILAS_TRADING_PRODUCER_BOUNDARY_20261010.md`
- `docs/KILAS_TRADING_WINDOWS_READONLY_CHECK_20261010.md`
- `docs/KILAS_TRADING_SERIAL_INTEGRATION_20261010.md`
