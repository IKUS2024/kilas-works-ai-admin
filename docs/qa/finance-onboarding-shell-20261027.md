# Finance onboarding shell consistency

New customers choosing Finance from Home reach `/products/finance?step=business`.
That endpoint was omitted from the existing customer shell context, so the page
rendered the old product tools/settings/language sidebar instead of the current
New chat, Library, Products and Profile components. This is a reproducible shell
coverage defect; it is not evidence that another customer's session was loaded.

The route now opts into the same existing shell and owner-scoped, read-only
history projection as Home. The Finance form, POST handlers, tenant checks,
trial/billing behavior and ledger remain unchanged. Shared drawer components and
styles are reused without modification.

The parent materialized and visually inspected the two original owner screenshots
(`1000348701.jpg`, `1000348699.jpg`). This executor could resolve their Library
metadata but could not download their bytes through the supported transfer
helper. It independently reproduced and viewed the same route's legacy shell.
The parent explicitly accepted that combined evidence before implementation.

## Functional evidence

`test_finance_onboarding_shell.py` exercises a real local Flask application with
disposable SQLite accounts and real revocable login sessions. It checks the new
Finance handoff and approved menu, owner-only history, no external transport on
page rendering, existing CSRF rejection, business creation and duplicate-submit
protection, foreign-business denial, logout token revocation and account switching.

`finance_onboarding_browser_qa.py` uses local Chromium at 320, 390, 820 and 1440
pixels. It exercises the actual Home Finance menu, drawer bounds and Escape focus,
profile language change, business creation, existing-business listing and logout
with Back/Forward followed by another account login. Screenshots and browser.json
are exported as the `finance-onboarding-synthetic-browser` CI artifact.

The focused workflow additionally runs existing customer authentication, sidebar
products/history, standalone Finance and style-loading contracts. All data is
synthetic; no paid provider calls, production account creation or production data
writes are part of this QA.

Products pages already send `Cache-Control: private, no-store`, and their existing
`pageshow` handler reloads restored browser pages. Login clears/rotates the session,
logout revokes it server-side, and token validation binds the owner. Baseline
two-account and browser checks did not reproduce cross-account identity/business
leakage. No session or authorization code was changed.

## Release verification limits

Use exact-head focused CI, current repository review policy and exact Render LIVE
commit for release evidence. Historical broad workflows have known baseline
failures documented in `kilas-hd-release-ci-triage-20261027.md`; this change does
not disable or weaken them. Production authenticated browser QA currently cannot
run in this executor because the cloud browser runtime lacks its provisioned
token and direct production HTTP encounters the outbound proxy's CONNECT403.
Local synthetic QA and Render deployment/log verification must be identified
separately from live customer acceptance.

An additional attempted existing `test_kilas_chat_sidebar_browser.py` run fails
at its chat-send fixture expectation (draft input remains populated). The same
failure was reproduced on untouched exact main `180e0183`, so it is not treated
as a successful check or changed to accommodate this release. Its logs are
`/tmp/onboarding-chat-browser.log` and `/tmp/onboarding-chat-browser-main180.log`.
No existing workflow or assertion is disabled by this change.
