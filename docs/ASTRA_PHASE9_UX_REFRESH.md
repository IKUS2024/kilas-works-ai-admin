# ASTRA PHASE 9 — PRODUCT UX / ONBOARDING / ADMIN / FINANCE REFRESH

Status: execution specification
Branch: feature/kilas-core-v2
Prerequisite: Phase 8 COMPLETE; Phase 1–8 regressions green.

## Goal

Turn the existing Kilas V2 feature set into one coherent, premium, sellable product experience.

This is the first phase where broad UX restructuring is explicitly allowed.

Astra has meaningful creative freedom over:
- information architecture
- navigation
- page hierarchy
- responsive layouts
- visual grouping
- button placement
- empty/loading/error states
- owner flow
- admin flow
- Finance presentation

BUT product capabilities and authoritative business/accounting behavior must be preserved.

The experience should feel like one modern Kilas product, not a collection of old modules.

## Product identity

Kilas Works is the umbrella.

Core SaaS:
- Kilas AI Admin / Business Workspace
- Kilas Finance

Service offerings remain separate commercial services:
- Kilas Content
- Talent / Production services

Do not turn AI Admin into a creative image/video generator.

Visual direction:
- premium dark charcoal / near-black
- Kilas orange as primary accent
- white / soft gray hierarchy
- restrained green / red / yellow for status
- clean typography
- strong spacing and hierarchy
- modern SaaS, not gaming/neon
- subtle depth, borders and shadows
- dense enough for business use, but not cramped
- mobile-first and desktop-polished
- no decorative clutter

## Non-negotiable preservation rule

Before redesigning any area, inventory every existing customer-visible and operator-visible capability
in that area.

Except for the explicitly retired Kilas Order feature below, Phase 9 must not accidentally delete,
hide beyond discovery, or break an existing useful capability just because the page is redesigned.

Preserve behavior and data for:
- Public Web Chat
- WhatsApp readiness/onboarding state
- Inbox
- Human Takeover
- Customers
- Jobs / business-specific labels
- Automations / Attention
- business setup and settings
- subscription/package visibility
- Finance Standalone
- Finance Connected / Bridge
- projects/content/talent service flows that remain part of Kilas Works commercial services
- internal admin/support operations
- existing audit/security/tenant controls

Astra may relocate a function to a better screen/menu if the new location is obvious and tested.

## 1. Unified customer app shell

Replace the fragmented customer experience with one coherent app shell.

Package-aware primary navigation:

AI Admin only:
Home | Inbox | Customers | Jobs | More

Finance only:
Home | Finance | More

Full Kilas:
Home | Inbox | Customers | Jobs | Finance | More

Desktop may use a sidebar if it produces a clearer result.
Mobile should use a compact bottom navigation or similarly ergonomic pattern.

More may contain:
- Automations
- Knowledge / business info
- WhatsApp / Channels
- Settings
- Billing / package
- Kilas Services where appropriate

Do not expose modules the customer's package does not contain.

Do not create a separate isolated general AI page merely to fill navigation.
"Tanya Kilas" can be contextual.

## 2. Home / Command Center

Home is an attention and next-action dashboard, not a wall of vanity analytics.

For active businesses prioritize:
- conversations needing human response
- Jobs needing information
- Jobs ready for quote/action
- overdue or outstanding Finance items when Finance is active
- setup/channel issues
- useful next actions

For new customers prioritize:
- setup progress
- create/confirm business
- add business information/services
- try as customer
- copy/open Public Web Chat
- connect WhatsApp when officially available, with a truthful optional/pending state

Do not fill first-run dashboards with meaningless zero charts.

## 3. Inbox

Preserve Phase 2/6/8 behavior while making it feel like a professional support workspace.

Goals:
- conversation list + clear active thread
- visible channel (WEB / WhatsApp)
- Customer identity
- linked Job
- known information
- missing information
- current status
- AI/Human state
- obvious takeover/resume
- manual reply
- delivery state where available
- attention/handoff state

On mobile, conversation navigation must remain usable without horizontal overflow or tiny controls.

## 4. Customers

Keep full existing Customer functionality.

Improve:
- list/search/filter density
- clear customer profile
- notes
- conversation history
- Jobs
- linked Finance status when allowed
- actions grouped by intent, not scattered buttons

Do not merge identities based on visual/UI shortcuts.

## 5. Jobs

