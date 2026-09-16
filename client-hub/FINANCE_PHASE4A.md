# Finance Phase 4A — internal read-only analyst

Finance → AI Analyst uses the existing authenticated business membership checks,
Finance beta gate, and an independent server-only business allowlist. No implicit
admin bypass of the analyst allowlist. Configure only the verified existing Kilas
Works business ID; do not infer it from a display name or choose an arbitrary ID.

Configuration (server environment, no schema change):
- `KILAS_FINANCE_ANALYST_BUSINESS_IDS`: comma-separated business IDs; empty disables
  access for everyone, including administrators. Initially set only Kilas Works.
- Existing `KILAS_FINANCE_BETA` gate continues to apply.
- Existing `ANTHROPIC_API_KEY`; missing credentials return a safe error.
- Optional `CLIENT_HUB_FINANCE_ANALYST_MODEL`, default `claude-haiku-4-5-20251001`.
  Other AI model settings and behaviors are unchanged.

GET/POST `/business/<id>/finance/analyst`: login and business access are enforced
before allowlist checks. POST uses existing JSON CSRF validation. Browser-supplied
extra fields/business IDs are rejected. The route ID is authorized server-side and
all Phase 3 report calls also receive the authenticated actor ID.

The service has no AI tools, SQL writer, audit writer, usage-ledger writer, saved
conversation, or automatic action. Existing report helpers calculate integer IDR
metrics. The entire SQLite database is compared before/after in a regression test.
Normal Finance functionality and migrations are untouched. Anthropic receives only
the question and bounded financial aggregates; never full configuration or records.
Database text is untrusted data in a separate user message, not system instructions.
The browser renders all returned content with textContent, never HTML.

Choose a calendar month and one focus: cashflow summary, previous-month comparison,
top five expense categories, or receivables aging. No raw invoice notes, contact
information, transaction descriptions or uploaded files are sent. Existing Phase 3
query limits still apply. Context is capped at 6,000 characters; question at 1,000;
HTTP body at 8 KiB. One explicit submit makes at most one Anthropic request, output
700 tokens, connect/read timeouts 5/25 seconds, no redirects or retries. Six attempts
per user/minute in process; worker/restart limits are not globally coordinated.
GET, normal Finance writes, and report loading never invoke this analyst.

Server facts are displayed separately from AI observations and suggestions. Model
output accepts only bounded narrative plus references to existing fact IDs. Numeric
narrative/monetary notation and unknown fact references are rejected. This is a
conservative guard, not proof that qualitative AI interpretations are correct;
review suggestions. Missing data must be acknowledged. Cash flow is not profit.
Month comparisons use full calendar months (including future-dated recorded items).
Aging uses current invoice status with payments through the selected month end,
matching Phase 3; it does not reconstruct historical status. Concurrent report
queries are not a frozen accounting snapshot. Unavailable detail (vendors, individual
invoice identification, recurring schedules or proven anomalies) is explicitly
out of this initial bounded context; use existing reports/receivables pages.

No database migration, production migration, push or deployment is required by tests.
Run from repository root with dependencies already installed:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=client-hub:client-hub/tests python client-hub/tests/test_finance_phase4a.py

Run existing `test_finance_phase1a.py`, `test_finance_phase1b.py`,
`test_finance_phase2a.py`, `test_finance_phase2b.py`, `test_finance_phase3.py` and
`test_app_service_briefs.py` in separate processes with the same environment.
All analyst HTTP is mocked; no paid API is called. No real PostgreSQL concurrency
or live model verification is claimed.
