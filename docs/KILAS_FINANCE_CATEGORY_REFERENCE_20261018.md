# Finance category reference revision — 2026-10-18

## Scope and behavior

This release builds on `ff1c81f6f562a4a65441c1e54b75b97caaf20f40`; its Translator runtime and sandbox configuration are unchanged. No paid API calls or production financial test records were used.

Personal's reference catalog contains 11 roots and 43 children, in the requested order: Home/Rent; Utilities; Food/Groceries; Departmental; Entertainment; Car/Auto; Insurance/Medical; Misc/One-time; Investment; Bank Charge; Salaries. The final three have no seeded children. Business retains its separate business catalog. Existing custom/historical extras remain available; the reference count does not imply their removal.

| Requirement | Implemented evidence |
| --- | --- |
| Dependent subcategory below category | Add/Edit Expense and every split row filter by actual parent; changing parent clears an invalid child; server validates scope, owner and relationship. |
| Add child to selected parent | Actual create route and management form retain parent; identically named children under different parents remain separate. |
| Category/subcategory management | Scoped Add/Edit name and icon, explicit edit mode, bottom Add, sibling reorder, Cancel/Save, and archive-only removal. 18 finite monoline icon choices. |
| Reference order and localization | All 11/43 English reference labels independently asserted. Built-ins localized for id/en/es/zh; real customer renames become custom and remain verbatim. Icon-only saves preserve built-in localization. |
| Stable history | Proven unchanged built-ins reuse IDs and canonical identities; no name-only custom merge, relationship deletion, or ledger mutation. Version journal records catalog metadata changes. Archived defaults stay archived. |
| Legacy edits | Only the actual existing transaction's unchanged allocations/total can retain archived categories. New/changed selections must be active and valid. Active Bills in any affected Business branch block category archival. |
| Legacy Personal guard | New catalog does not turn empty legacy seed datasets into populated conflicts; genuinely populated conflicts remain protected. |

The catalog upgrade uses existing provenance metadata rather than guessing from names. A customer-renamed parent and its descendants remain intact. Known obsolete default children are archived only where provenance and dependent-Bill checks permit; historical IDs/links remain. Reused canonical keys stay stable for old-code compatibility. Unknown custom rows are not deleted or automatically consolidated.

## Additive schema

Migration `0109_finance_category_preferences` creates only the empty preference and catalog-version/journal tables, using the existing targeted checksum-locked release installer. PostgreSQL migration SHA256: `4cb1a6041437930ff681dd5b18708d22c18026c44087713ac35e0eddb3052f57`. No financial transaction backfill, reset, merge, or destructive migration. Normal authorized catalog initialization later records preferences/version metadata.

## Verification

- 51 unique focused Python tests passed: category reference 8, purchase plans 14, expense entries 9, approved revisions 17, and 3 selected Personal canonical/conflict tests. The 8 category/security tests passed again after the final canonical-key compatibility correction; this is a subset rerun, not additional unique coverage.
- Actual local Flask/browser flow passed Personal and Business at 320/390/768/1440 (8 combinations), with no overflow or JavaScript errors. At 320 it exercised Add/split Save/Edit dependencies, name/icon save, persisted reorder, child add/edit, archive of a used category, and unchanged archived-allocation edit without duplicate debit. The four 320/390 combinations passed again after the mobile edit-row spacing fix.
- JavaScript syntax and `git diff --check` passed.
- Browser evidence: `/tmp/kilas-category-reference-browser/categories-{personal,business}-{320,390,768,1440}.png` and matching `editor-*.png`. Logs: `/tmp/kilas-category-final-tests.log`, `/tmp/kilas-category-security-final.log`, `/tmp/kilas-category-browser-wide.log`, `/tmp/kilas-category-browser-mobile-final.log`.
- All 11 Library reference metadata records resolved, but the official file transfer failed before image bytes were available. Their pixels were not inspected; no visual-parity claim. Latest locally rendered 320px management screenshot was inspected.
- Physical Android/iOS and authenticated production UI were not exercised. Local synthetic browser/accounting fixtures do not prove those environments.

## Production integrity baseline and release check

Read-only pre-release aggregates: transactions 69 / `e439175f48160db657b0fe659a92a196`; accounts 38 / `6e92d18b2cbaa67f7a05409436e0102b`; category hierarchy 824 / `19aaccfbb8fd53130b5059c0eda82c5b`; maximum existing category ID 18510. Compare the existing hierarchy using `child_category_id <= 18510` so legitimate new seeded links are distinguished from any changes to old links.

The release verification record is `/tmp/kilas-category-reference-live-evidence.json`: exact deployed SHA/time, migration checksum, old financial/link aggregates, error logs and unchanged sandbox readiness. It is populated after LIVE. Reload the page to use the new assets/catalog. Genuine multiple populated Personal contexts still require explicit reconciliation; this release does not choose or merge them.
