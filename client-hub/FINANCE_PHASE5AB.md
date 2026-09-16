# Finance Phase 5A + 5B — invoice document and manual customer sharing

Existing Finance draft → publish → receivable → received-payment workflow, invoice
numbers (`KFIN-…`) and integer IDR calculations are preserved. No platform billing,
AI, external sending provider, migration or schema change is involved.

## Document and print

The authenticated invoice view includes a shared white A4 document: current business
name, invoice number/status, issue/due dates, customer name/email/phone, items,
quantities, unit and line prices, subtotal/total, paid amount, balance and invoice
notes. DRAFT is prominently marked and cannot be shared. VOID is marked cancelled.
Overdue and balances reuse existing Finance calculations. No unsupported discount,
tax, company/address, bank account or payment instruction fields are invented.
Invoice notes are customer-visible; review them before sharing.

Print / Download PDF opens an authenticated standalone print view with no Client Hub
navigation, payment form, audit or internal controls. Use browser Print → Save as PDF,
A4, and disable browser headers/footers (which otherwise can include the URL).
The customer view prints the same document. CSS uses 14 mm margins, wrapping text,
repeated table headers and grouped totals. Mobile uses stacked item rows instead of
a wide table. No server PDF library or PDF-generation API is added. Browser/font
pagination can vary, especially with very long notes or many items.

## Share security and configuration

Authenticated POST `/business/<business_id>/finance/invoices/<invoice_id>/share`
requires the existing Finance access, login/membership and CSRF checks. Only ISSUED,
PARTIALLY_PAID or PAID invoices are shareable. It renders Copy Link/Open Customer View
controls; clipboard failure leaves a selectable input for manual copying. No sending
or financial database write happens. Refreshing share can generate another token,
but cannot create an invoice/payment.

Public read-only GET `/finance/invoice-share/<token>` verifies a dedicated-purpose,
SHA-256 signed timed token BEFORE invoice queries. Token contains only the business
and invoice locator plus purpose, not customer/financial contents or signing secrets.
Itsdangerous and existing Flask SECRET_KEY are reused. Signature binds both identities
and purpose; TTL is seven days. Tokens are signed, not encrypted. Treat the entire
link as a private bearer capability; do not decode/display its internals to customers.

The server loads only the signed business's matching Finance invoice/customer and
items, and checks its current state every time. DRAFT/VOID, mismatched IDs, bad-purpose,
expired/tampered/malformed tokens all return the same unavailable response. No public
mutation route exists. No account IDs, audit data, internal customer notes, payment
notes, account names or unrelated invoices appear in the customer projection.
Stored text is autoescaped. Status reflects the current Finance records when opened;
a saved PDF is a static snapshot. Concurrent updates can cause a brief read skew
between existing service queries; refresh to see the latest status.

Required existing server configuration:
- `SECRET_KEY`: strong random stable key, at least 32 characters in production;
  missing/short/known development default keys cannot issue/verify share links.
- `PUBLIC_APP_BASE_URL`: canonical HTTPS origin, e.g. `https://app.kilasworks.id`;
  no credentials, query, fragment or subpath. No Host-header fallback. Missing/invalid
  configuration fails safely and leaves ordinary invoice/print functionality working.
- Existing Finance beta/access rules are unchanged. No new environment variable.

Public pages have no external assets/tracking, use no-referrer, private/no-store,
noindex/nofollow/noarchive and frame denial headers. Never log tokens in application
code; configure reverse-proxy access logging to redact share URL paths if necessary.
Anyone holding a valid link can view that single invoice, including customer contact
and notes. Share only with intended recipients. No recipient login/email verification
or per-link revocation store is added. Expiry or signing-key rotation invalidates
links; VOID invoices are inaccessible immediately on subsequent requests. Key rotation
also affects existing Flask sessions. Do not void a valid invoice merely to revoke a
link; use expiry/key management appropriate to the incident.

## Tests

Run separately with local disposable databases and HTTP mocked/blocked:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/offline_tests:client-hub:client-hub/tests python client-hub/tests/test_finance_phase5ab.py

Run existing test_finance_phase1a/1b/2a/2b/3/4a/4b/4c.py, test_app_service_briefs.py
and test_postgres_sql_adapter_external_audit.py as regressions. No live provider or
production migrations are required. Layout assertions cover A4, print-hidden controls,
mobile stacked rows and escaping. Manual Chrome/Android Print → Save as PDF remains a
rollout check; browser installation in the build environment may be unavailable.

Local print verification: rendered short and 35-item invoices through WeasyPrint in
the development environment only (not an application dependency). Verified A4 page
size, all item text present, no print controls, and inspected first/last page images.
Chromium download timed out; actual Chrome/Android interactive/mobile verification
remains a manual rollout check. No PDF artifacts or renderer dependencies are shipped.
