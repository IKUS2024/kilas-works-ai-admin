# Kilas V2 Phase 3 status

Status: COMPLETE

Branch: `feature/kilas-core-v2`.
Verified code/test head: `b64369caa4cac29e0a69f5011424bc63c8d9dfaf`.
Completed: 2026-09-24. The final checkpoint changes this status document only.

## Prerequisites and resume boundary

Phase 1 is COMPLETE. Phase 2 release verification is accepted as passed per the
product owner's confirmation of full GitHub Actions run `36009442066`.
Historical pending text in Phase 2 documents does not reopen that prerequisite.

Resumed Phase 3 at `0b6d1fe688d710a096cff1338e24e1ddb8488dbd`; completed Customers
implementation was retained. Inspected failed run `36009442153`, job `107666042108`.
It failed because an imported Phase 2 unittest class was rediscovered and because
the inherited owner fixture had membership in both businesses. No production
assertions, authorization checks, or tenant security were weakened.

## Completed milestones

- Additive SQLite/PostgreSQL migration pair `0056` and explicit schema installer.
- Tenant-scoped durable Customers, WEB visitor identities, and conversation links.
- Same valid visitor reuses its customer within one tenant; cross-tenant identities
  remain separate. Names and unverified contact details do not merge customers.
- Owner Customers list/search/detail/profile/notes and conversation history links.
- WEB Inbox customer names and Customers navigation; business-first/text-first only.
- SQLite, PostgreSQL, tenant/security, protected-write, and mobile-browser verification.

Resume commits:
- `155e8d3bc2f8f7380b62679c277b64d9b8261eb3`: module import isolates unittest discovery;
  businesses 7/8 have separate synthetic owners; PostgreSQL fixture seeds channel parents.
- `b64369caa4cac29e0a69f5011424bc63c8d9dfaf`: invalid/duplicate identity rejection,
  bidirectional forged read/edit rejection, and protected-write flow coverage.

## Verification evidence

Final Phase 3 CI: [run 36010570980](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36010570980),
job `107669889873`, exact verified head above: SUCCESS, including all cleanup steps.

| Gate | Result |
| --- | --- |
| Phase 1 contract + simulator regression | PASS, 30 tests locally; same suites PASS in final CI |
| Phase 2 focused routes + store regression | PASS, 27 tests locally; same suites PASS in final CI |
| Phase 3 Customers SQLite | PASS, 9 tests locally and final CI; no imported Phase 2 class rediscovery |
| PostgreSQL 18 / Phase 2 additive 0055 runtime | PASS, 4 tests in final CI |
| PostgreSQL 18 / Phase 3 additive 0056 runtime | PASS, 2 tests in final CI |
| Mobile Chromium, 390 x 844 viewport | PASS, Customers list/detail/edit, Inbox name/link, takeover/reply and visitor delivery |
| Tenant isolation | PASS, separate owners; cross-tenant read/edit rejected, original records unchanged |
| Invalid/ambiguous identity | PASS, forged visitor access rejected; duplicate tenant identity fails uniqueness without extra customer/message |
| Protected write boundaries | PASS, full WEB/customer/profile/takeover/reply flow with SQLite write authorizers and Finance/WhatsApp spies |
| Exact diff / whitespace | PASS, reviewed full Phase 3 and narrow resume diffs; git diff --check clean |

Commands: `python scripts/run_offline_tests.py --only test_kilas_core`,
`--only test_public_chat_routes.py`, `--only test_public_chat_store.py`,
`--only test_kilas_customers.py`; CI also runs
`python client-hub/tests/test_public_chat_postgres.py`,
`python client-hub/tests/test_kilas_customers_postgres.py`, and
`python client-hub/tests/public_chat_browser_qa.py` with their explicit QA flags.

PostgreSQL validation used a disposable CI PostgreSQL 18 service and synthetic
businesses. Phase 3 builds minimal prerequisites and applies 0055/0056 explicitly;
no historical migration replay is needed for that validation. No production DB
or customer data was used. Browser QA used the real Flask/Core/store/auth/UI with
synthetic tenants and a stubbed model transport; this is not a live AI-provider or
Render staging certification. The real Chromium mobile gate passed in CI.

Browser artifact: `kilas-phase3-browser-qa`, ID `10812516419`, from final run above.
Screenshots `03_customer_profile.png`, `04_owner_takeover.png`, and
`05_customer_human_reply.png` were downloaded and visually inspected: profile save,
linked customer name in WEB Inbox, and human reply delivered to visitor are visible.

## Exact scope

Full Phase 3 diff baseline: `3b41f7895960cc69ea71c47295c07547541c4ba0`.
Exact changed files through the verified head (final status-only commit adds no paths):

- `.github/workflows/kilas-v2-phase3-qa.yml`
- `client-hub/app.py`
- `client-hub/kilas_core/customer_routes.py`
- `client-hub/kilas_core/customer_schema.py`
- `client-hub/kilas_core/customers.py`
- `client-hub/migrations/0056_kilas_core_customers_postgres.sql`
- `client-hub/migrations/0056_kilas_core_customers_sqlite.sql`
- `client-hub/public_chat/owner.py`
- `client-hub/public_chat/store.py`
- `client-hub/templates/customer_detail.html`
- `client-hub/templates/customers.html`
- `client-hub/templates/product_dashboard.html`
- `client-hub/templates/web_inbox.html`
- `client-hub/tests/public_chat_browser_qa.py`
- `client-hub/tests/public_chat_dev.py`
- `client-hub/tests/test_kilas_core_simulator.py`
- `client-hub/tests/test_kilas_customers.py`
- `client-hub/tests/test_kilas_customers_postgres.py`
- `docs/KILAS_V2_PHASE2_STATUS.md`
- `docs/KILAS_V2_PHASE3_STATUS.md`

The Phase 2 status file in that list is inherited documentation history; it was not
changed during this resume. The pre-existing 0053 SQLite fix predates this Phase 3
baseline. The only migration pair added by Phase 3 is 0056: separate Core customer,
identity, and WEB link tables with tenant constraints; no Finance schema changes.
The existing simulator test guard was scoped to actual Phase 1 execution modules
when Customers gained persistence; Phase 1 runtime code remains unchanged.

This resume changed exactly:
- `client-hub/tests/test_kilas_customers.py`
- `client-hub/tests/test_kilas_customers_postgres.py`
- `docs/KILAS_V2_PHASE3_STATUS.md`

Finance implementation/accounting tables and production WhatsApp paths are unchanged
by Phase 3. WEB flow tests deny writes outside the explicitly allowed Core/WEB,
audit, usage-ledger, and SQLite sequence tables and assert Finance write/WhatsApp
send entry points are never called. Production require_business_access is unchanged.
No production deployment, WhatsApp cutover, Jobs, Playbooks, Finance Bridge, media AI,
or creative studio work was performed. Feature enablement/production rollout is not
part of this completed verification.

Remaining Phase 3 work: none. STOP. Do not start Phase 4 automatically.
