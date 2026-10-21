# Credits & Usage — design-only release

Owner authorized the Credits & Usage page design and deployment on 2026-10-21.
The new `/kilas-ai/usage` entry is explicitly a design proposal. It contains no
connected wallet, conversion, free-credit grant or payment submission. Balance,
used credits, total top-ups and estimated credits are unavailable em-dash states.
Custom amount entry and USD/IDR selection are presentation only. Currency choice
clears the input rather than converting or reinterpreting money.

The visible **Manage existing billing** link opens `/kilas-ai/usage?view=legacy`,
which renders the unchanged original subscription/capacity/invoice template with
the existing route context. Existing purchased access, payment handlers, price
tables, ledgers, expiry and entitlements are unchanged. Finance implementation and
shared styles are unchanged. The existing Kilas profile entry is renamed Credits
& Usage. New English-source strings have Indonesian translations; existing app
language behavior is retained.

## Validation

- Browser: English and Indonesian at 1440, 1024, 834, 390 and 320 pixels; no
  horizontal overflow, page errors, external requests or write requests from
  proposal interactions. Verified custom amount validation, currency reset,
  unavailable estimate, disabled payment, arrow/Home tab keyboard behavior and
  mobile navigation focus restoration.
- Inspected actual desktop/tablet/mobile screenshot pixels; fixed tablet top-up
  grouping and placed the amount form directly after balance on smaller screens.
- Billing regression: 2 tests pass, including manual activation, idempotent review,
  owner isolation, renewal and plan transition. Fixture updated to create the
  current revocable synthetic customer session; no authentication guard weakened.
- Console/capacity regression: 5 tests pass, including exact unchanged subscription,
  top-up grant/debit, Audio balance and usage records across proposal GETs, retained
  paid PLUS access, anonymous denial and reachable original billing.
- Localization: 14 tests pass. JavaScript syntax, JSON and diff whitespace checked.
- Broader revisions suite: 6 pass, 1 existing failure in
  `test_navigation_profile_and_private_library` before the changed profile-label
  assertion: its old thread is absent from the current sidebar projection. The
  same failure is reproduced with the original HEAD profile template. No history
  behavior or assertion was weakened for this release.

All test data is disposable local SQLite; tests run without provider credentials.
No paid inference, production account mutations, price changes or schema changes.

## Preview and evidence

Run `python scripts/preview_credits_usage.py` from `client-hub` with Flask installed.
It binds loopback `127.0.0.1:8765`, imports no application/DB/provider module and
renders the same template with an empty, explicitly preview account shell.

Repeat browser evidence with
`python tests/credits_usage_preview_browser.py --browser /usr/bin/chromium`.
Screenshots and JSON checks are written to `/tmp/kilas-credits-review` by default.
This is not a production authentication bypass or a new hosted preview endpoint.

Release scope: Client Hub `srv-da7ti2psrm7s73dh9i2g` only. Deployment SHA and LIVE
status must be verified from Render after the scoped commit is pushed; this
document alone does not claim production is LIVE.
