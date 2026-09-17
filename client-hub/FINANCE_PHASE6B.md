# Finance Phase 6B — Bank Statement Import & Reconciliation

Implemented on Phase 6A parent `4d9631b1f6a925f52d50ed1483f578fdef5f89fb`.
The existing local `origin/main` reference is `6886dccdc86e2cd4d9aec3c96b0672b031e0e664`.
Remote state was not fetched or changed. No push, deployment, or production migration.

## Product behavior

Finance dashboard → **Import Mutasi Bank** → choose an active IDR Finance account →
upload → extract → correct/add normalized rows → **Mulai Rekonsiliasi**.
Every open row remains UNMATCHED until a person chooses an existing transaction,
**Catat Transaksi**, or **Abaikan Baris Ini**. Leaving it untouched leaves it unmatched.
Upload, extraction, corrections, opening, matching and ignoring never create ledger money.

REVIEW rows are editable; optimistic revisions reject stale corrections/opening.
OPEN freezes the reviewed rows. COMPLETED means all rows have explicit decisions,
not that the statement is financially verified. REVIEW and undecided OPEN imports
can be cancelled without deletion. Imports with decisions cannot be cancelled.

## Architecture

- `finance_bank_extract.py`: standard-library CSV parsing, shared byte validators,
  ordered source hashing, strict row normalization, one bounded Anthropic request.
- `finance_bank_service.py`: tenant-scoped staging, review, candidates and decisions.
  All mutations reuse `finance_service._write` / `db.app_purchase_transaction`.
  PostgreSQL uses the existing business-row lock; SQLite uses the existing write lock.
- `routes_finance.py`: existing login, Finance beta gate, business access and CSRF;
  bank responses have private/no-store caching and no-referrer headers.
- Bank multipart streams stay in request memory instead of Werkzeug disk spooling.
  Bank upload requests have a 26 MiB envelope cap; other routes retain their 12 MiB cap.
  Flask 3.1+ is required for the request-specific size setting.
- Existing receipt, operator, invoice-payment and recurring protections are retained.
  Bank origins cannot be created through normal transaction creation, spoofed by
  updating an unrelated transaction, or changed on an existing bank-origin record.

## Extraction and file limits

| Input | Behavior |
| --- | --- |
| CSV | One `.csv`, ≤2 MiB, UTF-8/BOM only. No AI or AI quota consumption. |
| PDF | One real PDF, ≤10 MiB, ≤20 pages. Isolated pypdf worker first. |
| Images | JPG/JPEG/PNG/WEBP, ≤10 files, ≤5 MiB each, ≤25 MiB combined; real-byte validation. |

CSV uses `csv.reader(strict=True)` plus quote-placement validation. Supports the two
canonical formats and explicit case-insensitive aliases; rejects duplicate semantic
headers, mixed formats, binary/control data, malformed records and uncertain values.
Limits: 1,000 data rows, 50 columns, 2,000 characters per cell. Unknown columns are
discarded. Dates accept only the four specified formats. Money uses integers only;
grouping and zero decimal fractions are accepted; nonzero fractional rupiah is rejected.

PDF parsing retains Phase 6A resource isolation: 384 MiB address-space limit,
5 CPU seconds, 8-second parent timeout, suppressed parser diagnostics. Receipt
limits remain 5 MiB/10 pages/20,000 text characters. Bank text is bounded at
100,000 characters. Usable text goes to Anthropic as untrusted text only; scanned,
mixed, short-page or truncated text goes through a base64 PDF document block.

Images are submitted in order in one request. The existing requests-based Anthropic
Messages pattern is reused; no other OCR provider, tools, model retry or repair call.
Existing shared Finance user/business AI quota applies to both PDF and image extraction.
Strict JSON rejects unknown/duplicate fields, malformed output, truncation, wrong
types, noninteger money, invalid dates/directions, oversized rows and unreadable results.
Provider failure/quota exhaustion produces an empty REVIEW import with manual entry.
Invalid source files/CSVs are rejected before staging. Neither path posts money.

Only normalized transaction data and hashes are persisted. No raw files/model output,
bank metadata columns, credentials, source filenames or balances are archived.
Obvious account/balance identifiers and long numeric identifiers in normalized text
are redacted. Review copy asks users not to enter account numbers, balances or credentials.
Audit records contain fixed event names and record IDs only; provider errors and
statement contents are not included in application error responses/log messages.

## Identity, candidates and atomic decisions

Single-source identity is SHA-256 of validated raw bytes. Multi-image identity hashes
a versioned canonical JSON representation of the ordered individual hashes. Exact
duplicate uploaded files are rejected. Import uniqueness is business + account + hash;
duplicate uploads return the existing import without another model request.

Row hashes include source identity, business/account, row index and normalized fields.
Legitimate identical rows remain separate; identical-looking rows are only flagged.

Candidate retrieval makes one bounded ledger query per import, scoped to business,
account, POSTED/IDR status and the import date span ±3 days. At most 5,000 ledger
records are loaded; a 5,001st result fails safely. Transactions are grouped by
direction/amount in memory. Exact-date results sort first, then date difference/date/ID;
each row shows at most 10 candidates with deterministic explanations. Linked
transactions are excluded. There is no automatic match or confidence score.

Explicit matching revalidates business/account/status/direction/amount/date inside the
business write transaction. Database uniqueness across the effective linked transaction
prevents one ledger record being used by multiple bank rows, including across POST/MATCH.

Explicit posting fixes account, direction and amount from the reviewed bank row. Only
active categories of the correct direction and business are accepted. Date, description
and counterparty can be reviewed. The internal validated/audited insert, row link/state,
reconciliation audit and completion audit commit together with no nested transaction.
Origin is `FINANCE_BANK_IMPORT`; source_ref is the lowercase 64-character row hash.

