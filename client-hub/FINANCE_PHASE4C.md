# Phase 4C — Finance AI production hardening

This document supersedes the quota/configuration details in Phase 4A/4B docs.
No schema change, migration, deployment or production data migration is included.
All changes are inside Client Hub. Platform billing, root AI, WhatsApp, pricing and
subscription behavior are untouched.

## Final architecture and security

- Analyst: authenticated business + Finance beta + analyst allowlist → validated
  question → existing Phase 3 deterministic, bounded IDR aggregates → one bounded
  Anthropic call → facts separated from narrative. No DB writes, including usage
  ledger/audit/chat writes. Prompt/records are untrusted data, never system rules.
- Operator: independently allowlisted business + existing user access → explicit
  action/request and chosen references/date → one AI extraction → strict validation
  → signed preview → explicit JSON confirmation with existing CSRF → revalidation
  → existing transactional Finance service. No AI call during confirmation.
- Supported actions remain expense, income and recording received invoice payment.
  No new financial action or automatic execution. Normal Finance services and reports
  remain authoritative; no platform invoices are queried by Finance AI.
- Draft signatures bind version, user, business, action, normalized fields and nonce.
  Strict types reject bool IDs/version, action swapping, extra fields, wrong references,
  tampering and expired signatures. Server checks all references again; service writes
  check ownership under the existing business transaction lock. Browser IDs never
  authorize access. No model-generated record IDs are accepted.
- HTTP methods, JSON content type and 8 KiB limit are enforced. Duplicate JSON keys,
  nonfinite values, unknown fields and non-object requests are rejected. Model responses
  require exactly one text block, end_turn, strict object/schema and bounded content.
  Refusal, truncation, malformed/empty content, timeout and 4xx/5xx fail safely with no
  write or provider retry. Error details never reach the browser.
- Existing budgets remain: question 1,000 chars; analyst context 6,000 chars and output
  700 tokens; operator output 400 tokens. Connect/read timeout 5/25 seconds, no redirects.
  GET/pages/reports and operator confirmation make no model call. No usage DB writes.
- Finance AI pages/responses use private/no-store. Existing global CSRF is not changed.

## Required production configuration

- Existing `KILAS_FINANCE_BETA` rules continue to apply.
- `KILAS_FINANCE_ANALYST_BUSINESS_IDS` and `KILAS_FINANCE_OPERATOR_BUSINESS_IDS`:
  independently set to the verified existing Kilas Works ID only for initial beta.
  Empty disables. Every entry must be a positive signed-BIGINT-range decimal ID;
  malformed entries, trailing comma, wildcard or excess size deny the ENTIRE setting.
  There is no implicit administrator bypass of either allowlist.
- Existing `ANTHROPIC_API_KEY`: nonempty, no internal whitespace. Missing/invalid
  configuration prevents calls and returns a generic 503, not an executed draft.
- Optional `CLIENT_HUB_FINANCE_ANALYST_MODEL`: default remains
  `claude-haiku-4-5-20251001`. Invalid identifier fails closed; no provider/model switch.
- Existing `SECRET_KEY`: strong random stable key, at least 32 characters. Operator
  rejects missing/short/known development default keys outside tests before paid calls.
  All workers must use the same key. Rotation invalidates pending drafts and existing
  Flask sessions per existing behavior. No credential is exposed in HTML/tokens.

## Quotas and limitations

No distributed limiter exists in the inspected Client Hub infrastructure. Reuse its
thread-safe in-process approach without adding a DB quota writer or new infrastructure:

| Bucket | Per user across businesses | Per business across users | Window |
| --- | ---: | ---: | --- |
| Analyst + operator draft combined | 6 | 20 | 60 seconds |
| Confirmation attempts, including malformed/replayed tokens | 30 | 60 | 60 seconds |

Maps are bounded to 4,096 live keys and fail closed at capacity. Buckets expire using
monotonic time. 429 includes Retry-After: 60. Endpoint hopping does not evade the
combined AI quota; confirmation remains available after AI quota exhaustion. Normal
non-AI Finance routes are unaffected. Oversized/wrong-content-type bodies are rejected
before expensive parsing. Quotas are NOT global across workers/instances and reset
on restart. For this beta, use a single application worker/instance or apply an
existing external shared limiter before expanding; this patch does not configure it.

