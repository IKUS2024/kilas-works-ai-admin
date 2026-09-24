# Phase 9 — product UX refresh

Status: IN PROGRESS. No production deployment or Phase 10 work.

## Baseline and required reading

Started from feature head `2d6d6fe8454d3d9ff7225cf52df3fb49ffafe3d9`.
Remote main: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.
Read MASTER, AUDIT, EXECUTION_ROADMAP, PHASE7_STATUS, PHASE8_STATUS,
FINANCE_SELLABILITY and ASTRA_PHASE9_UX_REFRESH completely before changes.
Phase 9 explicitly supersedes earlier restrictions on Finance presentation redesign.

Initial feature CI: Phase 2 `36067842637`, Phase 3 `36067842711`, Phase 4
`36067842650`, Phase 5 `36067842704`, Phase 6 `36067842675`, Phase 8
`36067842748` successful. Phase 7 `36067842694` still running at inspection.
These results certify the baseline, not Phase 9 changes.

## Capability inventory before redesign

The route handlers, template actions, context selectors and shared scripts were
inspected. Existing Phase 7 Finance and Phase 8 Inbox screenshot artifacts were
visually inspected as baseline evidence; new Phase 9 viewport QA remains pending.

| Area | Useful capabilities to preserve | Intended location |
| --- | --- | --- |
| Entry / Home | Independent AI and Finance setup, business selection, subscription/review state, existing historical businesses | Three intent choices; Home attention and setup; More business settings |
| AI setup | Business identity, services, operations/contact, appointment/payment information, FAQ, reply style/languages, knowledge upload/download/delete, writing assistance, review/revision, checkout | Guided setup with first customer simulation; advanced knowledge/settings retained |
| Inbox | WEB and official WhatsApp, legacy history/media, search/pagination, known/missing information, Jobs links, takeover, manual reply, explicit resume, delivery status, approved template | Primary Inbox, existing guarded channel handlers |
| Customers | Tenant-scoped search/list, editable profile/contact/notes, conversation history, Jobs, explicit Finance Bridge | Primary Customers |
| Jobs | Business-specific labels, search/status/customer filters, create/update, fields, lifecycle, optimistic concurrency, conversation/customer links | Primary Jobs; business Order/Pesanan remains |
| Operations | Attention queues, handovers, approvals, follow-up settings and audit state | Home and contextual Inbox/Jobs; settings in More |
| Finance context | Independent entitlement, Personal/Business, business/branch selection, period/currency, archived/read-only history | Finance context toolbar; primary package-aware navigation |
| Accounts / transactions | Account types, opening balances, balance adjustments, rename/delete guards, categories/subcategories, income/expense, edit/void, versioned workspace relocation, guarded reset | Finance accounts and transactions; destructive actions stay explicit |
| FX | Different-currency exchange create/edit/void and history | Explicit currency exchange; no invented same-currency transfer |
| Invoices / receivables | Finance customers, invoice sender/payment settings, draft/edit/issue/void/archive/restore, notes, partial payments, print/share, statements, collection queues/reminders | Invoice workspace with contextual subnavigation |
| Recurring / budget | Rules, schedule/calendar/list, editing/deactivation, owner-confirmed occurrence payment, category budgets and actuals | Finance bills and budgets |
| Reports | Period/scope filters, native currency and display estimates, cash flow, PDF/CSV/ZIP exports | Finance reports; never labeled accrual financial statements |
| Import / Finance AI | Receipt and bank/PDF extraction, review/correction, matching/post/ignore/cancel/retry, staged actions, explicit confirmation, contextual analyst/operator/document flows | Finance tools and contextual Tanya Kilas |
| Finance Bridge | Explicit business/branch and customer mapping, owner review, idempotent draft, authoritative readback | Customer/Job context; no automatic invoices/payments |
| Services | Content/project catalog, fixed checkout, custom briefs, quotes, proof/payment, project status/cancel/download, talent profiles/requests | Kilas Services under More; separate from customer business Jobs |
| Account | Profile/photo, Personal and Business invoice identity/payment fields, branch data, email OTP, password, logout | More / account |
| Operator | Review/revision/approval, business support, subscription renewal/sweep, package/status, files, AI setup retries, simulation, official links/catalog, service projects/quotes/payments/talent, channel support/coexistence, Inbox/media/manual templates, AI usage/search | Grouped operator navigation and priority queues |

## Legacy Kilas Order dependency audit

The retired marketplace is implemented by `routes_products.py` Order endpoints,
`routes_admin.py` Order endpoints, `order_service.py`, `order_search.py`,
`order_intake_ai.py`, `order_catalog_service.py`, Order templates and migrations
0051–0054. Active entry links occur in product_start, base admin navigation and
admin_dashboard. Retirement must stop GET handoff/background-search side effects
as well as POST creation. Historical schema/data and migrations remain intact.

Service checkout `renew_wa_order_link`, service purchases and generic Core Jobs
are separate capabilities and must remain. No deletion of historical services or
schema is proposed. Public static catalog PDF must not be regenerated incidentally.

