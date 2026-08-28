# KILAS WORKS BUSINESS HUB V2 — FINAL ECOSYSTEM SYNC REPORT

Base checkpoint: `12bb71f` (Business Hub V2 Final Operations Polish). Branch: `business-hub-v2`.
Scope: the 28-section "FINAL ECOSYSTEM SYNC & OWNER NOTIFICATION PATCH" instruction set. No
deploy performed. No merge to any other branch. Additive-only changes throughout.

## What was implemented, per section

**Section 2 (priority gap) — registration no longer forces AI Admin.**
`client-hub/feature_flags.py` gained a `"NONE"` package (all feature flags False, added to
`PACKAGES`/`FEATURE_MATRIX`, accepted by `is_valid_package`) — no migration needed, since
`businesses.package` already has `DEFAULT 'AI_ADMIN_BASIC'` with no CHECK constraint.
`routes_client.py`'s `create_business()` now defaults the form to `package="NONE"` and, when
`NONE` is chosen, redirects straight to the dashboard instead of the onboarding wizard.
`client_dashboard.html`'s "Buat Business Baru" form defaults to "Belum pakai AI Admin"; a
`NONE`-package business is labeled "Active Customer" with its own explanation text instead of the
AI Admin status pill. A new explicit action, `POST /business/<id>/upgrade-ai-admin` (route
`client.upgrade_to_ai_admin`, backed by new `repo.upgrade_business_package()`), lets a customer
add AI Admin later — it re-seeds `tenant_features` for the chosen package and routes into the
wizard for the first time. Only reachable from `package == "NONE"`.

**Section 3/18 — AI Admin fixed-only.** Verified: `pricing_config.py`'s only two `AI_ADMIN`
category entries are both `FIXED_PRICE`; no route or template exposes a custom-AI-Admin path.
Covered by `test_no_custom_ai_admin_catalog_entry_exists_anywhere`.

**Section 4/5 — Content fixed+custom; custom-quote scopes.** Added `custom_content`
(`CUSTOM_QUOTE`, category `CONTENT`) to `pricing_config.CATALOG_ITEMS` (auto-seeds additively via
the existing `catalog_service.seed_catalog_if_needed()`, never overwrites admin edits).
`routes_projects.py`'s `custom_project_request()` now accepts `"CONTENT"` alongside
VIDEO/PHOTO/WEBSITE/APPLICATION. Photo/Video/Talent/custom-website-app remain `CUSTOM_QUOTE`;
fixed website line items (landing page, company profile, extra page, maintenance, domain+hosting)
are untouched `FIXED_PRICE`.

**Section 6 — real CTAs.** `service_catalog.html`'s custom-quote rows now render an actual `<a>`
CTA per category instead of a passive label: Talent links straight to the talent flow; Content /
Video / Photo / Application link to `projects.custom_project_request` for the signed-in
business (resolved client-side from the existing business selector). Anything outside those known
custom categories still falls back to the plain label (unchanged prior behavior).

**Section 7 — Content brief fields.** `custom_project_request.html` gained a CONTENT branch:
need/quantity, platform, location, deadline, style (budget range and notes were already
generic across all types).

**Section 8 — owner negotiation flow.** `wa_project_bridge.py` was audited only, per the explicit
"do not rewrite" instruction — its classification, offer-parsing, customer-facing message
rendering, and payment-response wording already satisfy every constraint in the spec (never
invents a price, strips owner-internal wording, points approved quotations to
app.kilasworks.id). No changes made; all its existing unit tests (`test_business_hub_v2_phase_fgh.py`)
still pass unchanged.

**Section 9 — payments in-app only; custom-project payment gate.** Verified unchanged:
`checkout_page` still requires `project.status == "APPROVED"`; confirmed the new `custom_content`
type flows through the exact same `create_custom_project` → `create_quotation` →
`approve_quotation` → checkout path as every other custom type (see
`test_custom_project_not_payable_before_quotation_approved`).

