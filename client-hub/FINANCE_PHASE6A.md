# Phase 6A — Receipt & expense intelligence

Base inspected: remote main `6886dccdc86e2cd4d9aec3c96b0672b031e0e664`.
The prior local Phase 5C commit and its untracked ZIP were preserved in their
original worktree. Phase 6A uses a separate branch/worktree based on remote main.

## Workflow and privacy

Finance → **Scan Struk / Receipt** → upload → review → **Catat Pengeluaran**.
`GET /business/<id>/finance/receipts/new` is read-only.
`POST .../receipts/analyze` validates one file, checks for an existing receipt
origin, and makes at most one extraction request. It creates **no database rows**,
including Finance records, audit events or AI usage records. Cancel and refresh
also create no Finance records. An exact already-recorded file is identified before
spending another AI call. No automatic sending or public receipt endpoint exists.

`POST .../receipts/confirm` requires a valid analysis token, explicit checkbox,
reviewed amount/date, IDR currency, active IDR account and active EXPENSE category.
Account/category choices are loaded from the authorized business on the server,
never chosen by the model. The category is visibly labeled **Saran AI** and is not
automatically selected. Original extracted values and editable final fields are
shown separately. Inactive/wrong-tenant references are rejected again inside the
Finance write transaction. A validation error preserves the review for correction.
A successful confirmation redirects to the recorded transaction's month.

Receipt bytes exist only during the request (including normal multipart temporary
spooling and an in-memory parser pipe). No permanent files, archive, session bytes,
localStorage, database receipt blobs, raw-response logs or receipt-data URLs.
The UI discloses that analysis sends receipt content to the configured AI provider.
Provider retention is subject to the existing provider/account policy.

## Upload and PDF limits

Receipt validation wraps `file_utils.validate_project_attachment_upload`, reusing
its real-byte helpers. Only JPG/JPEG/PNG/WEBP/PDF, maximum 5 MiB, one file per request.
Images must decode, match their declared format, be single-frame and at most
20 million pixels. Existing upload behaviors elsewhere are unchanged.
The application's existing 12 MiB request cap also applies to multipart requests.

PDFs must parse with installed pypdf, be unencrypted and contain 1–10 pages.
Parsing/text extraction uses a disposable subprocess with 384 MiB address-space,
5 CPU-second and 8-second wall-time limits. It receives bytes through stdin and
returns at most 20,000 text characters, with no parser logs. Pathological inputs
fail safely. Linux/POSIX `resource` support is required for this PDF path; without
it PDFs fail closed. Images/manual Finance entry remain available.

PDF text of at least 40 non-padding characters uses a text request; otherwise a
base64 PDF `document` block is sent for scanned receipts. Images use a base64
`image` block. Extracted text can be incomplete; users must check the original.

## AI and signing

Uses existing requests-based Anthropic Messages infrastructure and credentials:
`ANTHROPIC_API_KEY`, `CLIENT_HUB_MODEL` (existing vision default `claude-sonnet-4-6`).
No SDK, provider, credential system, model-default changes to Phase 4, repair calls,
usage writes or automatic ledger actions. Fixed system instructions treat all
receipt/category content as untrusted data. Bounded exact JSON schema rejects
unknown/duplicate keys, invalid amounts/dates/currencies, oversized strings and
category suggestions outside the supplied active EXPENSE names. Suggestions are
limited to the first 100 active categories to bound the prompt; all active
categories remain available in the human selection form.

Timeout `(5, 25)`, maximum 700 output tokens, no redirects or retries. Missing
credentials, unreadable receipts, malformed results and shared AI-rate-limit
exhaustion produce empty manual review fields. Unsafe signing configuration fails
before a paid call and offers existing Finance manual entry.

Receipt extraction shares `finance_ai_safety.allow_attempt(..., 'ai')` with the
Analyst/Operator; confirmation uses the shared `confirm` bucket. The existing
limiter is bounded and process-local, not a distributed quota. Diagnostic logs
use existing fixed event categories, never amounts, hashes, filenames, raw model
responses, tokens, receipt contents or provider errors.

