# Phase 5C — Receivables & collection workspace

## Behavior

Pelanggan & Piutang → Penagihan & Aging opens a read-only collection queue.
Existing create/publish/payment routes remain authoritative. Customer cards and
queue cards link to Customer Statement; queue cards and authenticated statement invoice numbers link to invoice/payment entry. Standalone print and public statements contain no admin invoice links.
No financial record, reminder state, audit record or configuration is written by
the new workspace, statement, sharing or reminder routes. No AI or sending API.

Aging reuses Phase 3 invoice/payment calculations and a shared pure bucket helper.
Server date is the statement date. Only current ISSUED/PARTIALLY_PAID invoices
issued on/before that date with positive remaining balance count. Payments dated
on/before that date count, consistent with Phase 3. Current invoice status remains
authoritative (not historical status reconstruction). Draft/VOID/PAID are excluded.
Money remains integer IDR. Due today is current, not overdue:

- Current: zero days overdue, including future due dates.
- 1–30, 31–60, 61–90, and **more than 90** days overdue (91+).

Each bucket has invoice count and remaining balance. Summary shows total/overdue
balances and open/overdue counts. No opaque priority score. Sort by longest overdue,
largest balance, earliest due date, or customer name; invoice ID is the stable final
tie-breaker. Filters: all open, overdue, or due today through seven days ahead.
Summary always describes all open invoices, not only the filtered queue.

Queue uses 50 cards/page; responsive cards avoid wide tables. SQL filters published
open states and optional customer **before** the existing 50,000-row report cap.
One bounded invoice query aggregates payments/items without application N+1 queries.
Totals never silently use a truncated dataset: the report cap fails safely instead.
This is not a cursor-based large-enterprise reporting system.

## Customer statement / print

One customer's open invoices, issue/due dates, total/paid/remaining amounts, status,
days overdue and total/overdue balance. Paid invoices are omitted, not deleted;
their history remains in the existing invoice/receivables views. No private customer
notes, invoice notes, payment notes, ledger/account/audit metadata, or internal IDs
are shown. Empty position explicitly shows no open receivables.

Print / Save as PDF opens a standalone page using the Phase 5A A4 print CSS,
14 mm margins, repeated table headings, row break avoidance and grouped totals.
Print hides controls and has no Client Hub navigation. Choose A4 and disable browser
headers/footers (otherwise the private URL may print). Mobile item rows stack below
600 px. Browser-specific pagination can vary; inspect long statements before sending.

## Manual reminders

Only currently overdue, published invoices with a positive balance can generate a
reminder. Friendly and firm-but-polite deterministic Indonesian wording uses current
customer name, invoice number, due date and existing invoice balance calculation.
No made-up fees, penalties, contact history or promises. Copy uses Clipboard API;
failure selects the readonly textarea for manual copying. Nothing is sent or marked
as sent. Refresh/check the invoice before sending, especially after concurrent payments.
Persistent reminder tracking is intentionally omitted: no suitable existing storage.

## Signed statement sharing / security

Authenticated POST statement/share uses existing Finance beta, authentication,
membership and CSRF guards, then checks business/customer ownership server-side.
The Phase 5B serializer/strong key checks, canonical HTTPS PUBLIC_APP_BASE_URL and
seven-day expiry are reused. Exact payload keys: purpose, business_id, customer_id;
purpose is `finance_customer_statement`. Invoice and statement tokens are not
interchangeable. Signature is verified BEFORE customer/invoice lookup. Invalid,
expired, tampered or mismatched combinations are unavailable. No URL query ID override.

Public GET is read-only and exposes only that signed customer's open invoice position.
The link is a **live customer-wide bearer capability**, not a single-invoice snapshot:
new published open invoices for that same customer also appear during its lifetime.
The share UI explicitly warns the issuer. No recipient login or per-link revocation
store; expiry/key rotation invalidates links (rotation affects existing sessions).
Do not share links with unintended recipients. Signed locators are not encrypted;
no financial/customer text or secret appears in token payload. Business/customer
IDs are not printed into public page markup. All stored text is autoescaped.

Privacy headers: no-store, no-referrer, noindex/nofollow/noarchive, frame denial.
No external assets. Configure proxy/access logs to redact the bearer-token path;
application logs use a static error code only, never tokens or financial text.
Existing `SECRET_KEY` (strong, stable, >=32 chars) and HTTPS `PUBLIC_APP_BASE_URL`
remain required for sharing. No new environment variable. No migration or provider.

## Verification / limitations

Offline disposable database tests (all external HTTP blocked):

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/offline_tests:client-hub:client-hub/tests python client-hub/tests/test_finance_phase5c.py

Run regression files in separate Python processes: the existing Phase 1A fixture changes the global database path, so combined unittest discovery is unsupported.

Regressions: test_finance_phase1a/1b/2a/2b/3/4a/4b/4c/5ab.py,
test_app_service_briefs.py and test_postgres_sql_adapter_external_audit.py.
No production migration, push, deploy, AI call or messaging integration.
No Phase 6 work. Real PostgreSQL execution and Chrome/Android manual print/layout
checks depend on the deployment environment; mocked adapter tests are not a claim
of real PostgreSQL verification. Customer identity and invoice reads can briefly
reflect different concurrent snapshots; reload to see the latest state.

Local print verification rendered 2-invoice and 38-invoice statements to A4 (one
and six pages respectively), verified all invoice numbers and hidden print controls,
and visually inspected first/last pages. WeasyPrint was used only as a local test
tool, not added as an application dependency. Mobile layout is covered by responsive
markup/CSS assertions; actual Chrome/Android interaction remains a manual rollout check because this runtime has no Chromium executable.

Final local regression results (each suite isolated, network blocked):

| Suite | Passed | Failed |
| --- | ---: | ---: |
| test_finance_phase1a.py | 15 | 0 |
| test_finance_phase1b.py | 16 | 0 |
| test_finance_phase2a.py | 25 | 0 |
| test_finance_phase2b.py | 22 | 0 |
| test_finance_phase3.py | 19 | 0 |
| test_finance_phase4a.py | 15 | 0 |
| test_finance_phase4b.py | 35 | 0 |
| test_finance_phase4c.py | 25 | 0 |
| test_finance_phase5ab.py | 24 | 0 |
| test_finance_phase5c.py | 30 | 0 |
| test_app_service_briefs.py | 18 | 0 |
| test_postgres_sql_adapter_external_audit.py | 2 | 0 |
| test_client_hub_v1.py | 22 | 0 |
| test_production_foundation.py | 26 | 0 |
| test_business_hub_v2_phase_a.py | 19 | 0 |
| test_client_hub_batch1.py | 16 | 0 |
| test_client_hub_batch2_3.py | 14 | 0 |

Total: 343 passed, 0 failed. Phase 5C: 30 passed.
Initial combined discovery failed because Phase 1A leaves a removed temporary DB path; isolated reruns passed. Pytest is unavailable; existing unittest/script runners were used, and both SQL adapter functions were invoked directly.
