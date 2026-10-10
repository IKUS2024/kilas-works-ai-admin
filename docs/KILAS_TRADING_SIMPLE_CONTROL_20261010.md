# Trading minimal control — local release preparation, 2026-10-10

The owner's final request supersedes the earlier collapsed-maintenance design.
The visible Trading page contains only GOLD/BTC selection, LOT and ON/OFF, with
one short control-local `OFF · Belum siap` status. No account, risk, chart,
position, history, connection, diagnostic or AI panel/accordion is rendered.
No Trading JavaScript is loaded by this page. Existing shared shells are unchanged.

## Control dependency and truth

No recurring DEMO executor start/stop/status API exists in this checkout.
`routes.py` retains paper actions and observation upload; `bridge_routes.py`
retains read-only pair/exchange/telemetry/status/revoke. Neither controls a
broker robot. `analysis.market_source` remains `None`.

`#demo-robot-toggle` is a disabled switch button, unchecked, with no form or
handler. OFF means this dashboard cannot activate a robot; it does not attest
that an independently run local MT5 executor is stopped. The reported separate
one-shot DEMO entry/close does not establish a recurring dashboard controller.
No order or broker connection is initiated by this page.

GOLD/BTC and LOT are editable page-local drafts. Default BTC and LOT 0.01 reset
on reload, with no submission or persistence. Browser minimum 0.01 is not backend
acceptance. `step=any` avoids guessing broker rules; no maximum is invented.
GOLD/BTC are display identifiers, not resolved broker symbols or analysis feeds.
A future reviewed executor contract must resolve GOLD/XAUUSD/suffix and BTC
symbols, validate each broker's volume_min/max/step and unchanged backend risk
limits, and disable instrument changes while active or require confirmed stop
first. Draft changes never migrate position management. GOLD's lot/risk is not
assumed identical to BTCUSD; existing historical reports do not establish readiness.

## Preserved backend work

The scoped release also retains the preceding OFF-revocation and safe collector
stage/status diagnostic patch. Authenticated pilot status and CSRF-protected
revoke work OFF while pair/exchange/telemetry remain blocked. Confirmed progress
comes from existing sanitized rows; failed server attempts remain NOT_RECORDED.
Collector diagnostics use fixed codes and optional exclusive-created sanitized
local status. Strict secret input, read-only SDK guards and shutdown remain.

No backend history/data, API route, risk cap, strategy, SL, MOCK engine or parser
asset is deleted. The recorded import panel and maintenance UI are removed from
the normal page as explicitly requested; backend/retained parser functionality
is not replaced by an executor. No new diagnostic web route is invented.

## Validation and release boundary

Main base is `faae3fbca5f1018c16b013f69af30c537654d796`. Scoped changes avoid Home,
Kilas AI, Finance and shared shells. Preparing a local main commit is explicitly
authorized for review; push/deployment remain coordinated. Production bridge
remains OFF. No real MT5/NTP, paid call, environment/security change or order.

38 Trading + 62 bridge/collector + 4 host-isolation + 20 retained parser/security
tests passed (124 total). Both loopback browser
suites passed: only three controls, invalid lot, local draft changes/reset, no
POST/state mutation, storage failure remains OFF, and retained synthetic bridge
API pairing/telemetry/OFF-status/CSRF-revocation. GOLD and BTC each passed
1440/768/390/320 px screenshots/overflow checks with no page errors.

Authoritative final commit patch, screenshots, test logs and exact modified files
are in `/workspace/trading-final-ui-review-20261010/`. Earlier review artifacts
are preserved but superseded by this final controls-only layout.
