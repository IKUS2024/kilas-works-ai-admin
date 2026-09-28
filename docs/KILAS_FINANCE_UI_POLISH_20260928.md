# Kilas Finance UI polish — 2026-09-28

## Scope

This release is a conservative presentation-only refinement of the authenticated Kilas Finance shell. It preserves the existing dark/orange visual identity, navigation, terminology, workflows, templates, JavaScript, routes, calculations, persistence, tenant boundaries, invoice/payment behavior, and Finance assistant behavior.

The implementation changes only `client-hub/static/finance_ui.css`. No Kilas Assist file, Python file, template, JavaScript file, migration, schema, API, or data task changed.

## Verified audit findings

- Secondary text, table headers, metadata, status pills, and form labels were frequently below a comfortable reading size.
- Several context controls, tabs, pagination links, and mobile navigation targets were 32–38 px high.
- Mobile forms used 13–14 px inputs, increasing zoom and input friction on touch devices.
- Dense transaction, invoice, report, bill, and assistant surfaces needed more consistent type, spacing, and control sizing.
- The invoice editor retained an unnecessary outer card treatment on mobile around its existing section groups.
- Long headings and currency values needed explicit wrapping or numeric stability without changing their content.

Detector suggestions were reviewed separately from the rendered audit. The final Impeccable detector returned `[]` for the changed stylesheet; visual inspection remained the source of truth.

## Changes

- Raised the Finance base type and secondary text sizes while retaining compact data density.
- Standardized headings, cards, form controls, buttons, tabs, pagination, tables, status markers, empty states, and dialog close controls.
- Added 44 px touch targets at phone/tablet and coarse-pointer sizes.
- Increased mobile input text to 16 px and improved placeholder contrast.
- Improved disabled, busy, and focus-visible feedback.
- Simplified the mobile invoice editor container while preserving every field and action.
- Improved mobile Finance AI readability and composer controls.
- Kept the cash-flow totals readable in a single column below 400 px.

## Responsive evidence

The disposable authenticated Finance fixture was inspected at 360×800, 820×1180, and 1440×1000 across 14 routes: Home, transactions, accounts, bills, budget, invoice list, customer list, new invoice, invoice settings, payees, reports, bank imports, Finance AI, and receipt upload.

- 42 route/viewport visits returned HTTP 200.
- No document-level horizontal overflow was detected.
- No JavaScript page errors were recorded.
- Undersized interactive instances in the automated scan fell from 972 to 607; remaining matches include inline links and controls whose usable parent target is larger.
- Text nodes below 12 px fell from 385 to 320; remaining matches are compact chart/calendar annotations and inherited non-primary metadata.

Representative before/after screenshots and raw metrics are in `docs/qa/finance-ui-polish-20260928/`.

## Verification

- Impeccable detector: clean (`[]`).
- Fast Finance UI gate: 41 tests plus 46 subtests passed.
- Covered Finance route rendering and style isolation, dashboard values/navigation, invoice editor behavior, CSS loading order, login exclusion, period/currency preservation, invoice partial/full payment reconciliation, recurring payment projection, search/pagination, branch isolation, and migration replay.
- A broader Windows run was stopped at user direction. Observed failures were missing local `tzdata`, Windows SQLite handle cleanup, or PDF/native-environment issues; no product assertion was tied to this CSS change. `tzdata` was installed only in the disposable QA interpreter.

No production migration or data reset is part of this release.
