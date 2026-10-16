# Finance navigation Reset placement — 16 October 2026

Reset is now a compact item immediately after Dashboard in the primary Finance navigation containing Transactions and Accounts. The existing navigation appears horizontally at the top on mobile and in the sidebar on desktop. The Personal/Business context area contains no Reset button. The action is shown only on Dashboard to the existing authorized owners, respecting read-only restrictions. Its accessible name/title remains Reset Data Finance; the compact visible label is localized Reset.

The action still submits only to the warning preparation endpoint. Typed RESET, acknowledgement, owner authorization, exact selected Business branch or canonical Personal ledger, state fingerprint and duplicate-submit protections are unchanged. There is no schema, route, ledger, credential or unrelated-module change. This task invokes no production reset, preparation or financial write.

## Personal entry verification

The dashboard passes `finance.list_entry_accounts` for the authenticated owner and selected branch directly to the Add Income receiving-account selector. The same function validates the account on submission. Its query includes the current business, branch and active account scope. Synthetic integration checks cover existing bank choices and isolation. Owner-specific read-only verification is reported privately and excluded from this public release document. No user impersonation or production form submission is used.

The canonical `/finance/personal` GET route resolves the authenticated owner's existing authorized Personal ledger. Dashboard/sidebar GET navigation and opening the Add Income dialog allow inspection without saving. Do not click Reset or submit forms during read-only production verification.

## Validation and release

- 43 targeted tests pass, zero failures/errors/skips: navigation-only placement and other-tab absence in both modes, existing owner/reset safeguards, UI integrity, styles and locales.
- Chromium passes at **1440/390/320px**, both Personal and Business, all four languages. The Reset item is inside the primary navigation and outside the context area, visible within the navigation bounds with no document overflow. Other tabs and review omit the action. Local warning-only clicks preserve every financial fixture row and never submit a final reset. External browser requests are blocked. [Browser evidence](evidence/finance-reset-navigation-20261016/).
- Screenshots use synthetic disposable fixtures. Production browser access from this execution environment remains unavailable; no authenticated production UI observation is claimed.
- Deploy verification pending the approved main push and existing Client Hub deployment.
