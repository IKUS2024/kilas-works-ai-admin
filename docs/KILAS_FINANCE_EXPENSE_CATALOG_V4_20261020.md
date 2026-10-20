# Expense defaults v4 and two-bar picker

The owner-approved expense defaults, in order, are Home/Rent, Food, Utilities,
Personal Item, Transportation, Entertainment, Medical, Holiday, Bank Charge,
and Misc/one-time. These built-in labels remain English in every application
locale. Income defaults and customer-authored labels retain their existing rules.

The shared picker shows Category/Subcategory over two equal 44px bars. The upper
bar opens the hierarchy and displays only the root category. The lower status
shows only the selected child and has no action, link or tab stop. Receipt stays
on the left; Split Categories follows the bars. Existing Date/Amount spacing,
validation, Save/Cancel, receipt handling and split form contracts remain.

## Data protection

No new schema migration or production QA data write is required. Existing scoped
`finance_category_catalog_versions` metadata stores policy version 4, initialized
under the existing business write lock on normal workspace initialization/use.

Only registered seed identity plus an unchanged stored name and matching parent
can qualify for a built-in alias. Multiple candidates never cause guessed
historical reassignment. Unknown rows, renamed defaults and custom descendants
remain intact. A custom descendant protects its old ancestor from being hidden.
Such context rows are custom exceptions, not additional built-in defaults.

The policy hides superseded proven defaults from new choices and applies English
presentation aliases. It does not rewrite existing category rows, stored display
names, parent relations, transactions, allocations, budgets, installments or
recurring rules. Raw legacy active flags remain available to existing scheduled
posting and retained transaction edits. The journal records the original seed
metadata, newly created IDs and previous presentation preferences. Existing
Income initialization remains separate; old expense seed callers now defer to
the scoped catalog instead of creating unmarked legacy duplicates.

Personal retains its existing approved children in English (42 children under
10 roots; the removed Insurance group contributes no new children). Business
retains only its previously configured seven utility children. No new child
meanings are introduced. Existing custom children are not translated.

The policy is reversible: setting the retained v4 journal's `enabled` field to
false restores old choices and previous presentation preferences, while hiding
only newly created v4 defaults. Categories and history are never deleted. Custom
context protection also applies when reversing. Do not remove the journal or
change customer provenance to force a duplicate cleanup.

## Validation

59 focused fixture tests pass: fresh/legacy catalogs, duplicate provenance,
custom/Income/tenant protection, concurrent initialization, reversal/idempotency,
transaction/split/balance/schedule preservation, retained edit and first setup.
Chromium passes 12 main journeys at 320/390/768/820/1024/1440 pixels across Personal
and Business, eight category-management journeys and receipt regressions.
Screenshots confirm the equal bars and Date/Amount gap. All mutations in these
checks target disposable local fixtures; browser network is limited to loopback.

No native PostgreSQL server is installed in this execution environment; the SQL
uses the existing scoped metadata schema and portable query conventions. Actual
Safari/iPad and authenticated production UI are not claimed verified. The legacy
`test_final_product_flow.py` suite cannot enter its test body because its existing
Phase 6A fixture references removed `finance_receipts.requests`; current setup
paths are covered by the new independent fixture tests instead.
