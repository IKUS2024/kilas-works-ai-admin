# Finance transaction Type filter correction — 16 October 2026

The post-release screenshot showed a redundant Type selector on the dedicated Expense list. This follow-up removes that selector from both Income and Expense lists, in both Personal and Business modes. A hidden canonical direction preserves the existing page context. The generic all-transactions list retains its useful Type selector.

Account, literal search, category, period and currency filters survive filter submission, month links and pagination. The period dialog now retains the transaction-list context, and its month/range canonical redirects retain account/search/category filters. Month navigation resets pagination to the first page. No ledger service, calculation, schema, identity, upload, transfer or unrelated module implementation changed.

Validation from main baseline `777b543b3689c95a865f33bac35a3a6003229c32`:

- **73 focused tests PASS**, zero failures/errors/skips: six new direction-filter tests covering all four mode/direction combinations, 17 approved Finance revision checks, 46 dashboard regressions and four locale checks. New cases cover hidden direction, generic selector retention, filter submission, pagination, month links and month/range period redirects.
- **Chromium PASS at 1440, 390 and 320 pixels**: 12 mode/direction combinations, actual filter submission and month/period navigation, plus the original income-save, transfer and identity browser acceptance. External browser requests remain blocked; every write uses a local disposable fixture.
- [Business Expense screenshot](qa/finance-direction-filter-20261016/business-expense-mobile.png), [Personal Expense screenshot](qa/finance-direction-filter-20261016/personal-expense-mobile.png), [browser report](qa/finance-direction-filter-20261016/browser-report.json).

Commands:

```sh
python client-hub/tests/run_finance_regressions.py test_finance_direction_filters test_finance_approved_revisions test_finance_home_dashboard test_ui_finance_locale
FINANCE_QA_OUTPUT=/tmp/finance-type-filter-browser python client-hub/tests/finance_approved_browser_qa.py
```

Release target remains the existing Render Client Hub `srv-da7ti2psrm7s73dh9i2g`, workspace `tea-da34t2gu01pc73ft7uf0`. No production QA writes or new migration are required. The application commit and LIVE deployment ID will be reported after verification. Direct external HTTP verification remains blocked by the execution proxy; no authenticated production browser success is claimed by this local browser report.

## Verified release

- Application commit `edb638c298097906539cb25835b6aeed0d1e17cc` was pushed directly to main. Existing Client Hub deploy `dep-db95nk2jnfac73alu7qg` reports **LIVE**, finished **2026-10-16 17:17:01 UTC**, at that exact commit. Worker startup independently confirms the same SHA.
- Post-release read-only comparison: **31/31 Finance data tables unchanged**, including complete transaction Notes and internal transfer history. Counts and full-row fingerprints match the pre-release capture. No production QA workspace, transaction, account or other financial record was created or changed by this follow-up.
- Render error-level query covering 17:16:00–17:17:35 UTC returned no logs. No new migration or configuration change.
- User URL: https://app.kilasworks.id. Direct HTTPS smoke remains blocked by the execution proxy; the screenshots above are local synthetic browser evidence. Parent production-browser verification can open the existing authorized workspace with `view=transactions&direction=EXPENSE` or `direction=INCOME` and inspect the search/account filter area.
- The evidence checkpoint changes documentation only; deployed application source remains identical to `edb638c`.
