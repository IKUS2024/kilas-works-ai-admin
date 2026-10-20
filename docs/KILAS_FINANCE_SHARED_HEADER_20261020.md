# Shared Finance header — 2026-10-20

Scope explicitly authorized: polish only the shared upper navigation/context chrome across Finance, preserving everything below it. Baseline main: 59d7b050b81b9fdaaff2531ca92cb6c055cc3096. VoiceOver, attachments, first paint, localization, AI Call and Finance root-picker commits remain ancestors.

## Cause and change

The mobile shell independently stacked sidebar branding/tabs, Home/language, search/notifications/profile, and workspace/branch/month controls. Shared form rules expanded the language selector, while label heights and competing breakpoint rules scattered context fields. Native focus sometimes exposed only part of the last scrollable tab.

A Finance-only `finance-chrome` boundary now contains the existing shell. Its dedicated styles affect only that boundary. Home, profile, bell and a compact language control share one mobile row; search uses a full-width row when present. Workspace and branch controls align in a single context row. Existing month filtering remains available behind an accessible calendar control. Language select and Apply remain inside a native details popover. Keyboard Escape/outside click dismiss popovers; focused navigation tabs scroll fully into view without scrolling the page vertically. Native details remain usable without the new JS.

Existing forms, endpoints, field names, hidden values, notification target and identity dialog handlers are preserved. No new copy, business rules, credentials, schema or security configuration is introduced. The only base-template change conditionally loads Finance chrome assets in the head. Other modules and page-content templates are untouched. Help/profile dialogs remain outside the style boundary.

## Verification

- 136 rendered before/after cases: 320/390/768/1440 widths, English/Indonesian, Personal/Business. Supported pages: Dashboard, Income, Expenses, Transactions, Accounts, Scan Receipt (Business), Bills, Budget, Invoices, Recipients, Reports, New Invoice and Invoice Settings.
- Body-region text, forms, computed styles and normal-flow geometry are identical after normalizing the permitted vertical shift. Existing sticky Invoice action bars retain their styles/dimensions and naturally respond to the shorter header's viewport position. No body file or body style was edited.
- Nine final before/after screenshot comparisons at 390/768/1440 for Dashboard, Income and Scan Receipt; original shared templates are rendered from baseline Git objects without reverting the worktree. Crops are normalized for vertical position. Byte-level image equality is not claimed because fractional-pixel rasterization differs; DOM geometry/style equality and visual inspection establish content equivalence.
- 16 dedicated control cases: keyboard profile/dialog/escape, touch popovers, long business/branch labels, branch GET context, month GET context, language POST return URL and workspace POST payload. POSTs are inspected and redirected locally without reaching application handlers. Seven fixture financial tables remain unchanged.
- 80 component/integration tests +52 subtests pass, covering Finance totals, reports, edits, categories/roots, splits, receipts, isolation, initialization and first-render separation. Three existing context JS tests pass.
- Archived assistant/analyst/operator/bank-import routes retain HTTP404. Personal Scan Receipt remains HTTP404. No retired flow is re-enabled.
- No page overflow; first and last navigation links remain reachable by keyboard. App-language labels, active tab, branch/month/currency, Home and unpaid-bill notification targets remain intact.

Evidence lives outside Git in `/workspace/finance-header-evidence/`: `body-equivalence.json`, `controls.json`, before/after screenshots under `visual/`, logs and production protection fingerprints. Library references were resolved, but their download helper returned download failed; the parent's inspected reference descriptions and real baseline pages grounded the work.

Production target verified: Render My Workspace tea-da34t2gu01pc73ft7uf0, Client Hub srv-da7ti2psrm7s73dh9i2g, main branch, client-hub root, autoDeploy OFF. Push/deploy requires exact-SHA LIVE confirmation. Seven scoped production count/fingerprints are compared before and after. No production financial mutations, paid inference, credential or security changes are performed.

Limits: Chromium browser verification includes phone and tablet dimensions, not physical Safari. The runtime cannot observe authenticated production UI; parent performs that final browser check after LIVE.
