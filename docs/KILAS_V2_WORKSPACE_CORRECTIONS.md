# Phase 7 Finance workspace corrections

This is a supported correction of workspace classification inside **one immutable
Finance business**. It is not a cash transfer, income, expense, new ledger row, or
cross-business migration. Existing row IDs, economic fields and source references
remain intact. The original two positive workspace tests remain unchanged.

## Database command boundary

Migration 0059 adds an immutable correction journal and a monotonic correction
version on transactions and recurring rules. Inserting a correction command
atomically applies that exact old -> new branch/account/category transition via
a database trigger. Each command validates a current OWNER membership, two active
opposite Business/Personal workspaces, ownership of any Personal workspace, and
same-business account/currency/category compatibility. SQLite and PostgreSQL use
the same checks.

The branch guard continues to reject ordinary raw UPDATE, cross-business changes,
version reset/replay, or combined financial-content changes. Its only new accepted
transition must match the immutable journal entry for **current version + 1**.
After application the permission is consumed by the new version; it cannot be
reused after a reverse move. There is no connection-wide disable flag, trigger
suspension, deleted/recreated ledger, or tenant identity exception. Journal foreign
keys retain the underlying transaction/rule, and journal UPDATE/DELETE is rejected.
Accounts, invoices and bank imports retain their original strict identity guards.

The authenticated service independently requires a real owner, explicit source
branch/actor, active Finance write entitlement and authorized destination. The
HTTP command acquires the existing Finance business transaction before resolving
or initializing the destination. Default accounts/categories, corrections,
transaction revisions, recurring rules, opening amounts and audit commit together.
A late audit failure restores the entire request, including a newly initialized
Personal workspace. SQLite serializes writers; PostgreSQL uses the existing
business-row lock. Competing transaction moves re-read after locking; only one
moves the row. A stale second request fails closed without reversing it.

## Opening amounts and account corrections

A full eligible-account move maps each transaction and unposted rule to the target
account. The source opening amount becomes zero; the destination receives exactly
that amount in addition to its existing opening amount. An immutable opening
history record captures both original amounts and the owner. No operating cash
flow is inserted. Source accounts and their identity are retained; an empty source
may archive, and reverse corrections can reactivate the same original account.
Repeating an already-empty account move cannot add the opening amount again.
All integer minor-unit, native-currency and report calculations remain unchanged.

## Conservative exclusions

Individual moves permit only existing manual/operator/receipt origins without
customer/project links, invoice-payment links, recurring-posting links, or bank
reconciliation links. Full-account moves also reject any invoice-payment or FX
account history, bank import batch, already-posted/reserved recurring occurrence,
or project-linked rule. Both posted and void history are inspected for eligibility.
An unposted recurring rule retains its ID, schedule, amount and audit reference.

These exclusions are explicit safety boundaries: imported/reconciled batches and
posted recurring history need a separately reviewed whole-structure correction
before they can move. They are not detached or silently rewritten. Invoice/FX
records never move through this command. Historical transaction revisions remain
readable; every new correction adds another revision rather than overwriting it.

## Verification

Original positive dashboard tests plus new correction tests cover economics,
reverse/repeat moves, plain SQL denial, monotonic command replay, immutable history,
owner and private-workspace authorization, reconciliation protection, independent
concurrent connections, late rollback, failed first-use initialization and repeat
migration. `scripts/run_finance_baseline.py` executes the complete isolated gate.
PostgreSQL certification is `client-hub/tests/finance_workspace_postgres_qa.py` and
requires the explicitly named disposable loopback `kilas_phase7` database.
Production migration, data access and deployment are outside this run.
