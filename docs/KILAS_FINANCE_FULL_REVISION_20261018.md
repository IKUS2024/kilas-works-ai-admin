# Finance full revision — 2026-10-18

Scope: owner written Finance requirements09:07UTC. Translator is paused indefinitely; its incomplete work remains only on local `translator-hold-wip-20261018` at7789f17f. No Translator or sandbox implementation/configuration is included.

| Requirement | Implemented behavior / evidence |
| --- | --- |
| Category/subcategory | Dependent subcategory directly below category in ordinary and every split row. Bottom Add Category/Subcategory actions use existing scoped CSRF endpoints. Real browser creation/parent linkage passed. |
| Personal defaults | Six ordered roots: Housing (Rent, Maintenance); Food & Groceries (Groceries, Dining Out); Transportation (Fuel, Parking, Tolls, Car Rental, Public Transport); Utilities (Electricity, Water, Gas, Internet); Health (Medical Care, Medicine); Personal Items (Clothing, Toiletries, Personal Care). Shoes belong to Clothing. Four-language known-built-in labels and exact children/order tested. |
| Business/custom categories | Existing seven business expense roots remain separate; built-in identity metadata permits localization without translating custom names. Exact existing same-parent choice can be reused without guessing provenance. Unknown legacy semantic synonyms/custom names remain available and verbatim: no unsafe name-only merge, rename, deletion, or historical relationship rewrite. Therefore this release does not claim all historical duplicates were removed. New identity/order metadata is additive/reversible. |
| Splits | Toggle precedes category and replaces single controls. Server-authoritative integer minor units, scoped leaf validation, exact sum; one parent debit, allocation-based reports. 100.01=50+50.01 and invalid totals covered. |
| Installments | Collapsed Additional Options after Notes; enabled settings only when selected. Months/years, monthly/quarterly/yearly/custom dates, derived count, optional per-payment amount, exact final residual/EOM. Purchase Amount is total. Save creates a finite unpaid plan/Bills schedule, **no purchase ledger debit**. Existing manual Mark Paid posts each installment once; splits aggregate to total. No bank payment, loan account, or automatic payment. Plan detail retains payee/notes/private receipt. Future schedule/amount/category edits that break total are rejected; linked account cannot move scope independently. |
| Dashboard | Both scopes show Income, Expense, Accounts, Bills, Invoice, Recipients in that order;3 columns wide/2 phone. Existing Budget remains below. |
| Recurring Bills | Add/Edit Begin next month; end date or until stopped. Month-end anchor/leap logic, unpaid projection, idempotent manual payments, existing paid history retained after future edit. |
| Expense fields/list | Photo/category/subcategory/split/date/amount/pay-from/optional payee/notes only; legacy Description preserved hidden. List description left, tabular amount far right. |
| Account filter | Compact dynamic selector immediately submits GET; no Apply/repeated labels/account hardcode. |
| History | No transaction-history redesign/deletion. Existing revisions retained. |

Accounting: cash basis. A20M IDR purchase over1year monthly produces12 unpaid scheduled Bills whose integer amounts total20M; only actual manually marked-paid installments affect expense/account reports. Saving or retrying a plan does not debit the purchase total. Personal is one canonical owner dataset; Business remains selected-branch scoped. Payload-bound atomic submission uniqueness, stale edit checks, auth and receipt private routes remain.

Schema0108 adds four empty tables only: `finance_catalog_items`, `finance_installment_plans`, `finance_installment_items`, `finance_installment_receipts`. Startup uses existing checksum-locked targeted installer, not historical migrations/backfill. PostgreSQL SHA256: `e15c0dfdae3578274ecb069dace9273f3fbf45fb1f1235441601f52e49cf8bb4`. Normal user access can lazily seed additive category identities; no release transaction/account/history backfill. Receipt JPG/PNG/WebP uses existing20MiB input validation/normalization,4MiB stored ceiling, shared20MiB/business64MiB/global capacity, private downloads, no OCR.

Validation:
- Final combined **63 PASS**: purchase plans14, ordinary expense entries, approved Finance revisions, targeted recurring suite. `/tmp/kilas-finance-full-final-tests.log`.
- Two legacy recurring UI assertions fail unchanged on clean e45a16de (retired beta-off gate/old copy), documented and excluded from final63; `/tmp/kilas-finance-recurring-baseline.log`. No new failure concealed.
- Existing expense browser PASS320/390/768/1440, including split/photo/save/edit/download/cancel. `/tmp/kilas-finance-full-expense-browser.log`.
- New browser PASS **8 combinations**: Business/Personal ×320/390/768/1440. Cards/filter/splits/layout; year/custom settings; actual plan save/private receipt/manual payment at320 both scopes; actual recurring Add/Edit at390 both scopes. `/tmp/kilas-finance-full-browser-final.log`.
- Additional targeted Business390 browser PASS after fixing actual bottom-action AJAX method target; category/subcategory persisted linkage, plan settings and recurring workflow. `/tmp/kilas-finance-full-bottom-actions.log`.
- Screens `/tmp/kilas-finance-full-browser/{dashboard,installment}-{business,personal}-{320,390,768,1440}.png`; expense screenshots `/tmp/kilas-finance-expense-browser/expense-{width}.png`.
- JS syntax/diff whitespace pass. All financial fixtures disposable local only. No paid calls, production financial test saves, bank actions, data resets or sandbox changes.
- Physical Android/iOS and authenticated production UI not tested. Reference Library pixels could not be downloaded; confirmed written layout followed.

Pre-release read-only production aggregate: transactions69 fingerprint `e439175f48160db657b0fe659a92a196`; accounts38 fingerprint `6e92d18b2cbaa67f7a05409436e0102b`. Query uses md5(string_agg(row_to_json(row)::text,'' ORDER BY id)); compare same query after LIVE, acknowledging possible genuine concurrent user activity.