## Idempotency, concurrency and cancel

Existing SQLite/PostgreSQL business-row locking serializes lookup + financial write
+ audit commit. No nested transactions or new adapter-specific SQL was added.
Expense/income reuse the signed nonce in existing FINANCE_OPERATOR source fields.
Those source markers can no longer be removed/swapped by update_transaction, or
introduced onto an unrelated existing row. Replay checks all normalized fields/actor,
returns the existing row, or safely rejects conflict. VOID rows still prevent replay
from creating a replacement. Existing permitted field edits remain possible, but a
changed amount/data makes a replay reject, never create another row.

Invoice payment retains its existing persistent unique idempotency key and atomic
ledger/invoice/audit transaction. Concurrent different drafts cannot overpay the same
invoice because balance/status is checked inside the same business lock. Accepted
replay does not mean a new payment was recorded. Expense replay lookup has no new
unique constraint: it relies on all writes going through existing locking services.
Do not bypass those services with direct SQL that rewrites/deletes source markers.

Drafts remain valid for 10 minutes. Cancel only discards the browser copy and never
writes; a copied token is not centrally revoked. Reliable multi-worker revocation
would require persistent/shared state; deliberately not replaced with misleading
per-process revocation. The copied token still requires the same authenticated user,
business access/allowlist, CSRF and explicit confirmation before expiry. On uncertain
network/commit outcome, retry the SAME draft or inspect Finance history. Two separately
generated and confirmed legitimate drafts remain separate intentional actions.

## Observability and performance

`kilas.finance_ai` logs INFO events using a fixed allowlist: analyst success/failure,
draft generated, confirmation accepted/rejected, replay, expired/tampered drafts,
permission/allowlist denial, rate limit, configuration, timeout and upstream failure.
No business/user IDs, amounts, record text, raw provider errors, credentials or tokens
are logged. Existing successful Finance audit writes remain transactionally coupled
to execution; generating/denying a draft does not create audit rows.

Operator reference validation uses scoped ID lookups, not whole account/category
lists per confirmation. The invoice picker queries only 100 eligible invoice IDs/numbers
with a SQL LIMIT; it no longer loads the whole invoice history or notes. Phase 3
calculations/limits and read-only semantics remain unchanged.

## Offline verification and rollout

Run from repo root in separate processes, with mocked HTTP and local test DB:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/offline_tests:client-hub:client-hub/tests python client-hub/tests/test_finance_phase4c.py

Also run Finance phase1a, phase1b, phase2a, phase2b, phase3, phase4a, phase4b suites,
`test_app_service_briefs.py`, and `test_postgres_sql_adapter_external_audit.py`.
No external AI/Meta calls. Fixtures initialize only disposable SQLite databases.
Tests cover real concurrent SQLite connections for same expense/payment drafts and
competing invoice payments, full DB snapshots for read-only/failure cases, CSRF,
allowlists, tenant/user binding, schema failures, safe logging and quota boundaries.
No PostgreSQL server/container is available locally: real PostgreSQL concurrency is
NOT claimed. Existing PostgreSQL SQL-adapter tests pass but are not an integration test.

Before production rollout (operator-managed, not performed by this task):
1. Verify prerequisites from Finance phases 1–3 already installed; no migration here.
2. Verify Kilas Works business ID, independent allowlists, production environment,
   HTTPS secure cookies and strong shared SECRET_KEY. Keep all other tenants disabled.
3. Confirm API configuration and worker/instance count; arrange a shared external
   limiter before treating per-process quotas as a global spend limit.
4. Run the concurrency scenarios against a disposable PostgreSQL database matching
   production BEFORE broadening beta: same-draft expense/payment, competing payments,
   audit rollback and transient commit/network failure. Never use production test data.
5. Deploy manually only after review; inspect fixed event logs. Smoke-test analyst,
   draft/cancel, one explicit confirmation and same-token retry in controlled beta.
6. If uncertain outcome occurs, inspect existing Finance history; do not regenerate
   and confirm a replacement draft blindly. Roll back access by emptying allowlists.
