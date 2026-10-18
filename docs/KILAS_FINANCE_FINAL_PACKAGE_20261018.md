# Finance final catalog, cascading choice and receipt review — 2026-10-18

Baseline: `a4641caca340bdc10113c27f145a304b82c7c04c`. Translator, sandbox sources/configuration, financial pricing, existing package grants and ledger history are unchanged. No paid API/model/VM test, production financial save, new infrastructure, credential change or permanent category deletion was performed.

## Delivered scope

| Request | Result |
| --- | --- |
| Cascading category selection | One visible category summary opens parents, then immediately only that parent's children. Selecting a child fills parent/child summary. No separately visible all-child dropdown. Add/Edit Expense and every split use the same widget; changing parent clears the old leaf. Empty parents support adding a scoped child or selecting the empty parent. Existing server relationship/tenant/branch validation remains authoritative. |
| Final Personal defaults | Version3 contains exactly the 11 requested roots and 45 children below. Known immutable built-in identities are reused only for unambiguous same-parent meanings; no historical transaction recategorization. Customer/renamed names remain verbatim. Business defaults remain separate. |
| Old defaults | Proven obsolete defaults are temporarily retired with an existing-table reversible version journal. This is **not permanent deletion**. Custom/unknown rows and children of customer-owned parents remain intact. Specific permanent cleanup approval is pending. |
| Cash Flow | Local heading/picker spacing, padding and typography fix; no card dimensions or dashboard redesign. Actual “Last 6 months” label fits in both scopes at all four widths. |
| Business receipt scanner | Business Quick Actions → photo → signed, owner/business/branch-bound review → editable date/total/payee/available category → explicit confirmation. Analysis never saves a financial transaction. Existing receipt-hash/business-lock idempotency prevents duplicate confirmed expenses. |
| Business Income | No category or Source/Customer fields/requirements. Receiving account is required and credited once. New manual income gets an internal generic FK; edits retain original category/customer/counterparty when omitted. Personal Income still requires its description; Expense requirements are unchanged. |

### Exact final Personal order (English UI)

1. **Home / Rent:** Rent; Association Fee; Property Tax; Mortgage; Household Staff; Home Services.
2. **Utilities:** Electricity; Gas / Heating; Internet; Garbage; Laundry; Cleaning. No Water/IPL default.
3. **Personal Items:** Clothing; Makeup; Skincare; Kids / Toys.
4. **Food:** Groceries; Restaurants; Fast Food.
5. **Entertainment:** Movies; Subscriptions; Events; Games.
6. **Transportation:** Fuel; Vehicle Servicing; Tolls; Ride-hailing; Parking; Vehicle Loan Payment; Car Rental.
7. **Insurance:** Health Insurance; Vehicle Insurance; Home Insurance.
8. **Medical:** Cosmetic Procedures only.
9. **Misc / One-time:** Gifts & Donations; Special Purchases; Other.
10. **Holiday:** Flights; Accommodation; Local Transport; Food & Drinks; Activities & Tickets; Visa & Travel Documents.
11. **Bank Charges:** Tax; Administration.

Built-ins follow App Language (id/en/es/zh), with existing English default. Names of customer-owned records are not automatically translated. A same-named custom root can remain alongside a separately identified default; no name-only merge or deletion is inferred. An intentionally archived default remains archived. A required item retired only by the previous system catalog can return only with journal evidence and no user-deactivation audit. The finite `v3.misc.2` identity is exempt from the legacy generic-catch-all filter/retirement; unrelated old catch-alls remain protected by the existing rules.

Combined old Insurance/Medical categories are not assigned to new narrower meanings; old restaurant/fast-food combined entries are not guessed into Restaurants or Fast Food. Existing historical IDs and hierarchy links stay unchanged. The new version journal records metadata before-states and created IDs; refresh does not reseed or reset custom order, name, icon or archive choices.

## Receipt boundaries

Only the receipt flow was reopened; analyst/operator/assistant/bank-import routes remain archived. Upload processing requires existing paid-package or fixed-end sponsorship eligibility and the existing shared Premium reservation/settlement ledger. No free allowance, quota, funds or pricing were changed.

The adapter makes one exact `gpt-6-luna` request using the existing OpenAI transport, strict structured JSON, no tools, max2048 output tokens, conservative200000 input-token reservation forecast, original safely validated/normalized photo bytes and at most100 available leaf-category path labels. Read-only model/image availability is checked before dispatch. No model/provider fallback or paid automatic retry. A repeated normalized photo operation does not create a second provider request; unknown-cost failures retain conservative exposure in the existing ledger. Provider outcomes are unverified by live synthesis in this release.

JPG/PNG/WebP input uses the existing 20MiB validation/normalization and pixel/decompression bounds. Confirmation uses exact currency minor units; IDR draft display no longer mistakes minor units for whole rupiah. Account and final category remain validated in the current branch. Unsupported/unavailable suggested categories are cleared for human selection while retaining the readable extracted facts. Signed review expires after the existing10minutes, is tenant/user/branch bound, contains no file bytes, and cannot save without explicit confirmation. The existing scanner is request-local: receipt bytes are not archived by this review path; its page discloses that limitation. Manual expenses remain available when AI entitlement, capacity or provider access is unavailable.

## Focused verification