Keep the generic Job engine and business-specific labels.

Improve list/detail/create/edit flows so normal owners do not need to understand internal state-machine
terminology.

Present business-appropriate language:
- Pesanan
- Booking
- Pengiriman
- Project
- Service
- Pekerjaan fallback

Preserve lifecycle rules, operation/idempotency semantics and tenant isolation.

## 6. RETIRE KILAS ORDER

The legacy separate "Kilas Order" shopping/search marketplace/request product is no longer part of the
Kilas V2 product direction.

Remove it from:
- customer navigation
- Home
- product switchers
- public product entry points
- active service/catalog marketing inside the SaaS
- internal admin navigation where it exists only to operate Kilas Order

Audit current references before removal.

Important safety rule:
- DO NOT drop old Kilas Order database tables or old migration files in Phase 9.
- DO NOT destructively delete historical customer/order-request data.
- Existing migrations must remain valid for already-upgraded databases.
- Disable/retire new Kilas Order usage.
- Historical records may remain dormant/read-only if needed for data safety.
- Delete dead templates/services/routes only after proving they have no shared dependency.
- Old public bookmarks should redirect safely to the current Kilas product/home where sensible,
  or return an intentional retired response; never crash.

This retirement applies ONLY to the separate legacy Kilas Order product.
Do NOT remove the new generic Jobs engine or business-specific "Pesanan" label.

## 7. Finance UX refresh

Finance may be substantially visually reorganized in Phase 9.

Astra has creative freedom to improve:
- Finance shell/navigation
- grouping of features
- page hierarchy
- account detail flows
- transaction entry
- income/expense presentation
- transfer presentation
- invoice flow
- receivables
- recurring bills
- budgets
- reports/cash flow
- branch/business selectors
- Personal vs Business context
- multi-currency presentation
- Bank/PDF import surfaces
- Finance AI surfaces
- empty/error/read-only states
- mobile layout
- button naming/order
- duplicate or confusing controls

However Finance remains ONE protected engine.

Do NOT change monetary/accounting semantics merely for UI convenience.

Preserve all currently supported Finance capabilities, including:
- businesses/workspaces
- branches
- accounts
- opening balances
- income
- expenses
- supported transfers / FX behavior
- categories/subcategories
- invoices
- edit/issue/void/archive behavior already supported
- partial/full payments
- receivables/outstanding/overdue
- recurring bills/expenses
- budgets
- cash flow/reports
- multi-currency
- exports/documents/PDF paths
- Finance AI
- entitlements/trial/read-only behavior
- Standalone Finance independence
- Connected Finance Bridge
- audit/history behavior

Do not recreate Finance in a new database/model.

Keep the useful foundation/design language the existing team built, but make the overall experience
cleaner and more coherent. Strange, duplicated, low-value or badly placed buttons may be consolidated
or relocated after behavior is mapped.

## 8. Finance Professional Readiness audit

Phase 9 must honestly inspect whether these exist and are production-ready:
- chart of accounts
- double-entry general ledger
- journals
- reconciliation
- trial balance
- profit & loss
- balance sheet
- period close/lock
- accountant/audit export workflow

Do not fake these with labels or UI.

If missing, document the gap in:
docs/KILAS_V2_FINANCE_PROFESSIONAL_READINESS.md

Only implement bounded, clearly safe improvements that fit Phase 9 without rewriting the Finance
engine. Large accounting architecture changes become a separately approved future phase.

The UI must not call Finance "full accountant-grade accounting" unless evidence supports that claim.

## 9. Onboarding simplification

New user flow should be understandable in minutes.

Preferred product-selection entry:
"Apa yang mau dibantu Kilas?"
- Layani Customer
- Kelola Keuangan
- Keduanya

Then minimum setup:
- business name
- business type
- city / primary branch where required

Then contextual checklist.

AI Admin wow moment:
"Coba sebagai customer"

Finance-only users must never be forced through AI Admin setup.

WhatsApp is optional while external Meta access is unavailable.
Do not make WhatsApp approval a signup blocker.

## 10. Package / entitlement clarity

The UI must clearly reflect what the customer owns without exposing internal entitlement jargon.

Support:
- AI Admin only
- Finance only
- Full / both

Do not show locked modules as if broken.
Use clear upgrade/availability messaging where needed.
Do not invent prices or package rules not already authoritative in the product configuration.

## 11. Kilas Content / Talent services

