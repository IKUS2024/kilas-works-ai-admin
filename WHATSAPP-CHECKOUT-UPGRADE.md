# WhatsApp-first checkout

## Deployment order

1. Back up PostgreSQL. Apply migration 0025 before deploying code to either service, using the existing Client Hub migration runner (`python -c "import db; db.init_schema()"` from `client-hub`). Keep normal production `RUN_MIGRATIONS_ON_BOOT` policy after the one-off migration.
2. Deploy Client Hub, then the platform bot using this same revision and shared database. No push was performed by this task.
3. Both services need the existing `INTERNAL_SERVICE_SECRET` with at least 32 characters, identical on both; never publish it. Both need `PUBLIC_APP_BASE_URL=https://app.kilasworks.id`. No new provider/model or environment variable is introduced. Client Hub's existing production environment setting and `SECRET_KEY` must keep Secure/HttpOnly session cookies enabled.
4. Test one WhatsApp purchase, brief submission, invoice and proof upload. Verification remains a Kilas Admin decision.

## Migration

`0025_whatsapp_checkout_{sqlite,postgres}.sql` adds a per-customer serialization row and scoped session table. Quotations become business-optional, matching existing ordinary projects/invoices. PostgreSQL relaxes only the NOT NULL constraint. SQLite requires a lossless table rebuild preserving every column/ID and invoice foreign key. Repeated migration/data preservation is tested; no historical prices are rewritten.

## Security and behavior

- Only the platform customer branch invokes intake, after existing Human Mode/tenant routing.
- Signed opaque token = random 256-bit session identity + HMAC using the existing internal secret. Only its hash authenticates persistent access; neither phone nor project ID appears in the token. Seven-day expiry. Random identity alone cannot grant access.
- Link uses a URL fragment, removed by browser JavaScript before CSRF-protected POST exchange. No token in server URL/access log. Grant is an order-only value in existing signed HttpOnly session; it never logs a user in. Responses are no-store/no-referrer. Keep proxy/application request-body logging disabled.
- Platform stored message history redacts checkout capabilities. The real outgoing WhatsApp link remains functional.
- All guest invoice/proof/quote operations derive project/invoice/payment from the bound session, not submitted IDs. An explicit logged-in action can attach that same project to the account; never creates a fake account/business.
- New projects remain REQUESTED until validated brief submission. Fixed service -> review -> existing checkout. Custom -> WAITING_FOR_QUOTE -> existing admin quotation -> explicit approval -> existing checkout. Transport is never silently added.
- Per-phone database row write lock serializes concurrent intake/guest writes on SQLite and PostgreSQL. Existing DB helpers suppress commits/retries inside the transaction. Attached-order authenticated checkout uses the same lock. SQLite two-connection concurrency tests executed; PostgreSQL executable/container was unavailable, so real PostgreSQL concurrency was not executed locally.
- Ordinary app payment/verification logic is preserved. Proof images use the existing payment-proof extraction path, with its existing API behavior; commerce/intake itself never calls AI. Tests mock/block external network calls. No additional conversational model call or retry.
- Admin sees source, phone/name when known, human-readable brief, missing fields, and copyable customer link. Quote availability is shown on the same link. Admin must send that link to the recorded customer; no new automatic outbound/template sender is introduced. Payment confirmation is shown on the page. Expired access can be renewed by admin without creating another project (old token revoked).
- Existing per-process failed-login limiter is reused in a separate namespace for invalid access attempts; it is not a distributed rate limiter.
- Deterministic prefill uses explicitly supplied labels/simple fact phrases and only customer turns, not model guesses. At most three essential questions on WhatsApp; remaining essentials/optional details go on the form. Unstructured ambiguous facts can be completed there.
- One unfinished order per sender/service is retained. Completed links show completed state; creating a fresh repeat order after completion is intentionally not automatic.
