# Approved Finance revision — 16 October 2026

User authorization covers implementation, direct main push and release to the existing Client Hub. Source baseline: `68211ee3948984c837b935ee34fe7cad15cadc15`, also verified as the previous LIVE commit. Render auto-deploy remains off. No new hosted service, environment change, bank/payment integration, production test transaction, recovery, deletion or business merge is part of this work.

## Result

- Finance pages omit the AI promotional/shortcut strip; other modules retain their existing includes.
- Personal Add Income has description, date, amount, existing receiving account, optional separate Notes. No type/category/customer picker. The required legacy category FK uses a generic compatibility category created only inside a successful save; historical categories and transactions remain intact. Edits preserve the original category.
- Add Expense has a fixed hidden expense direction and retains expense categories, account and notes. Income/source and expense/category summaries include only posted, saved transactions and honor period, account, category and literal search filters. The successful-save redirect preserves those filters.
- Current business remains authoritative. Business name is editable in its header profile; the duplicate business selector is replaced by a collapsed legacy-business switch for existing multi-business users. Branch/Add Branch remain. Additional-business creation is removed for existing Finance users, including the old creation query/POST path. No existing business is renamed, chosen as primary, deleted or merged by release.
- The same header component renders the personal name/photo or current business name/logo, with initials fallback. Identity writes are CSRF-protected and owner-authorized, and use existing user/business identity and protected asset storage. Uploads are limited to 5 MiB JPEG/PNG/WebP with signature and decoded format/dimension checks. Only name and image metadata are writable; credentials and permissions are untouched.
- The currency selector beside Branch is removed. Existing display context and account-native currency parsing remain unchanged. No balance or historical currency rewrite.
- Income/expense/balance use green/red/blue restrained cards, explicit labels and symbols. Computed foreground/background contrast exceeds 4.5:1. The compact budget ring uses actual monthly calculations and shows Not set when no budget exists.
- A small Transfer action below the account cards records one equal debit/credit row atomically. An explicit authenticated branch scope is required, including for direct service calls. Transfers reject identical, inactive, foreign-tenant, other-workspace and differing-currency accounts, invalid/non-positive amounts and future dates. The unique request key plus business row lock prevents duplicate posting across workers. Transfer amounts affect account balances, never operating income/expense totals. Voiding retains history; a replay of a voided key does not recreate money. Accounts linked to transfers cannot be moved across workspaces.

## Schema and preservation

Only additive `0100_finance_approved_revisions` is applied by `finance_schema.apply_release()`: a new internal transfer table and nullable transaction Notes column, with advisory lock, transaction rollback and a checksum marker. Production startup does not replay historical migrations. Previous code and workers remain compatible with the nullable addition. A one-line bank-import replay compatibility change treats absent Notes as NULL.

The 30 existing production Finance tables were fingerprinted through read-only SQL before release. Only row counts and hashes were exported. The new nullable Notes column is excluded from the comparison. See [before evidence](qa/finance-approved-20261016/production-before.json). Deployment and after evidence are recorded separately when verified.

## Verification

- **136 targeted tests PASS**, zero failures/errors/skips: approved changes 17; locale 4; dashboard 46; UI integrity 10; phase 1A 18; workspace corrections 12; FX precision 4; style loading 3; invoice editor 18; Finance baseline 4. Tests use disposable synthetic SQLite and block external IO.
- **Native PostgreSQL 18: 4 PASS** on a disposable loopback Docker database. Includes a deliberate late migration failure with complete DDL rollback, successful apply/retry with exact hashes for every original Finance table, four concurrent independent connections producing one debit/credit, cross-currency rejection, and audit-failure rollback. No hosted QA service or production database was used for these writes.
- **Real Flask/Chromium PASS at 1440, 390 and 320 px**. Checks header mode/position, no shortcut strip/currency button, branch controls, exact personal income field order, save/reload and saved summaries, expense category visibility, transfer POST/history/income exclusion, and protected logo upload. External browser requests are blocked. See [browser report](qa/finance-approved-20261016/browser-report.json), [desktop](qa/finance-approved-20261016/dashboard-desktop.png), [mobile](qa/finance-approved-20261016/dashboard-mobile.png), [income](qa/finance-approved-20261016/income-mobile.png), [transfer](qa/finance-approved-20261016/transfer-mobile.png).
- The archived suite is already red on unchanged main: **577 tests, 276 assertion failures and 54 errors**, chiefly expired raw-session fixtures and retired AI routes. A detached baseline comparison reproduced these results. The Notes regression found by comparison was fixed; there are no additional failure signatures. One locale expectation now checks the business identity rather than the personal name, and the empty-budget expectation now checks Not set. The archived branch-delete helper also retains its existing login-fixture failure. Its production implementation was not changed. [Comparison evidence](qa/finance-approved-20261016/legacy-regression-comparison.json).
- The 27 legacy JavaScript checks report 13 pass/14 fail on both unchanged main and this change, with identical failing names. Actual browser checks cover the new forms and interactions.

