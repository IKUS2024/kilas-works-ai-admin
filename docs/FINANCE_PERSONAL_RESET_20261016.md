# Finance Personal consistency and scoped reset — 16 October 2026

## Release scope

Personal uses one existing owner-private ledger across every Finance entry point, with no Personal dataset selector or branch controls. Existing populated ledgers are reused; pristine empty legacy contexts remain stored. Multiple populated legacy contexts stop with a review message rather than merging, moving, copying or deleting financial records. Concurrent first entry across businesses creates only one Personal home. Switching back to Business preserves the last authorized active Business branch.

Add Income lists the current Personal ledger's existing active accounts and validates the same scope on save. No replacement bank/account or recovery data is created.

Reset Data Finance opens a separate warning naming the exact owner or business and selected branch. Final submission requires typed RESET, acknowledgement, CSRF and a server-stored ten-minute request. Ownership, target and data fingerprint are revalidated under the ledger write lock. Duplicate confirmations execute once; failures roll back atomically.

Personal reset targets only that owner's canonical ledger. Business reset targets **only the selected branch**. Other branches, Personal ledgers and other businesses are excluded. Active transactions, invoices and both internal-transfer/FX legs are voided; opening balances become zero, recurring expenses are disabled, pending bank imports are closed and target budgets are removed. Account definitions, categories, payees/customers, invoice settings, payment/history records and audit remain stored. No production reset was invoked.

Migration 0101 adds only reset-request and canonical-home metadata tables with foreign keys; no financial backfill, destructive migration or credential change. Existing 0100 migration is unchanged. Creative Services and unrelated modules are untouched.

## Validation

- 166 targeted regression tests: zero failures/errors/skips, across Personal/reset, approved Finance revisions, direction filters, home dashboard, workspace corrections, UI/locales, baseline, FX precision and invoices.
- 6 native PostgreSQL 18 tests on a disposable local database: atomic additive schema/retry, failed-DDL rollback, concurrent duplicate reset, late audit rollback, selected-branch isolation, concurrent one-Personal creation.
- Local Chromium at 1440, 390 and 320 pixels: existing bank selection and save, canonical routing from another business, absence of Personal branch/selector controls, preserved Business return context, warning/typed confirmation/acknowledgement, scoped reset with other branches retained. All external browser requests blocked. Only synthetic local records were reset.
- Desktop/mobile screenshots and machine-readable browser report: [evidence](evidence/finance-personal-reset-20261016/).
- Production pre-release snapshot: counts and full-row fingerprints of all 31 pre-existing Finance tables, excluding the release marker. Post-deploy comparison will be recorded below.

## Deployment verification

Pending release verification. Target: existing Client Hub service srv-da7ti2psrm7s73dh9i2g, main, https://app.kilasworks.id. Auto-deploy is disabled; one explicit deploy follows the approved main push. Authenticated production UI access from this environment is unavailable; local authenticated browser coverage is recorded above. No production reset/prepare endpoint or transaction is used for verification.
