# Windows DEMO integration review

This isolated Windows worker matches the BTC and Gold contracts in cloud main
`db035b5da415bed61bed08e2b1cac50d8d31f73c`. It adds instrument-specific capture,
control acknowledgements, bounded HTTP routes and analyst proposal parsing.
Gold uses broker symbol `GOLD`; `XAUUSD` is not an accepted wire alias.

The factories do not attach MT5 or start workers. Endpoint authorization, owner
scope, reviewed risk/cost facts and a secure credential provider are required
explicitly. Activation defaults to false. Gold rejects activation and any
execution grant. Unknown fees, uncovered cost bounds and exposure above the
existing USD 2,000 cap block locally before an analysis request. Runtime model
remains `gpt-6.1-sol`, medium reasoning, default service tier.

The published terminal data path is a deliberate nonfunctional placeholder.
The private local pin remains on the owner's PC. Review that pin separately
before any future native attachment; this publication configures no machine.
No local account binding, ledger, credentials, installer, captured broker data,
historical order helper or runtime configuration is included.

Run only the reproducible offline verification from this directory:

```powershell
python -B run_offline_tests.py
```

Python 3.12 standard library is sufficient. Tests inject fake SDK and in-memory
HTTP collaborators, use temporary journals and never attach MT5, send native
order checks/orders, request inference or contact a model provider. They cover
wrong instrument/symbol/routes, duplicate JSON, contract changes, transport
watchdogs, journal vetoes, Gold proposal-only behavior, caps and cost blockers.
Parity tests evaluate selected pure definitions from hash-verified pinned cloud
source; they do not import the cloud app. Full cloud Flask regression belongs
to the cloud environment and remains a separate check.

The runner blocks external socket connections, UDP sends, subprocesses and
native SDK imports for the entire discovery/run. Aggregate results go to stdout;
the published historical `offline-test-result.json` is never rewritten. Its
323 tests and the historical 411-test local suite overlap and are not additive.
Manifest checks cover every shipped file, and cloud CI additionally compares the
pinned contract sources with the current server before accepting the bundle.

The retained source snapshot is test input under `cloud-contract-db035/`, not
a replacement for cloud server modules. Publication adds this directory and a
scoped Trading CI gate; it changes no server flags, UI, Finance, unifiedHome or
existing cloud application source.

The historical local UNKNOWN entry audit remains intact. A separately audited
exact-ticket close and later read-only flat checks do not automatically clear
that entry veto. Future policy review must decide whether an append-only
resolution may link the confirmed close to the original UNKNOWN audit, and
what independently approved fresh session and prerequisites would be needed.
This package neither implements that resolution nor grants a new entry.

Gold still needs reviewed macro/calendar evidence, verified clock/session
evidence, costs and an exposure-compatible contract before future use. The
observed local minimum lot exceeded the unchanged cap. Publication alone
does not make either instrument ready for runtime activation.
