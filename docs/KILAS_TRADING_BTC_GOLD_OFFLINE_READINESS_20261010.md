# BTC/Gold offline component readiness

This change extends the existing bounded DEMO analyst to exactly BTC and GOLD.
It does not implement orders, a worker, an HTTP approval issuer, or a Gold feed.
Runtime model remains `gpt-6.1-sol`, reasoning `medium`; existing pricing,
model budget, risk policy, SL/TP strategy and MOCK engine are unchanged.

## Boundaries

The existing BTC endpoints remain BTC-only. New `/control/gold-analysis` and
`/control/gold-evidence` endpoints require separate, default-off
`KILAS_TRADING_GOLD_ANALYSIS_ENABLED` / `KILAS_TRADING_GOLD_EVIDENCE_ENABLED`
flags and retain the existing Trading host, pilot, scoped bearer credential,
current DEMO ACK, exact JSON, 8 KiB, no-cookie/query and replay protections.
No flags or credentials are changed by publication. Owner browser controls stay
disabled and `analysis.market_source` stays `None`.

`GOLD` maps only to broker symbol `GOLD`, not an inferred `XAUUSD` alias. Its
reviewed contract hash, market source and news coverage are distinct from BTC.
Contract size, minimum/step, tick, stop distance, spread, costs, notional and
approved loss are independently checked. The reported 0.01 lot at 100 oz/lot
and approximately $4,188/oz exceeds the unchanged $2,000 exposure cap and is
BLOCKED. Unknown commission/slippage/swap bounds remain `COSTS_UNKNOWN`.

Gold requires fresh `GOLD_MACRO_CALENDAR` news and a separate bounded calendar
record, reviewed server-side. The server-only `install_reviewed_gold_news`
handoff accepts exact allowlisted fields; it does not fetch data or confer
runtime authority. Calendar coverage must cover the current time plus/minus
15 minutes; HIGH/UNKNOWN USD events in that window block analysis. Unreviewed,
missing, stale, empty or known HIGH-risk Gold evidence blocks before inference.
There is currently no configured Gold news/calendar provider. BTC editorial RSS
cannot satisfy Gold coverage. BTC empty/known HIGH news now blocks before
inference too; its existing UNKNOWN editorial assessment remains bounded.

Durable reservations, exact request identity, duplicates, uncertain outcomes,
provider schema/usage, pre/post-model freshness and final intent checks are
shared with BTC. BUY/SELL remain proposals, WAIT stays blocked, and no trade
quota or forced entry is introduced. A Gold runtime flag alone cannot adopt
BTC authority or bypass the distinct reviewed runtime grant/current ON lease.
Evidence-only false/0/0 manifests stay read-only with NULL run authority.

## Offline verification and limits

Synthetic tests cover BUY/SELL/WAIT, freshness, exact schema/symbol isolation,
calendar risk, reported Gold minimum notional, unknown costs, independent
SL/TP/tick/stop/loss checks, timeouts, malformed/ambiguous model output,
duplicates, credentials/owner/host/cookie/body isolation, receipt-window capture,
persistent source state, reviewed news replacement and zero model/runtime
authority. Small-contract successful Gold fixtures are deliberately synthetic
10 oz/lot contracts and are not claims about the owner's broker contract.

Trading QA now includes control, BTC analysis/source and Gold suites on SQLite
and isolated disposable loopback PostgreSQL. Existing Trading, diagnostic,
producer, preflight, bridge, host-isolation and browser regressions are retained.
The PostgreSQL helper runs each suite separately and avoids a repeated app
startup migration pass; it does not modify production migration behavior.

No live provider, MT5, NTP or broker tests are performed. No orders, secrets,
runtime activation, production migrations or paid inference are authorized by
this change. Windows `demo_control_v2.py`, `demo_worker_runtime.py` and the
owner's durable runner/close-only recovery files are absent from this checkout;
their integration and the discarded post-fill error root cause cannot be
verified here. This is offline component readiness, not end-to-end trading
readiness, net P&L/drawdown assessment, or permission to execute a DEMO trade.
