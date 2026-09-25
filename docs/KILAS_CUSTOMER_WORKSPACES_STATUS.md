# Customer product separation — 2026-09-25

Implementation checkpoint; deployment and final CI pending.

## Inspected starting state

Remote main and live Hub: 2aa5e0658b70815685493cbddd45caea2fb5b72b,
Hub deploy dep-dar0u4rncjis73bnenk0. Bot remains db777b23c0c04b4a5419b1f4aabd9ba88bddd613.
Normal Putri customer session inspected in production. Home mixed AI Admin and Finance
cards, and a six-item shared navigation included Finance alongside Inbox/Customers/Jobs.
Existing Finance business 13/branch 19 and business 2 retained; no new business or ledger writes.
Installed V2/Finance schema inspected read-only. No migration needed or performed.

## Causes and corrections

- Phase-9 workspace context built one navigation from the union of owned products; Home
  rendered both product lists and Finance attention. Home now renders AI information only.
- Explicit /workspace/ai and remembered product routing separate the two workspaces.
  Finance-only accounts enter Finance directly. AI-only accounts have no Finance menu.
  Dual-product accounts get a separate accessible product selector, available on phones too.
- Finance session middleware previously trapped AI deep links. Existing authorized AI routes
  can now select their own context; their membership, CSRF, entitlement and Core gates remain.
  Unmatched requests preserve actual 404/405 instead of redirecting failed writes.
- Finance business selector previously included every membership. It now shows claimed Finance
  businesses, including legitimate legacy accounts and read-only/expired Finance access.
- Independent selected AI/Finance business IDs and validated per-business Finance branch memory
  prevent product switching from selecting another product's business or a foreign branch.
- Account/billing navigation retains product context. More hides AI configuration in Finance.
- Previous restoration in main already restored approved pre-Phase-9 Finance presentation.
  Confirmed _finance_home_dashboard.html matches 05d50a8; finance_ui.css differs only by
  greeting wrapping and the necessary tablet toolbar fix. This change preserves that restoration.
  The switcher uses existing colors/styles and does not replace dashboard/cards/calculations.

## Scope / files

routes_workspace.py, finance_ui.py, app.py: presentation context/navigation only.
base.html, _workspace_nav.html, _product_switcher.html, workspace_home.html,
workspace_more.html, _finance_app_shell.html, _finance_dashboard_shell.html,
product_switcher.css: isolated navigation and compact switcher.
Workspace tests, Finance selector test, Phase 9/10 browser journeys updated for the explicit
new product contract. Finance financial assertions and malformed/foreign-write gates retained.

## Integration and data safety

Core/Finance Bridge engines, schema, subscription lifecycle and accounting services unchanged.
Job, Operations and Bridge route presentation guards no longer treat active_product=finance
as authorization: owned AI pages work across products, while existing package/subscription,
allowlist, flags, membership and Bridge source/destination validation remain mandatory.
Bridge still requires configured mapping, owner-confirmed customer/draft invoice actions,
and authoritative Finance issue/payment rules. Casual conversation never posts money.
Duplicate bridge/payment protections remain tested. UI separation does not enable production
Bridge automatically: existing rollout gates stay as configured; WhatsApp general stays OFF.
No production Finance write, business creation, deletion, reset or destructive migration.

Read-only baseline captured all tenants (including existing QA):
accounts 34/max34 eb2bea17987df4e7f06066dea6850d69;
transactions 64/max64 5f4c7f148327ed78fa15ce89446a5ba9;
invoices 9/max9 fb5dd4d4e02582a180f423bac62121d6;
invoice_items 20/max21 4dc304675cd4197faed7a2c8d0cc2f1e;
invoice_payments 4/max4 64ff1cd509319060e24d71ead988d920;
customers 7/max7 33c9b67a9b5da14e4be697abdebcfd95;
recurring_expenses 2/max2 6d6d3d0fd1bd30a5ce05c4fefc39bc5f;
recurring_postings 0 d41d8cd98f00b204e9800998ecf8427e;
budgets 2/max2 5922928e4763dc81fa4fba7e7e1f68ab.
Hash: sorted row JSON excluding relocation_version, joined by newline, MD5.
Compare the original ID range on final readback; do not mistake unrelated live additions for edits.

## Validation / next step

Local workspace 10 tests pass. First complete Finance run exposed the old membership-only
selector assertion, an unmatched-method redirect, and CSS-order violation; corrected narrowly.
Focused Finance selector and CSS tests pass. Complete local Finance baseline PASS: 39 files / 1018 tests.
First Phase 9 browser gate PASS at all five widths. Release QA exposed a Finance-session
redirect blocking the return to Bridge payment readback; fixed by recognizing Bridge as an AI
workflow route while keeping every Bridge permission/confirmation gate. Old standalone Bridge
route tests were reaching nonexistent GET URLs masked by redirects; now exercise canonical
Finance routes and retain all zero-Bridge-row and accounting assertions. Final CI rerun pending.
Browser suite checks 360/390/430/820/1440 widths, both switching directions, no mixed menus,
bottom-nav clearance, no horizontal overflow or JS errors. Authenticated release suite retains
invoice partial payment, Bridge duplicate protection, takeover and Finance persistence checks.
Next: certify PR, merge safely, deploy affected Hub, verify existing customer session and logs,
then update this file with exact live revision and evidence. Do not claim production success yet.