## Architecture decisions

- Shared navigation is presentation only; existing tenant/entitlement/CSRF guards
  stay authoritative. Explicit workspace transitions replace confusing session lock
  dead ends without granting permissions.
- Same owner does not imply same AI/Finance business. Preserve explicit Finance
  Bridge mapping and independent product identities.
- WhatsApp optional; no live Meta activation and no claim of general availability.
- Finance engine and schema are outside this redesign. Professional gaps are
  documented separately, never simulated with UI.
- No general-purpose chatbot or creative generation.

## Validation / next action

Phase 9 tests, PostgreSQL, responsive screenshots (360/390/430/tablet/desktop),
keyboard/focus, security and full Finance baseline are NOT yet run for new work.
Exact initial changed files: this status file and
`docs/KILAS_V2_FINANCE_PROFESSIONAL_READINESS.md` (audit documentation).

Next: implement shared package-aware workspace shell and safe legacy Order
retirement, preserve route actions, add focused security/navigation tests, then
complete onboarding/Finance/operator redesign and the complete regression gates.
Do not mark COMPLETE until all required gates pass.

## Checkpoint 1 — shared workspace and retirement

Implemented package-aware Home/Inbox/Customers/Jobs/Finance/More, explicit product
transitions with membership-scoped selection, shared owner CSS and grouped operator
navigation. Finance module navigation is secondary to the product shell. Finance
quick actions precede metrics; empty cash-flow periods have actionable guidance and
expandable details. Existing forms, history and service handlers remain available.
Three intent choices preserve separate AI/Finance setup. Marketplace handlers return
410 before search, handoff or mutations. No historical tables or migrations changed.

Focused validation: 5 new workspace tests passed; 19 non-PostgreSQL Core test files
passed (including WhatsApp). Broad selection also invoked four PostgreSQL executables
without their explicit fixture flags: those correctly refused to run; this is not a
PostgreSQL pass. PostgreSQL gates remain required in CI.

Complete Finance baseline executed: 39 files / 1,018 tests. Only three UI assertion
files failed on changed labels/navigation/CSS order. Updated those presentation
contracts, retaining financial assertions; all three files passed on focused rerun.
Full baseline rerun remains required. Synthetic route smoke: new, AI-only,
Finance-only, full and admin Home, Inbox, Customers, Jobs, Services, Talent, Projects,
Account and bank import returned 200. `git diff --check` passed.

Browser direct loopback preview returned `ERR_BLOCKED_BY_CLIENT`; no workaround or
production preview was attempted. Dedicated Phase 9 CI now supplies isolated real
route screenshots at 360/390/430/820/1440. Those results are not yet certified.
Next: run remote Phase 2–9 CI, inspect screenshots, fix layout/flow regressions,
finish onboarding/Home attention details and certify all gates. Status remains
IN PROGRESS; this checkpoint is not Phase 9 completion.

Exact checkpoint file manifest:

- `.github/workflows/kilas-v2-phase9-qa.yml`
- `client-hub/app.py`
- `client-hub/finance_ui.py`
- `client-hub/legacy_order_retirement.py`
- `client-hub/routes_products.py`
- `client-hub/routes_workspace.py`
- `client-hub/static/kilas_ui.css`
- `client-hub/templates/_finance_app_shell.html`
- `client-hub/templates/_finance_home_dashboard.html`
- `client-hub/templates/_operator_nav.html`
- `client-hub/templates/_workspace_nav.html`
- `client-hub/templates/admin_dashboard.html`
- `client-hub/templates/base.html`
- `client-hub/templates/customer_detail.html`
- `client-hub/templates/customers.html`
- `client-hub/templates/finance_dashboard.html`
- `client-hub/templates/order_retired.html`
- `client-hub/templates/product_start.html`
- `client-hub/templates/workspace_home.html`
- `client-hub/templates/workspace_more.html`
- `client-hub/templates/workspace_unavailable.html`
- `client-hub/tests/kilas_workspace_browser_qa.py`
- `client-hub/tests/kilas_workspace_dev.py`
- `client-hub/tests/test_finance_dashboard_design.py`
- `client-hub/tests/test_finance_home_dashboard.py`
- `client-hub/tests/test_finance_style_loading.py`
- `client-hub/tests/test_kilas_workspace.py`
- `docs/KILAS_V2_FINANCE_PROFESSIONAL_READINESS.md`
- `docs/KILAS_V2_PHASE9_STATUS.md`

## Checkpoint 2 — attention and responsive corrections

