# ASTRA PHASE 1 — CONVERSATION CORE + SAFE SIMULATOR

Repo: IKUS2024/kilas-works-ai-admin
Branch: feature/kilas-core-v2

READ FIRST, IN ORDER:
1. docs/KILAS_V2_MASTER.md
2. docs/KILAS_V2_AUDIT.md

GOAL:
Implement ONLY Phase 1 from the audit: a small, reusable, injected Kilas Conversation Core and route the authenticated owner simulator through it behind a default-off gate.

THIS IS NOT PUBLIC WEB CHAT YET.
THIS IS NOT JOBS YET.
THIS IS NOT WHATSAPP CUTOVER.
THIS IS NOT FINANCE INTEGRATION.

NON-NEGOTIABLE:
FINANCE IS A PROTECTED EXISTING MODULE.
Do not modify Finance routes, services, accounting logic, tables, migrations, templates, entitlements, balances, invoices, payments, branches, multi-currency, reports, or Finance AI behavior.

ALLOWED EXISTING FILE:
- client-hub/routes_client.py

ALLOWED NEW FILES:
- client-hub/kilas_core/__init__.py
- client-hub/kilas_core/contracts.py
- client-hub/kilas_core/service.py
- client-hub/kilas_core/flags.py
- client-hub/kilas_core/adapters/__init__.py
- client-hub/kilas_core/adapters/simulator.py
- client-hub/tests/test_kilas_core_contract.py
- client-hub/tests/test_kilas_core_simulator.py

Everything else is read-only unless a genuinely blocking issue is found. If blocked by something outside this allowlist, STOP and explain rather than expanding scope.

IMPLEMENTATION REQUIREMENTS:

1. CONTRACTS
Create validated inbound and result contracts for the core.
At minimum carry:
- business_id
- channel
- conversation_id or equivalent simulator conversation reference
- external_message_id when available
- actor_type
- text
- media references if supported; otherwise reject unsupported media clearly
- timestamp
Do not place Flask request objects, credentials, access tokens or channel clients inside contracts.

2. CORE SERVICE
Create one processing entry point with dependency injection.
It must not:
- send WhatsApp messages
- call the root webhook
- create Jobs
- write Finance
- run product search
- run checkout/payment
- execute live external actions

For this phase it should be able to use an injected understanding/reply provider and return a normalized result.

3. SIMULATOR ADAPTER
Wrap existing simulator behavior.
Preserve:
- authenticated owner/business access
- session/business scope
- current quota reservation behavior
- current simulation history behavior
- current onboarding/progress behavior
- current response contract as seen by the UI

Do not create fake phone numbers.
Do not write simulator traffic into the live WhatsApp Inbox.
Do not trigger outbound delivery.

4. FEATURE FLAG
Add KILAS_CORE_V2_ENABLED with default OFF.
Add a server-controlled test-business allowlist mechanism.
Do not reuse paid feature entitlements as the rollout flag.
Do not make the rollout flag user-editable.

When flag is OFF:
- simulator behavior must remain legacy-compatible.

When flag is ON for an allowed business:
- simulator must route through the new Conversation Core.

5. SAFETY
Unknown/unauthorized business must fail closed.
No cross-tenant history.
No fallback to platform tenant.
Errors must not trigger external side effects.
Do not import root app.py into client-hub.

6. TESTS
Add focused tests for:
- contract validation
- flag default-off behavior
- allowlist behavior
- authorized business routing
- unauthorized business rejection
- tenant isolation
- same external message / duplicate handling where applicable to simulator contract
- unsupported media behavior
- provider error behavior
- explicit assertion that simulator cannot send WhatsApp
- explicit assertion that simulator cannot create Jobs
- explicit assertion that simulator cannot write Finance
- existing quota/history remain coherent

Run only the relevant isolated/offline regression tests first.
Follow the repository's existing isolated test runner conventions.
Do not replace the existing test strategy with broad in-process pytest discovery.

7. NO DATABASE MIGRATION
Phase 1 requires no new schema.
Do not create or run migrations.

8. NO UI REDESIGN
Do not modify templates/static assets.
The current simulator UI should continue to work.

9. NO DEPLOYMENT
Do not deploy production.
Do not modify Render settings.
Do not touch production DB.

OUTPUT / COMPLETION:
- Implement the bounded Phase 1.
- Run relevant tests.
- Report exact files changed.
- Report test commands and results.
- Confirm Finance files were untouched.
- Confirm no migrations were added.
- Confirm no production deployment occurred.
- Before finishing, inspect git diff and ensure all changes are inside the allowlist above.

If Phase 1 is successful, STOP. Do not continue to Public Web Chat / Phase 2 in the same run.
