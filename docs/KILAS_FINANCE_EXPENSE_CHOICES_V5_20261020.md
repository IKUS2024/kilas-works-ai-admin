# Finance Expense choices and Income alignment — 2026-10-20

Scope: the owner's three approved revisions, built on main `89c36d671a7ca2880043cd6cd702913e35c333bb`. VoiceOver alternate takes, Translator playback, AI presentation and Creative Services remain ancestors and are not edited.

## Effective category policy

The previous v4 retirement deliberately required built-in identity or a provable initial Personal seed batch. Read-only production diagnosis found Personal:9 already has ten English roots, while Business has 25 roots and 56 Indonesian Expense labels still eligible before this revision. Business's old settings lack catalog identity, so provenance-based retirement could not remove them safely. Custom descendants also intentionally protected old parents. This was context/data behavior, not a browser cache changing the catalog.

This revision adds an Expense-picker-only flag calculated from the effective displayed label after English aliases. It matches complete audited Indonesian words, not substrings, IDs, positions or a category range. English labels remain available, including the English descendants of hidden Indonesian parents. Those descendants are presented as direct English choices while submitting their original parent/child IDs; no stored hierarchy is changed. Shared words Air, Film, Gas, Internet, Laundry, Bonus and English names containing a substring (e.g. Vegas, SewaBali Studio) are preserved. The specific old `Air` child under `Utilitas` is Indonesian Water and is hidden by exact label and parent context; standalone English Air and Air under Utilities are preserved.

No category/settings/raw active flag is deleted, renamed or changed by this policy. No ledger transaction, allocation, budget, recurring rule, account, reporting query or balance calculation is migrated. Historical selected IDs remain present on Edit and retain their existing relationship. Category management remains available. Reverting this presentation policy restores the hidden choices. Income categories are not filtered.

Read-only production snapshot replay through the real catalog decorator: Personal retains 52 English choices (10 roots +42 children); Business retains 35 English choices including 18 English children of hidden parents, and hides 56 Indonesian labels. The raw snapshot and ID mapping are outside Git in `/workspace/finance-picker-evidence/`.

## Interaction and layout

All shared Expense picker entrypoints (Add, split, dedicated Edit and category-only Edit) start with the category list. Choosing a parent replaces the panel with only that parent's child list and a Back action. Back/reopen resets the panel scroll and returns to the category list. Switching parents clears stale child selection. Selected subcategory remains a read-only status display. AJAX category refresh includes the same policy flag. Static asset versions are bumped on every entrypoint.

An English parent with no remaining visible children can be selected directly; single and split validation use the same visible-child rule. Existing historical selection retention remains authoritative. English children under hidden parents still use actual IDs and existing relationship validation.

Income transaction description, notes and category/account text align left; amounts align right. Income category summaries use full-width rows with bounded name/amount columns. Large amounts wrap inside their column rather than squeezing a name into vertical letters. Header totals stay bounded. Existing receipt, Date/Amount gap, Save/Cancel and split controls remain.

## Validation

- Component/regression: 67 tests and 33 subtests passed, including historical references, balances/reports, account isolation, split validation, initialization, actual legacy seed provenance, exact English aliases, ambiguous word protection and AJAX refresh scope.
- Browser: 16 combinations, 320/390/768/1440 px, English/Indonesian, Personal/Business. Real local Flask routes and synthetic SQLite. Add, both split rows, historical Edit, root/child/back switching, scroll filtering, read-only selected child, English orphan selection, Income copy/amount alignment and no overflow. No browser POST requests during selection QA; protected fixture tables remain unchanged.
- Exact legacy seed browser: 8 combinations pass, existing 23-to-10 Personal seed, single/split/read-only/no writes.
- Receipt preview browser regression: 14 checks passed, including saved bytes unchanged and Save after removing an image; logs and screenshots are in `/workspace/finance-picker-evidence/` after final verification.
- Real production data read-only mapping and seven protected table count/fingerprints captured before deployment, to compare afterward.

Production routes for owner review: `/business/10/finance?branch_id=23` (Personal) and `/business/10/finance?branch_id=16` (Business); append `view=transactions&direction=INCOME` for Income. Business initial picker has 28 English entries: ten roots and eighteen English descendants of hidden parents. The old ten-only range restriction has been canceled.

Production target verified: My Workspace `tea-da34t2gu01pc73ft7uf0`, Client Hub `srv-da7ti2psrm7s73dh9i2g`, repo IKUS2024/kilas-works-ai-admin, branch main, root client-hub, auto-deploy OFF. Deployment must be manual after push; exact SHA and Render LIVE status are checked. No production transaction/category creation or deletion is performed for QA, and no paid provider calls are made.

Limit: browser coverage uses Chromium in the selected execution environment, including iPad dimensions; it does not claim physical Safari validation. This runtime has no authenticated cloud browser. Parent should refresh production Personal and Business routes after LIVE, rather than reopen a stale modal. Production read-only snapshot replay is data-mapping proof, not a claim of observing the authenticated production DOM.