**Section 10/11/12 — owner WhatsApp notifications, idempotent, with deep links.** New module
`client-hub/owner_notifications.py` implements `notify_owner_once(event_key, event_type,
entity_id, business_id, message)` — a check-then-insert against a new UNIQUE `event_key` column,
so a logical event can only ever produce one row. Because Client Hub and the WhatsApp bot
(`app.py`) are separate processes with no shared in-memory state, the integration is a
durable-queue handoff (documented at length in the module's docstring): Client Hub writes a
PENDING row at the moment of the event; a new `app.py` endpoint, `GET
/cron/owner-notifications?key=<CRON_SECRET>` (same pattern as the existing `/cron/followups`),
polls PENDING/FAILED rows and does the actual send via the existing `send_whatsapp_message()` to
`OWNER_WHATSAPP_NUMBER`, marking each row SENT (never touched again) or FAILED (retried next
poll). Wired at every specified trigger point: `repo.set_business_status()` (AI onboarding ready
for review, and business becomes APPROVED for an AI Admin package → WhatsApp-connection-ready),
`projects_repo.create_custom_project()` (custom project submitted, excluding TALENT to avoid a
double notification), `talent_service.create_talent_request()` (talent request submitted),
`quotation_service.approve_quotation()` (quotation approved), and `routes_payments.py`'s
`invoice_page` POST handler (payment proof uploaded — the highest-priority event). All messages
are professional, concise Indonesian text with `https://app.kilasworks.id/admin/...` deep links
matching `routes_admin.py`'s actual URL patterns (`/business/<id>`, `/projects/<id>`,
`/payments/<id>`), no raw DB internals exposed. The genuine "human attention required" escalation
(G) has a builder function (`notify_human_attention_required`) ready to call from a future
escalation-detection point; no such detector currently exists in this codebase to wire it into, so
it is provided but not yet triggered anywhere — a known limitation, see below.

**Section 13 — owner-bot real DB queries.** Four new safe wrapper functions added to `app.py`
next to the existing `_get_open_projects_summary_safe`-family, following the exact same
never-raise / degrade-to-empty pattern: `_get_pending_payment_verifications_safe()`,
`_get_new_custom_project_requests_safe()`, `_get_new_talent_requests_safe()`, and
`_get_ai_admin_pipeline_status_safe()` (ready-for-review + waiting-WhatsApp-connection counts,
correctly excluding `package == "NONE"` businesses). These are query building blocks only — they
are not yet wired into the owner-message routing/NLU layer that decides *when* to call them
(that routing lives in the untouched, not-yet-live-wired `wa_project_bridge.py`); see limitations.

**Section 14 — admin status separation.** `routes_admin.py`'s `get_display_status()` now returns
`"ACTIVE_CUSTOMER_NO_AI_ADMIN"` for any `package == "NONE"` business, checked before the existing
AI Admin pipeline logic — such a business never shows up as e.g. `READY_FOR_REVIEW` or
`APPROVED_WAITING_WHATSAPP_CONNECTION`. The dashboard's `new_client_requests` action-center count
was also corrected to exclude `NONE`-package businesses (they never enter the AI onboarding
funnel, so counting them there was misleading).

**Section 15/17 — Talent preserved; landing page never shows a talent price.** Verified via the
untouched, still-passing `test_business_hub_v2_phase_bcd.py` (3 seed talents, custom-quote-only)
and `test_business_hub_v2_phase_i.py` / `test_prelaunch_hardening.py` (landing page + katalog PDF
never show a talent price). No changes needed.

**Section 16 — landing page stays marketing-only.** One small additive change:
`landing-page-kilasworks.html`'s nav bar gained a second CTA ("Masuk / Daftar") linking to
`https://app.kilasworks.id`, so a visitor who wants anything transactional has an actual path
there instead of only WhatsApp. No redesign; existing dark/orange/white styling and every other
CTA untouched.

**Section 19 — one canonical price source; historical prices frozen.** Verified unchanged:
`pricing_config.py` is still the only source seeding `service_catalog`;
`test_historical_transaction_price_unchanged_after_catalog_price_update` (existing test) still
passes. `generate_katalog_pdf.py`'s duplication of `app.py`'s `PRICING_CONFIG` is a pre-existing,
already-documented limitation — not touched this cycle (see limitations).