- **60 unique Python contracts passed:** category reference8, purchase plans14, expense entries9, approved revisions17, new final-package9, and3 selected Personal canonical/conflict tests. The final12-test guard/package run is a subset rerun, not additional unique coverage. Earlier exact catalog expectations were updated because the owner superseded v2 with v3; no financial safeguard assertion was removed.
- **8 actual local browser combinations passed:** Personal/Business ×320/390/768/1440. They exercise parent→children selection, every selectable parent at320, empty-parent Add child, parent clearing, Add/Edit/splits, management parent constraints/name/icon/order/archive and unchanged historical allocations. Business320 also tests real upload/review/edit/explicit-save endpoints with provider/usage mocks; no automatic ledger save and exactly one confirmed expense.
- A final one-page browser check passed receipt-origin Expense Edit with the shared cascade, English Back-to-Category label and no JavaScript errors; special payment editing keeps its existing accounting service.
- Separate read-only browser sizing check measured the actual “Last6months” text at approximately69–72px versus101–107px usable width for all8 combinations; no clipping, overlap or horizontal overflow. Mobile Cash Flow screenshot inspected. Existing cards were not assigned new dimensions.
- Existing mock HTTP denial prevents accidental external calls. New tests cover active-package denial, CSRF, foreign accounts/categories/tokens, invalid photo bytes, idempotent confirmation, unavailable suggestions, incomplete provider response, unknown-cost settlement, no paid retry, Business Income account credit and preserved legacy edit fields, reversible catalog metadata/history, archive persistence and read-only cleanup snapshot conflict detection.
- JavaScript syntax, locale JSON loading and `git diff --check` passed. Local screenshots/logs: `/tmp/kilas-finance-final-browser/`, `/tmp/kilas-finance-final-core.log`, `/tmp/kilas-finance-final-new.log`, `/tmp/kilas-finance-final-guard.log`, `/tmp/kilas-finance-final-browser.log`, `/tmp/kilas-finance-cashflow-final.log`.
- No authenticated production browser or physical Android/iOS test; mock extraction does not establish real receipt recognition quality.

## Permanent cleanup: pending specific approval

Read-only inventory found95 Personal catalog identities:81 proven unchanged built-ins and14 custom/renamed. Of the81,34 are retained by the final mapping,14 children of customer-owned parents are protected, and only the following33 are removal candidates. The14 custom/renamed identities are also untouched. Unknown categories outside this provenance catalog are excluded.

| Old group | Candidate name and exact ID |
| --- | --- |
| Home | Maintenance18479,18496; Mortgage-2nd18512 |
| Food | Dining Out18482; Restaurant/Fast food18499 |
| Personal | Toiletries18492,18509; Personal Care18493,18510; Personal items18526; Books/Magazines18528; Beauty Care18529 |
| Entertainment | DVD rental18532; Music18533; Appstore18534; Tune Core18535; Musik Produce18536 |
| Combined Insurance/Medical | Parent18544; Insurance-Auto18545; Insurance-Home18546; Insurance-Medical18547; Medical Expenses/Co-pay18548; Treatment18549 |
| Misc | Flights18551; Hotel/Lodging18552; Gifts/Charity18553; Family18554 |
| Obsolete roots | Investment18555; Salaries18557 |
| Utilities | Telephone18518; CellPhone18519; Cable/Dish18521; Water18522 |

Every candidate currently has one scoped setting and **zero** transaction, split-allocation, budget, Bill or installment references. The combined parent has five children, all in this candidate set; no retained child would be detached. Recovery snapshot contains33 base rows,33 settings,33 identity rows,26 preferences and30 hierarchy rows, with no private transaction contents or secrets.

Committed recovery/inventory file: `docs/qa/finance-final-catalog-cleanup-20261018.json` (also `/tmp/kilas-finance-final-cleanup-inventory.json`). SHA256: **`ce81b13dcde3a2f716daa7d421e195055c7ed7c6244d7800c3dc224fe3afd0e2`**. It captures pre-v3 metadata; reversible retirement changes active metadata, so any later execution requires a new reviewed snapshot and comparison, allowing only the documented catalog retirement delta—not arbitrary changes.

`finance_category_cleanup.py` has only read-only snapshot/dry-run functions, no delete executor or public route. It checks authenticated Personal ownership, unchanged built-in provenance, no customer-owned parent, a single scoped setting, current references/descendants and exact snapshot equality. Changed references/provenance/snapshot or another owner fail closed; the result explicitly states permanent deletion is not authorized.

Proposed **separately approved** operation: revalidate the exact33 IDs and backup checksum under the existing transaction lock; require zero fresh references and no outside children; remove only their scoped preference/identity/setting/hierarchy metadata, then child/base category rows before the combined parent, in one atomic transaction. Never move/delete financial records or assign ambiguous history. Preserve the version journals and immutable recovery export. Restore would explicitly reinsert original IDs/base rows/settings/identities/preferences/links from the reviewed export in dependency order. There is **no normal-product undo for permanent deletion**. This operation has not been implemented or executed by this release; archive is not being presented as final deletion.

## Release verification

Before-release read-only baseline:69 transactions / `e439175f48160db657b0fe659a92a196`;38 accounts / `6e92d18b2cbaa67f7a05409436e0102b`;863 existing hierarchy links / `ccba4b2aedadf486ad84ceb0440eca7c`;maxcategoryID18557. No new schema migration is needed: v3 uses existing0109 preference/version tables. After LIVE verify exact SHA, unchanged old financial/link aggregates, no startup errors, and unchanged small-execution ON/large OFF/$5/pins. Final record: `/tmp/kilas-finance-final-live-evidence.json`.
