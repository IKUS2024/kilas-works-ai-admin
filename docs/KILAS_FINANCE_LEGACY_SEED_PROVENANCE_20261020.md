# Legacy Personal seed provenance correction

Production cloud-browser review found 23 effective roots after v4: ten requested
English defaults plus all thirteen roots from the original Personal seed.
Fresh-seed coverage alone did not establish the legacy workspace result.

The old definition is in commit `42492996`. Importer `9655f501` marked exact reused
choices `__customer_owned__` conservatively, without evidence of a customer edit.
Other original seed roots had no `finance_catalog_items` record. The v4 metadata
rule therefore left this old initial seed visible.

The correction adds a read-only proof of the original initialization batch:

- Personal workspace identity and creation audit match its owner and branch.
- All 13 original expense roots and all five original Income roots exist as
  unchanged scoped settings created within five seconds of that workspace.
- Storage names still match scoped labels, and raw category updates predate the
  scoped seed mapping.
- All five new Income roots plus the new Expense roots share one precise
  creation audit transaction timestamp. A name alone or a coarse timestamp does
  not establish provenance.
- Actual edit/archive audits and later custom descendants remain protected.

Only proven seed mappings become hidden choices. Metadata markers, stored names,
active schedule flags, categories, hierarchy, transactions and allocations are
not changed. The same enabled/disabled v4 policy reverses this additional view
filter. Business scopes and incomplete/ambiguous batches do not qualify.

A read-only production PostgreSQL snapshot reproduced the reported 23 names in
exact order with the old rule. Running the same selector implementation with this
correction on that snapshot produces exactly Home/Rent, Food, Utilities, Personal Item, Transportation,
Entertainment, Medical, Holiday, Bank Charge, Misc/one-time on that same snapshot.
The snapshot contains no copied transaction contents and is kept outside Git.

Validation: 64 focused tests plus four negative subtests; eight Chromium journeys
with this exact legacy shape, single/split pickers, English/Indonesian locales,
and 320/390/768/1440 widths. Fixture snapshots prove zero stored-row changes from
selection. Negative cases preserve missing/mixed/coarse audit evidence, actual
edits, a later custom child, and Business scope. The two-bar UI is unchanged.