**Section 20 (priority gap) — live catalog price sync for the bot.** Added a new bridge block in
`app.py`: `_catalog_service` import (mirrors the existing bridge import pattern),
`_get_catalog_price_safe(catalog_key)` (returns `None` on any failure/CUSTOM_QUOTE/inactive item),
and `_build_live_price_sync_note_safe()`, which diffs a small explicit set of catalog_keys
(`ai_admin_basic`, `ai_admin_pro`, `content_basic/growth/pro`, `website_landing_page`,
`website_company_profile`) against their hardcoded `PRICING_CONFIG` figures and returns an
additive prompt note **only when they actually differ**. Wired into
`build_customer_system_prompt()` as `live_price_sync_note` (empty string when Client Hub is
unavailable or nothing has changed — confirmed byte-identical to prior behavior in
`test_live_catalog_price_sync_never_breaks_existing_pricing_config_regression_behavior`, and all
158+ pre-existing WhatsApp regression tests still pass unchanged). Any fallback is logged via
`print()` only, never shown to a customer. Skipped when a multi-tenant `tenant_context_block` is
already present (that block already carries the tenant's own canonical catalog).

**Section 21 — custom services never invent a price.** Verified unchanged in
`_build_tenant_context_block_safe()` and `wa_project_bridge.customer_price_response()` — both
already use the exact required wording pattern.

**Section 22/26 — new tests.** Two new test files, both passing in full (see counts below):
`client-hub/tests/test_business_hub_v2_ecosystem_sync.py` (15 tests — Sections 2–4, 6, 10, 11, 14)
and `test_ecosystem_sync_bot.py` at repo root (6 tests — Sections 13, 20, 23), including the
required negative test ("unrelated state change sends no notification") and an idempotency test
("calling the trigger twice must not send twice").

**Section 23 (security gap) — insecure-default audit.** `app.py` now logs a loud,
non-crashing startup warning — gated on Render's own auto-set `RENDER` env var (mirroring
`client-hub/app.py`'s `CLIENT_HUB_ENV == "production"` pattern) — whenever `VERIFY_TOKEN`,
`DASHBOARD_KEY`, or `CRON_SECRET` are still equal to their hardcoded defaults. It never logs the
actual secret value, only the env var name, and never crashes/gates startup (unlike Client Hub's
own `SECRET_KEY` check, which *does* crash-gate — deliberately not mirrored here because Render's
live env state for this file could not be verified from this sandbox). **Required manual step
before the next deploy: set real values for `VERIFY_TOKEN`, `DASHBOARD_KEY`, and `CRON_SECRET` in
Render's environment variables.** None of their current default values were changed.

**Section 24 — full regression.** See exact counts below; zero regressions.

**Section 25 — migration hygiene.** New migration `0010_owner_notifications_{sqlite,postgres}.sql`
(additive only — one new `CREATE TABLE IF NOT EXISTS owner_notifications` with two `CREATE INDEX
IF NOT EXISTS`), registered as the next entry in `client-hub/db.py`'s `MIGRATIONS` list, following
the exact same dual-dialect pattern as 0001–0009. No `ALTER TABLE` was needed for `businesses.package`
since it already has a permissive default and no CHECK constraint.

**Section 27/28** — see below.

## Test results (exact counts)

All commands run from a clean SQLite temp DB per file (`CLIENT_HUB_DB_PATH`), matching the
existing convention. **Zero failures across every suite.**

| Suite | Count | Result |
|---|---|---|
| client-hub/tests/test_client_hub_v1.py | 22 | PASS |
| client-hub/tests/test_production_foundation.py | 26 | PASS |
| client-hub/tests/test_business_hub_v2_phase_a.py | 10 | PASS |
| client-hub/tests/test_business_hub_v2_phase_bcd.py | 17 | PASS |
| client-hub/tests/test_business_hub_v2_phase_e.py | 5 | PASS |
| client-hub/tests/test_business_hub_v2_phase_fgh.py | 13 | PASS |
| client-hub/tests/test_business_hub_v2_phase_i.py | 3 | PASS |
| client-hub/tests/test_business_hub_v2_final_ops_polish.py | 18 | PASS |
| client-hub/tests/test_business_hub_v2_ecosystem_sync.py **(NEW)** | 15 | PASS |
| client-hub/scripts/postgres_smoke_test.py | run twice | PASS both |
| client-hub/scripts/postgres_smoke_test_v2.py | run twice | PASS both |
| root: test_appointment_flow_fix.py | included | PASS |
| root: test_appointment_payment_update.py | included | PASS |
| root: test_appointment_reminders.py | included | PASS |
| root: test_appointments.py | included | PASS |
| root: test_business_hub_v2_whatsapp_integration.py | 15 | PASS |
| root: test_demo_ux.py | included | PASS |
| root: test_final_launch_qa.py | included | PASS |
| root: test_language_layer.py | included | PASS |
| root: test_owner_catalog.py | included | PASS |
| root: test_owner_nlu.py | included | PASS |
| root: test_prelaunch_hardening.py | included | PASS |
| root: test_production_hardening.py | included | PASS |
| root: test_sales_engine.py | included | PASS |
| root: test_voice_note.py | included | PASS |
| root: test_voice_note_production_bugfix.py | included | PASS |
| root: test_ecosystem_sync_bot.py **(NEW)** | 6 | PASS |

New tests added this cycle: **21** (15 + 6). Preserved suites: **23** files (9 client-hub + 15
root, but counting root's whatsapp-integration suite once — 8 pre-existing client-hub suites + 15
pre-existing root suites), all still green, plus both Postgres smoke scripts run twice each with
no failures.

## Files changed / added

15 modified files, 5 new files (`client-hub/owner_notifications.py`, two migration files, two new
test files), plus this report and a minor landing-page edit — **21 files touched** in the commit
(see `git show --stat` on the commit below for the authoritative list).

## Known limitations / left for a future cycle

- The owner-bot's new query functions (Section 13) are query *building blocks* only — they are
  not yet wired into `wa_project_bridge.py`'s NLU routing (which decides when to answer "ada
  payment yang belum gue verifikasi?" etc.), because that routing layer is explicitly the
  not-yet-live-wired piece per `wa_project_bridge.py`'s own documented scope, and the instructions
  said not to rewrite that subsystem. Wiring the classification→query-function call is a small,
  well-scoped follow-up.
- `notify_human_attention_required()` exists and is tested but has no automatic trigger point yet
  — there is no existing "escalation detector" in this codebase to hook it into safely without
  inventing new detection logic, which was out of scope this cycle.
- `generate_katalog_pdf.py`'s duplication of `app.py`'s own `PRICING_CONFIG` (separate from Client
  Hub's `pricing_config.py`) is a pre-existing, already-documented limitation from an earlier
  cycle; not touched here to avoid unrelated risk.
- The `/cron/owner-notifications` endpoint requires an external scheduler hit (same as the
  existing `/cron/followups`) — this is a manual Render/cron-job.org setup step, not something
  this sandbox can configure.

## Required manual step before next deploy

Set real environment variable values on Render for: **`VERIFY_TOKEN`, `DASHBOARD_KEY`,
`CRON_SECRET`** (all three currently fall back to insecure hardcoded defaults if unset — the new
startup warning will fire in the Render logs if any are still on their default when the app boots
there). Also schedule an external hit to `GET /cron/owner-notifications?key=<CRON_SECRET>`
(e.g. via cron-job.org, same as the existing `/cron/followups`) so owner WhatsApp notifications
actually get delivered.

## Final commit and handoff ZIP

- Final commit hash: `5aa619c` (full: see `git log`)
- New ZIP: `kilas-works-business-hub-v2-5aa619c-ecosystem-sync-handoff.zip`
- ZIP SHA256: `fdce6fa26c313bb66e4a64993198578b8ce1e6b3ee78c4444c01852fcb8f915c`
- ZIP file count: `133`
- Supersedes: the prior cycle's handoff ZIP (no longer current)

READY FOR FINAL PRODUCTION REVIEW: YES