Review tokens use the existing strong application SECRET_KEY requirement (at
least 32 characters; insecure default rejected), SHA-256 signatures, dedicated
salt `kilas-finance-receipt-v1`, and a 600-second expiry. Exact payload: purpose,
version, user_id, business_id, receipt_hash, safe filename, bounded extraction
metadata, random nonce. Tokens are signed, **not encrypted**, and only appear in
hidden POST fields. Signature, schema, expiry, identity and business membership
are verified before ledger access. No AI call occurs during confirmation.

## Managed ledger origin and duplicates

`finance_service.create_receipt_expense` validates reviewed fields and uses the
existing Finance business lock, `_transaction_data`, `_insert_transaction` and
transaction-created audit event. There are no nested transactions or new tables.
Origin is `FINANCE_RECEIPT`, source_ref is lowercase SHA-256 of the original bytes.
Direction is EXPENSE and currency IDR. Merchant maps to counterparty_name.

The authoritative duplicate lookup is inside the business write lock before
insertion. Same tenant/hash, actor and every accounting field may return the
existing POSTED row. Different fields/actor, an edited record, or a VOID row
conflict safely. Other tenants neither see nor are blocked by the hash.
Normal creation cannot impersonate this origin; normal updates cannot change
its source_type/source_ref or turn another origin into it. Receipt direction and
currency also remain EXPENSE/IDR. Other fields retain normal validated edits.
Audit failure rolls back the ledger insertion.

Exact-byte deduplication does not identify rephotographed, resized, re-encoded or
otherwise modified copies. No long-term receipt archive, persistent OCR metadata,
bank import, reconciliation, new migration, or Phase 6B functionality is included.

## Tests

Use isolated processes: legacy Finance fixtures change shared global DB paths.
Tests use disposable SQLite databases and mocked AI HTTP, never live Anthropic.
From repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/offline_tests:client-hub:client-hub/tests python client-hub/tests/test_finance_phase6a.py
```

Run each existing `test_finance_phase*.py` and Client Hub regression script with
that same environment in a separate process. Invoke the two functions in
`test_postgres_sql_adapter_external_audit.py` directly (it has no script runner).
The existing offline sitecustomize blocks network connections and strips live DB
configuration. Production databases/migrations are never used by this workflow.

Coverage includes real image/PDF fixtures, parsing caps, malformed outputs,
injection data, zero-write snapshots, explicit reviewed confirmation, reference
changes, CSRF, auth/beta/tenant checks, signed-token bindings/expiry, byte dedup,
VOID protection, origin immutability, atomic audit rollback, shared rate caps,
escaping/privacy and simultaneous confirmations against SQLite.
Real PostgreSQL locking and live Anthropic behavior require deployment-environment
validation. Mobile uses the existing responsive Finance grid without wide tables;
actual browser interaction remains unverified in this runtime without Chromium.

Final isolated regression results:

| Suite | Passed | Failed |
| --- | ---: | ---: |
| test_finance_phase1a.py | 15 | 0 |
| test_finance_phase1b.py | 16 | 0 |
| test_finance_phase2a.py | 25 | 0 |
| test_finance_phase2b.py | 22 | 0 |
| test_finance_phase3.py | 19 | 0 |
| test_finance_phase4a.py | 15 | 0 |
| test_finance_phase4b.py | 35 | 0 |
| test_finance_phase4c.py | 25 | 0 |
| test_finance_phase5ab.py | 24 | 0 |
| test_finance_phase5c.py | 30 | 0 |
| test_finance_phase6a.py | 53 | 0 |
| test_app_service_briefs.py | 18 | 0 |
| test_postgres_sql_adapter_external_audit.py | 2 | 0 |
| test_client_hub_v1.py | 22 | 0 |
| test_production_foundation.py | 26 | 0 |
| test_business_hub_v2_phase_a.py | 19 | 0 |
| test_client_hub_batch1.py | 16 | 0 |
| test_client_hub_batch2_3.py | 14 | 0 |

Total: **396 passed, 0 failed**. Phase 6A: **53 passed**.