Published checkpoint 1: `c08a1c5436c843a8b07873a3c30f1083151fb5f1`.
CI Phase 2 `36069807778`, Phase 3 `36069807779`, Phase 4 `36069807811`,
Phase 5 `36069807774`, Phase 6 `36069807784`, Phase 8 `36069807836` successful;
Phase 7 `36069807819` running at inspection. This includes the existing PostgreSQL
and mobile gates in those completed workflows.
Phase 9 `36069807822` failed at Finance tablet width 820 after 104 screenshots;
artifact `10837677465` downloaded and mobile Home/Finance/operator inspected visually.
Identified tablet overflow, cramped Finance monetary text, elliptical budget ring,
and excessive operator/mobile module navigation height. Corrective CSS and native
collapsible menu changes are in checkpoint 2. No visual completion claim yet.

Home now reads real setup gaps and default Business branch invoice/bill attention
through existing scoped services; unavailable/expired states are explicit. No amount,
currency or cross-branch aggregation is invented. Empty Core attention count removed
from Home. Simulator / continue-later exposed in setup. Existing customer login goes
to Home; new accounts still see product intent. AI setup copy no longer promises
WhatsApp general availability. Selected owned business is retained in primary links.

Local workspace security tests pass after these changes. Exact additional files:
`workspace_presenter.py`, `static/kilas_ui.js` under client-hub; modifications to
routes_auth, routes_workspace, kilas_ui.css, _finance_app_shell, _operator_nav,
_workspace_nav, assist_entry, base, wizard, workspace_home and browser QA script.
Next: checkpoint these fixes, rerun Phase 9 screenshots and full required CI, inspect
all viewport results and finish flow polish. No production or Meta cutover.

## Checkpoint 3 — route consolidation and expanded journeys

Published checkpoint 2: `0b503bbb47aca39f762ed6cf880d0a275584b33e`.
Its Phase 2 `36070335060`, 3 `36070335040`, 4 `36070335021`, 5 `36070335056`,
6 `36070335031`, 8 `36070335059` passed. Phase 9 `36070335050` identified the
remaining 820px overflow precisely: the old Finance context grid's fixed minimum
columns. Fixed with an explicit two-row tablet grid; screenshot failures now collect
all offending pages in one run rather than ending visual evidence early.

Second complete local Finance run PASS: **39 files / 1,018 tests**, zero skipped,
logs `/tmp/phase9-finance-final`. Later legacy dashboard consolidation changes only
presentation: `/dashboard` now invokes shared Home, preserving old bookmarks; two
old dashboard assertions updated to the new intent and owned Finance lane. Focused
Finance Phase 1b and final product flow suites pass afterward. Workspace tests now
7 cases, adding authoritative read-only Finance attention, retained delivered legacy
Order history and owned-business selection. Browser journeys now exercise real AI
business creation / continue later and Finance-only trial onboarding separately.

Additional exploratory legacy tests (`test_client_hub_v1`,
`test_production_foundation`, `test_ai_admin_single_purchase_path`,
`test_astra_ui_production`) fail identically on untouched baseline `2d6d6fe` and the
Phase 9 tree. Baseline reproduced in isolated `/tmp/kilas-phase9-baseline` worktree.
These pre-existing stale fixtures expect obsolete approval requirements/catalog copy
or omit project template context; no security/provisioning requirements were weakened.
Required Phase 1–8 and full Finance gates remain the authoritative regression gates.
`test_final_product_flow` and `test_whatsapp_self_service` also pass.

Next: run the final candidate through Phase 2–9 CI, inspect full desktop/tablet/mobile
artifacts, verify real onboarding journeys, and review exact diff before completion.

## Checkpoint 4 — preserved subscription and usage visibility

Published checkpoint 3: `0c4e662568d980f96663c04fbeac1ff4c246043a`.
Phase 9 `36070949966` PASS, including five viewport sizes and real AI-only / Finance-only
onboarding journeys. Artifact `10837982249` downloaded; tablet Finance and desktop Home
visually inspected, with the previous overflow resolved. Checkpoint 2 Phase 7
`36070335057` also passed both complete Finance baseline and SQLite/PostgreSQL runtime.

Checkpoint 3 Phase 8 `36070949995` caught missing grace-period subscription copy on the
consolidated Home. Restored the existing subscription service banner without changing
entitlements; unchanged `test_subscription_lifecycle.py` passes locally. Capability
review also retains monthly AI reply usage, package/business status and review prompts
in the Home setup disclosure. No meaningless zero metrics added to primary Home.

Phase 3 `36070950026` passed unit/PostgreSQL gates but its old minimal browser fixture
failed Home reads (missing full business/Finance/subscription schema). Updated only
that harness's existing membership/subscription stubs and session-preference assumption;
Core conversation/action/security paths remain real. Local harness Home smoke passes.
Product-intent switching now clears a stale 'both' choice when explicitly choosing one.
Local seven workspace regression cases pass after these changes.

Exact checkpoint files: `client-hub/routes_products.py`, `client-hub/static/kilas_ui.css`,
`client-hub/templates/workspace_home.html`, `client-hub/tests/public_chat_dev.py`,
`client-hub/workspace_presenter.py`, this status file.
Next: publish checkpoint, rerun all Phase 2–9 workflows including Phase 1/Finance
baseline, inspect remaining screenshots, review exact diff, and certify only if green.