Exact POST replay returns the existing matching POSTED transaction without writes,
including if the account/category was subsequently archived. Conflicting confirmation
or VOID state is rejected. VOID never resets a bank row or silently recreates money.
Later changes to linked ledger amount, direction/account or match date are flagged.

## Migration 0031

SQLite and PostgreSQL migrations add `finance_bank_imports` and `finance_bank_rows`,
with tenant-composite foreign keys, state/link consistency constraints, integer money,
source deduplication, row identity uniqueness, one-link uniqueness, managed-origin
uniqueness and candidate/import lookup indexes. Registration is additive in `db.py`.
SQLite migrations, repeat application, foreign keys and uniqueness were executed
against disposable databases only. PostgreSQL parity and adapter checks passed;
no live PostgreSQL server was available, so PostgreSQL execution/concurrency remain
unverified and must be exercised before any later production rollout.

## Verification

Reproduce from repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python client-hub/tests/run_finance_regressions.py
```

The runner isolates suites in subprocesses, strips inherited DB/provider settings,
uses disposable SQLite fixtures, and blocks Python socket connections (also in child
Python processes). Providers are mocked. Both unittest and legacy function tests run.

| Suite | Passed | Failed / errors / skipped |
| --- | ---: | --- |
| Finance Phase 1A | 15 | 0 / 0 / 0 |
| Finance Phase 1B | 16 | 0 / 0 / 0 |
| Finance Phase 2A | 25 | 0 / 0 / 0 |
| Finance Phase 2B | 22 | 0 / 0 / 0 |
| Finance Phase 3 | 19 | 0 / 0 / 0 |
| Finance Phase 4A | 15 | 0 / 0 / 0 |
| Finance Phase 4B | 35 | 0 / 0 / 0 |
| Finance Phase 4C | 25 | 0 / 0 / 0 |
| Finance Phase 5AB | 24 | 0 / 0 / 0 |
| Finance Phase 5C | 30 | 0 / 0 / 0 |
| Finance Phase 6A | 53 | 0 / 0 / 0 |
| Finance Phase 6B | 114 | 0 / 0 / 0 |
| Client Hub V1 | 22 | 0 / 0 / 0 |
| Production foundation | 26 | 0 / 0 / 0 |
| Client Hub batch 1 | 16 | 0 / 0 / 0 |
| Client Hub batches 2–3 | 14 | 0 / 0 / 0 |
| Client Hub UX batch | 22 | 0 / 0 / 0 |
| PostgreSQL SQL adapter | 2 | 0 / 0 / 0 |
| PostgreSQL JSON compatibility | 16 | 0 / 0 / 0 |
| **Total** | **511** | **0 / 0 / 0** |

The initial full run had one runner-configuration failure: it set development mode,
while the existing foundation test requires default debug off. The runner now uses
test mode; the foundation rerun and final full run passed without changing legacy tests.

Concurrency results on SQLite:

- Two identical POST requests: one new ledger transaction, same returned transaction ID.
- POST versus MATCH for one row: exactly one decision succeeds, the other conflicts.
- Concurrent staging of the same source: one import, same returned import ID.
- Two bank rows matching one ledger transaction: one succeeds, one conflicts.
- Review versus opening from the same revision: one succeeds; no stale review is opened.
- Injected row-write, reconciliation-audit and completion-audit failures roll back
  both ledger and row state. No successful partial commit.

Security tests cover tenant/account/category isolation, auth/beta/CSRF, escaping,
no-store headers, safe audit/log output, source nonpersistence and immutable origins.
PDF resource limits remain confined to the worker process. Phase 6A regressions pass.

## Known limitations

- No real customer myBCA statement or screenshot fixtures were supplied. PDF/image
  transport and strict extraction validation were tested with generated fixtures and
  mocked Anthropic responses; real-world extraction accuracy is not claimed.
- AI may omit/misread rows. Its bounded 12,000-token response may truncate large
  statements and require manual entry. Human review against the original is mandatory.
- Shared AI rate limits retain the existing process-local architecture; they are not
  a distributed quota across application workers.
- Fixed CSV formats only, IDR only. No mapping wizard, XLS/XLSX, live bank sync or OCR
  service beyond Anthropic. Candidate lookup above the bounded ledger limit is unavailable.
- Normalized identifier redaction can remove long numeric references; original files
  are not recoverable from the application. Users retain and consult their own originals.
- No undo/reopen of completed decisions. Linked VOID/changed transactions need attention.
- Bank upload memory can exceed raw file size while constructing base64 model payloads;
  source and HTTP request sizes are bounded. No load-test claim is made.

## Exact changed-file manifest

All 19 files are under `client-hub/`; no repository-root source/configuration changes.

```text
client-hub/FINANCE_PHASE6B.md
client-hub/app.py
client-hub/db.py
client-hub/file_utils.py
client-hub/finance_bank_extract.py
client-hub/finance_bank_service.py
client-hub/finance_receipt_pdf.py
client-hub/finance_service.py
client-hub/migrations/0031_finance_bank_imports_postgres.sql
client-hub/migrations/0031_finance_bank_imports_sqlite.sql
client-hub/requirements.txt
client-hub/routes_finance.py
client-hub/templates/_finance_bank_review_fields.html
client-hub/templates/finance_bank_detail.html
client-hub/templates/finance_bank_index.html
client-hub/templates/finance_bank_new.html
client-hub/templates/finance_dashboard.html
client-hub/tests/run_finance_regressions.py
client-hub/tests/test_finance_phase6b.py
```

Phase 6A remains the unchanged parent commit; no reset, amend, squash, rebase or push.
Only local disposable test migrations ran. Commit identity is reported by `git log -1`.
