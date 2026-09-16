# Phase 4B — confirmed Finance actions (internal beta)

Supported: **create expense**, **create income**, **record received payment against
an existing Finance invoice**. Invoice creation/issuing remains in the existing
Invoice Finance UI; it is deliberately not an AI action in this release. No delete,
edit, bank transfer, automatic charge, bulk or recurring action is supported.
Platform invoices/payments, subscriptions and all other products are untouched.

## Access and configuration

Set `KILAS_FINANCE_OPERATOR_BUSINESS_IDS` to ONLY the verified existing Kilas Works
business ID. Empty/unset denies everyone (including admins) with 404 and hides the
UI. Do not infer the ID from a name. This is independent of the existing analyst
allowlist; Phase 4A remains read-only. The normal Finance beta gate, login, existing
business membership/admin access rules, and JSON CSRF remain in force on every
operator route. Even allowlisted IDs cannot bypass membership checks.

Reuse existing server `SECRET_KEY` (stable and strong in production),
`ANTHROPIC_API_KEY`, and optional `CLIENT_HUB_FINANCE_ANALYST_MODEL` (default
`claude-haiku-4-5-20251001`). No new credentials or SDK required. No secret appears in
HTML or JSON. No migrations or production database changes during installation.

## Flow and endpoints

- GET `/business/<id>/finance/operator`: no AI/write. Shows account/category and
  at most 100 current unpaid Finance invoice choices for this business.
- POST `.../operator/draft`: explicit chosen action + request (max 1,000 chars),
  chosen date/account/category/invoice. The server authorizes and validates those
  references before AI. One bounded Anthropic request (400 output tokens, 5/25s
  timeout, no redirect/retry) extracts only action, literal amount and description.
  Only request text and selected action reach AI, not financial records or IDs.
- Strict schema rejects unknown fields/actions. Returned action must equal the
  explicitly selected action. Amount and description must be grounded literal
  substrings. Decimal parsing, not model arithmetic, converts rupiah/rb/ribu/jt/juta
  into positive signed-BIGINT-range whole rupiah. Negative, float/boolean, fractional
  rupiah, expressions or unsupported formats are rejected. Account/category/invoice
  are server-resolved again. Preview includes all executed fields.
- Server signs normalized fields, action, user, business and random nonce with
  SHA-256 and a dedicated itsdangerous salt. TTL 10 minutes. Signed, **not encrypted**:
  keep draft tokens private; they contain the preview data, not credentials. Tokens
  stay in browser memory, not URL/localStorage. Draft generation has zero DB writes,
  including no AI usage-ledger/audit writes. Six draft attempts/user/minute share the
  existing analyst in-process limiter; multiple workers/restarts are not a global cap.
- POST `.../operator/confirm`: requires JSON `{token, confirm: true}` plus CSRF.
  No other fields accepted. Authentication, membership, allowlist, signature, expiry,
  user/business binding, schema, amounts, date and tenant-owned references are
  rechecked. Existing Finance service validates again inside its transaction before
  writing. Payment status/outstanding are checked in the existing payment service;
  overpayment or stale invoice state fails without partial writes. No AI on confirm.
- Cancel simply drops the browser draft and writes nothing. A copied signed token
  is not centrally revoked by browser cancel; it still requires valid user/access,
  CSRF and explicit confirmation before expiry. Refresh also does not confirm.
- On ambiguous network/commit result, retain and retry the **same** draft or inspect
  Finance history; do not generate a new draft. Completed responses show stored record
  ID. Model output never supplies success wording or directly invokes write functions.

## Persistent double-submit protection without migration

Expense/income uses existing transaction `source_type=FINANCE_OPERATOR` and
`source_ref=<signed draft nonce>`. The existing business write lock serializes
lookup, create and audit in one transaction. Matching replay returns the original
record ID; mismatched fields/actor are rejected. The check also finds VOID rows,
so replay cannot create a replacement for a voided record. Existing nonoperator
transaction behavior is unchanged. Invoice payment uses its existing persistent
unique idempotency key (`operator_<nonce>`) and atomic ledger/payment/audit path.
No nested transactions, background jobs or new idempotency table.

Protection is for the **same draft**, across processes/restarts. Two separately
generated and explicitly confirmed drafts are independent entries; this is not a
semantic duplicate detector. The expense/income lock convention, not a new unique
constraint, enforces source-key uniqueness; do not bypass service writers or alter
source keys. Expired drafts cannot replay even when previously executed: inspect
history before creating another. Changed/disabled references can reject a replay
safely without making a duplicate. No automatic re-issue/retry or silent write.

## Reliability and tests

Untrusted user/record text cannot become system instructions. No AI tools exist.
All rendered text uses autoescaping/textContent. Only fixed diagnostic categories
are logged; no requests, tokens, raw model text, amounts or credentials. Interpretation
can still misunderstand an ambiguous request, which is why human review is mandatory.
Full database snapshots prove draft/cancel/analysis do not mutate state. Tests cover
signature expiry/tamper, actor/tenant binding, allowlist/membership revocation, CSRF,
references, amounts, stale invoice balances, audit rollback, no extra AI calls,
persistent replay and two actual concurrent SQLite connections.

Run with local test database and mocked HTTP:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=client-hub:client-hub/tests python client-hub/tests/test_finance_phase4b.py

Also run the Phase 1A/1B/2A/2B/3/4A Finance suites, app-service-brief tests and existing
PostgreSQL SQL-adapter tests separately. No live Meta/AI or production migrations.
A live PostgreSQL server/container was unavailable; real PostgreSQL concurrency was
not executed. The existing business-row transaction lock is reused unchanged.
