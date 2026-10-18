# Expense entry: confirmed reference scope

Continued from main/LIVE `97acf5ce`. Owner confirmed the written Add Expense
scope on 2026-10-18: receipt photo; category/subcategory; multiple category
allocations on ONE expense; date; amount; pay-from account; optional payee;
notes; top Cancel/Save. No unspecified Additional Options, OCR, AI, paid APIs,
pricing, subscription or sandbox changes.

Library reference `libfile_c8178ad33c2c819186c52268d4820c4e` resolved to the
specified JPEG and its extracted field text. The official materialization
helper failed downloading its pixels. The image itself was not visually
inspected; implementation follows the confirmed written layout and existing
Kilas brand/navigation. Local synthetic browser screenshots were inspected.

## Model and implementation

- `finance_expense_entries.py` keeps exactly ONE ordinary expense transaction.
  Category allocations, private receipt bytes and submission metadata live in
  additive tables. No extra parent/child money transactions or account debits.
- The existing business-scoped write lock contains parent posting, splits,
  receipt, payee and audit changes. A unique business/submission key plus actor,
  owned branch/account and canonical payload hash returns the same row for an
  exact replay, rejects conflicting reuse and handles concurrent requests.
- Amounts use the existing Decimal currency parser and integer minor units.
  Two to twenty distinct active category/subcategory allocations must be
  positive and sum EXACTLY to the expense amount. Parent/child relationships,
  account currency, selected workspace/branch, permissions and entitlement
  remain server validated. No browser float determines accounting.
- Account/cashflow/transaction reports still count the parent ONCE. Category
  totals, category drill-down and budget category amounts use allocations;
  nonsplit historical rows fall back to their original amount/category. Void
  removes the parent from all posted totals. Expense edits update the same row
  and allocation history atomically; stale edits are rejected by the existing
  revision token. Same-branch account changes reverse/reapply the one amount
  through existing balance calculation. Cross-workspace moves of split entries
  are deliberately unavailable rather than retaining foreign category links.
- The new expense form is isolated from the existing income form. Existing
  nonexpense and managed-payment editors remain intact. Legacy POST callers
  without the new form key retain their existing path; the new UI uses durable
  server idempotency. Receipt photo and all confirmed expense fields are also
  available on manual expense edit. UI copy/errors cover ID, EN, ES and ZH.

## Receipt security and limits

Uses existing bounded Finance image validation/normalization, real MIME checks,
dimension/decompression limits and safe filenames; JPG/PNG/WebP only. Up to
20 MiB input; stored photo at most 4 MiB. Receipt bytes are private database
attachments and downloaded through the authenticated transaction ownership and
current branch scope, with attachment disposition, no-store, nosniff and a
restrictive CSP. No provider/OCR request, automatic transaction extraction,
public URL or temporary persisted draft.

Storage admission is serialized globally on Postgres and stays inside the
business transaction: 20 MiB per business workspace and 64 MiB across these new
receipt attachments. Existing photos count; replacing a photo excludes only
that transaction's old bytes. Capacity rejection rolls back the entire save,
with a localized message to retry without a photo. No automatic deletion or
infrastructure purchase. Cancel does not persist anything.

## Schema and release

Migration `0107_finance_expense_entries` creates four initially empty tables and
one category amount view. It performs no financial row backfill, deletion or
mutation. Production uses the existing exact-release checksum/advisory-lock
Finance migration installer while broad boot migrations remain unchanged.
SQLite uses the existing additive migration list. Older rows remain readable;
rollback must retain write protection for new split entries because a historic
editor does not understand allocations.

Pre-release read-only aggregate fingerprints (no financial contents retrieved):

| Existing table | Rows | Fingerprint |
|---|---:|---|
| finance_transactions | 69 | ec206cd2c4352e32b1d6eb4539632fb1 |
| finance_accounts | 38 | c37378107240c4f9537ff1633c934157 |

## Targeted verification

38 focused synthetic tests passed: nine expense-entry tests plus the existing
approved Finance and workspace-correction suites. Covered ordinary and split
saves, exact USD100.01 = 50.00 + 50.01, under/over totals, subcategory forging,
foreign account/category/tenant/branch denial, Personal data scoping, concurrent
duplicate requests, payload conflicts, edits/account changes, void totals,
private receipt bytes/download headers, rollback on commit failure and four
UI language renders. All financial writes were in disposable local fixtures.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=client-hub:client-hub/tests \
 /tmp/kilas-call-venv/bin/python -m unittest test_finance_expense_entries \
 test_finance_approved_revisions test_finance_workspace_corrections -q
```

Actual local Flask/Chromium tests passed at 320/390/768/1440 widths. They use
the expense button and actual form POST, select category/subcategory splits,
attach a synthetic JPEG, save/edit/reload, download matching receipt bytes,
cancel without writes and check no horizontal overflow or JS errors. Final
320/1440 confirmation passed after minor header/label alignment corrections.
Browser testing found and fixed omission of empty split subcategory fields by
native form submission; server tests alone had explicitly supplied them.

Evidence: `/tmp/kilas-finance-expense-final.log`,
`/tmp/kilas-finance-expense-browser.log`,
`/tmp/kilas-finance-expense-browser-final.log`,
`/tmp/kilas-finance-expense-browser/`.

No real financial writes, paid provider calls, mobile camera hardware test or
authenticated production expense save was performed. Deployment/schema/startup
and aggregate hash checks are distinct from physical Android acceptance.
