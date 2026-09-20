# Finance conversational agent — September 2026

The Assistant is an adapter over the existing Finance services. It does not maintain a separate ledger or introduce a migration.

## Draft boundary

`assistant/message` accepts a new message or the current signed review context plus a message and optional confirmation token. Server parsing handles common Indonesian edits first. The constrained interpreter may copy only semantic values literally present in the message. It cannot select IDs, change action, authorize writes, or calculate financial truth. Scoped server options resolve names; ambiguity preserves the prior draft.

Reviewed values, action, nonce, tenant, user, branch and expiry are checked before confirmation. Service validation runs immediately before the write. Invoice creation and issuance have independent reviewed confirmations, audit markers and idempotency inside the existing business write lock. Creation leaves the invoice DRAFT. Issuance also checks a fingerprint so a manually changed invoice cannot be issued from stale review.

Manual field names are recorded in `finance_draft_fields.py` and covered against templates and Assistant adapters. Customer validation uses the shared helper. Read-only answers use Finance projections and native currencies; no model-generated financial numbers.

## PDF boundary

Extension, signature, EOF, byte limits and bounded worker inspection precede generic classification. The worker has a 384 MiB address-space limit and 5 CPU seconds; its parent imposes an 8-second timeout. Generic/bank PDFs allow 20 pages / 10 MiB; receipt-specific handling retains 10 pages / 5 MiB.

pypdf owns normal structure/text reads. If structural parsing fails, QPDF via pikepdf independently attempts bounded structural recovery in the same worker. It never renders, executes PDF scripts, or OCRs. Memory/time/password/page violations fail closed. Safe PDFs with missing, broken or incomplete text reach the existing provider document path with their original bytes. Only fixed reason codes are logged.

pikepdf uses manylinux wheels compatible with the Render Python runtime, avoiding a system qpdf package or local compilation. Keep recovery isolated: importing the library into the web worker is unnecessary. Upstream API: https://pikepdf.readthedocs.io/en/latest/api/main.html

The actual reported BCA PDF was not supplied. Regression fixtures generate representative compressed bank-export PDFs, damage xref metadata, and exercise primary-parser failure plus real secondary recovery. Provider responses are mocked in offline regressions; recognition and extraction never post ledger transactions.

Document currency comes from printed evidence/context, never amount magnitude. A signed hash-bound classification context filters eligible bank accounts; extraction and write services independently enforce account currency. A bare dollar symbol remains ambiguous.

## Verification

Run the isolated Finance regression runner and Node Finance suites. The runner disables network and uses disposable SQLite databases. New behavioral browser tests execute the real Assistant script, including retained uploads and server account selection. Asset version: `20260920-server-agent-3`.

Production checks must use authenticated read-only pages when an authorized session is available. Do not create real finance records solely for smoke testing. Whole-repository legacy failures must be compared with the untouched baseline and reported separately from Finance regressions.