Preserve legitimate existing service-business flows for Kilas Content / Projects / Talent where still
used commercially.

They should not dominate the SaaS operating-system navigation.

Place them in a clear "Kilas Services" / project-services area or another coherent location chosen
through the UX audit.

Do not turn them into AI image/video generation features.

## 12. Internal admin dashboard refresh

The internal Kilas admin/operator experience must also be redesigned for clarity.

Preserve existing admin capabilities, including relevant:
- business/customer review
- subscriptions/payments
- project/service operations
- talent operations
- AI usage
- WhatsApp/channel readiness/support
- audit/support data
- search
- Finance/support visibility where already authorized

Remove Kilas Order-specific admin surfaces from active navigation as part of the retirement above.

Prioritize operational queues and exceptions instead of a wall of links.

Admin design may be denser than customer design, but must still be coherent/mobile-safe.

## 13. Flow ownership / creative freedom

Astra is explicitly allowed to redesign navigation and flow after inventorying the existing behavior.

Astra should choose the cleanest flow rather than mechanically preserving every old page boundary.

Allowed:
- combine related screens
- split overloaded screens
- move actions to better locations
- replace scattered links with menus/tabs
- add breadcrumbs/context headers
- use drawers/modals where appropriate
- simplify repeated selectors
- improve naming
- reduce vertical scrolling
- add pagination/search/filter controls
- improve mobile bottom navigation
- create reusable UI components/tokens

Not allowed:
- silently delete useful capabilities
- bypass server authorization in the UI
- move authoritative state into client-side-only code
- hide critical errors
- fake data
- change business/accounting outcomes through presentation code

## 14. Design-system cleanup

Refactor the current large collection of page-local CSS into a maintainable shared design system where
safe.

Goals:
- reusable tokens
- buttons
- inputs
- cards
- status pills
- tables/lists
- tabs
- page headers
- selectors
- empty/loading/error states
- responsive spacing
- icons

Avoid one giant risky rewrite. Migrate screens incrementally and keep regression/browser coverage.

## 15. QA requirements

Create docs/KILAS_V2_PHASE9_STATUS.md and keep it current.

Before completion verify:
- exact feature inventory before/after
- AI Admin-only navigation
- Finance-only navigation
- Full navigation
- new-account onboarding
- existing-account upgrade/entitlement states
- Home attention states
- WEB Inbox
- WhatsApp-enabled Inbox fixture
- Customers
- Jobs and each business label type
- Human Takeover
- Automations/Attention
- Public Web Chat share/open flow
- Finance Standalone
- Finance Connected Bridge
- all major Finance modules
- Personal/Business contexts
- branches
- multi-currency
- invoices/partial payments
- reports/export
- Finance AI
- Kilas Content/Projects/Talent retained in appropriate service area
- Kilas Order absent from active customer/admin product navigation and entry points
- old Kilas Order URL retirement behavior
- admin dashboard and operational flows
- 360 / 390 / 430 mobile widths
- tablet
- desktop
- no horizontal overflow
- keyboard/focus accessibility
- loading/empty/error/read-only states
- tenant isolation
- CSRF/auth
- Phase 1–8 regressions
- complete Finance baseline
- PostgreSQL
- exact diff review
- git diff --check

Use real browser/Chromium QA fixtures and inspect screenshots, not DOM assertions alone.

## 16. Deployment boundary

Do not deploy production in Phase 9.

Do not change production Meta/WhatsApp activation.

Do not reset/migrate customer data destructively.

Do not start Phase 10 automatically.

## Completion

Phase 9 is COMPLETE only when:
- customer app looks/behaves like one coherent Kilas product
- existing non-retired capabilities are preserved and discoverable
- legacy Kilas Order is retired safely
- onboarding is simpler
- package-aware navigation works
- owner dashboard is useful
- internal admin is refreshed
- Finance UX is materially improved without accounting regression
- Finance Professional Readiness is honestly documented
- Phase 1–8 plus Finance regression gates remain green
- PostgreSQL and browser/mobile QA pass
- exact diff is reviewed
- no production deployment occurred

If interrupted:
commit a coherent passing checkpoint, update docs/KILAS_V2_PHASE9_STATUS.md, and state:
RESUME FROM STATUS FILE

When complete:
mark docs/KILAS_V2_PHASE9_STATUS.md COMPLETE and STOP.

Do not start Phase 10 automatically.