Commands:

```sh
python client-hub/tests/run_finance_regressions.py test_finance_approved_revisions test_ui_finance_locale test_finance_home_dashboard test_finance_ui_integrity test_finance_phase1a test_finance_workspace_corrections test_finance_fx_precision test_finance_style_loading test_finance_invoice_editor test_kilas_finance_baseline
python client-hub/tests/finance_approved_browser_qa.py
# The PG rehearsal refuses every non-loopback/non-QA database target.
FINANCE_LOCAL_PG_QA=1 KILAS_FINANCE_BETA=on KILAS_FINANCE_ACCESS_MODE=internal_beta DATABASE_URL=<dedicated-loopback-kilas_finance_qa> python client-hub/tests/finance_approved_postgres_qa.py
```

Limits: Chromium viewport emulation does not certify a physical mobile keyboard/device. Browser writes were synthetic/local; production identity/transaction writes will not be performed for verification. Archived failing suites are disclosed rather than claimed green. The active agent could not switch its running model to the separately requested model setting.

## Production release evidence

- Application commit **`eeae81fa85941885218572493bee1e268e8a8c1c`** was pushed directly to `main` and verified against the remote ref. It preserves all prior commits, including Group Chat.
- Existing Render Client Hub `srv-da7ti2psrm7s73dh9i2g`, workspace `tea-da34t2gu01pc73ft7uf0`: deploy **`dep-db95hbnt5n8s73ec85r0`** reports **LIVE**, finished **2026-10-16 17:03:36 UTC**, at that exact application commit. No other service was deployed; auto-deploy remains off.
- Production `finance_release_migrations` confirms `0100_finance_approved_revisions` with SHA-256 `e6b616f7a2db5dc98cc93833ef705416c77535522efeab63e85198498fbc121c`, identical to the tested local SQL. New internal transfers: **0**. Existing transactions with non-NULL new Notes: **0**.
- At 17:04 UTC, every original Finance table has the **same full-row fingerprint and row count** as before release: **30/30 unchanged**. No real transaction, account, branch or business was created/edited/deleted for QA. [After evidence](qa/finance-approved-20261016/production-after.json).
- Render error-level queries for 17:02:38–17:04:21 and 17:03:36–17:05:41 UTC returned no logs. The new worker startup log independently confirms exact application commit `eeae81fa85941885218572493bee1e268e8a8c1c` at 17:03:37 UTC.
- User URL: **https://app.kilasworks.id**. Direct shell HTTPS checks of the custom domain and service URL are blocked by the execution proxy with `403 Forbidden`; the web tool also cannot access the custom domain. Therefore an external HTTP/production-browser smoke is **unverified**, even though Render reports LIVE and the production schema/data checks pass. [Probe limitation](qa/finance-approved-20261016/http-smoke-limitations.json).
- GitHub CLI check-run lookup returned `Forbidden`; the connector returned no commit statuses. Remote CI is not claimed green. Local targeted **136**, Notes bank-import compatibility **4**, native PostgreSQL **4**, and real local browser checks are the release validation evidence.
- This evidence-only follow-up changes documentation/images only. The deployed Client Hub source tree is unchanged from the verified application commit; no deployment is needed for the evidence checkpoint.
