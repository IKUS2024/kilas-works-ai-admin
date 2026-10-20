# Expense main picker: actual roots only — 2026-10-20

The owner clarified that Misc/one-time is the last correct default root; the child entries appearing beneath it must disappear from the MAIN picker. Fuel means petrol, not Food. This correction targets relationship type, not labels, positions or a category range.

## Cause and correction

Release dd75cd2c explicitly iterated child options whose parent had `data-picker-hidden=true` and appended each as `data-expense-root`. This UI promotion was incorrect. It was intended to preserve English choices after hiding Indonesian parents, but violated the required hierarchy. The underlying database parent/child links were never changed.

The second iteration is removed. The main view now comes exclusively from visible parent options, which the shared template builds only from rows with no `parent_category_id`. Every child, including legacy children of hidden parents, stays out of the main list. Legitimate custom English roots remain selectable even if their label is Fuel, Parking or Internet. Food remains untouched. Children under canonical Transportation and other visible roots keep their existing submenu, IDs and selection behavior.

Only JS presentation, its asset versions on Add/split/dedicated Edit/category-only Edit entrypoints, and browser expectations change. Backing selects retain historical choices so unchanged Edit can retain the original IDs and read-only child display. No category, active flag, hierarchy, transaction, allocation, recurring rule, report, balance or Income behavior is changed. No production database migration or write is required. Reverting the UI change is possible; no irreversible deletion is performed.

## Read-only production evidence

Business10 / branch16 currently has 18 promoted English children of hidden legacy parents, in both English and Indonesian UI contexts: AI / API, Freelancer, Gas, Google Ads, Hosting / Domain, Influencer / KOL, Internet, Laundry, Maintenance, MDR / Payment Gateway, Meeting / Client, Meta Ads, Packaging, SaaS / Subscription, Software, TikTok Ads, Transport Online, Vendor / Outsourcing. All 18 promotions are removed; the ten actual visible roots remain.

Personal:9 / branch23 currently has ten proper Expense roots and no promoted legacy children in the examined snapshot. Its canonical Transportation id18584 retains Fuel18585, Vehicle Servicing18587, Tolls18588, Ride-hailing18589, Parking18590, Vehicle Loan Payment18586, Car Rental18614. Those children are unchanged. Separate old legacy child ids18484/18485/18486 are children of Transportasi9432; they are not the canonical children. The exact reported Personal duplicates were not reproduced in the current production snapshot; the same promotion path is exercised with the full reported label list in both synthetic contexts. This diagnosis does not assume a cache cause without browser evidence.

## Tests and limits

- 67 component/regression tests and 33 subtests pass.
- 16 browser combinations pass: Personal/Business, English/Indonesian, 320/390/768/1440 px. Every rendered main-choice ID must equal a visible real-parent option ID; no orphan leaf can pass this assertion.
- Fixtures include hidden-parent children Fuel, Parking, Tolls, Car Rental, Public Transport, Gas, Internet, Medical Care, Medicine, Laundry and Studio rental. None is promoted. Same-label real custom roots are preserved. Canonical Transportation's complete child list remains accessible, including after switching/back/scrolling. Add, both split rows, historical Edit, read-only child, Date/Amount bounds and previous Income alignment remain covered. Selection QA makes no POST requests and protected fixture tables stay unchanged.
- Actual production category snapshot replay: 4 real-browser cases (both scopes × English/Indonesian) pass through the shipped JS. Every main-choice ID is a real parent; both contexts show ten roots, Food remains, Misc/one-time is last, Business loses all 18 promotions, and Personal keeps all seven canonical Transportation children. Snapshot data is injected only into local DOM options; there are no production requests or writes.
- 8 legacy browser combinations pass, preserving the existing 23-to-10 Personal seed behavior.
- Production protection: seven scoped table counts/fingerprints captured before deployment and compared after LIVE. No production QA transaction/category writes or paid calls.

Runtime cannot access authenticated production DOM: outbound HTTPS to app.kilasworks.id is blocked by proxy CONNECT403, and no cloud browser is exposed here. Parent must refresh the production routes after LIVE and confirm the main list stops at Misc/one-time while canonical submenus still work. Local browser checks use Chromium, not physical Safari.
