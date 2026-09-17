# Finance Phase 6C — Unified Assistant & Final Hardening

Implemented on unchanged Phase 6B parent:
`6f7f99a2ad44d4487b9e6e70e93b0807240a2944`.
Phase 6A remains `4d9631b1f6a925f52d50ed1483f578fdef5f89fb`.
The unchanged local origin/main reference is `6886dccdc86e2cd4d9aec3c96b0672b031e0e664`;
no remote fetch/push was performed. This is a local implementation, not a production rollout.

## Final architecture and ownership

| Phase | Capability | Authoritative owner |
| --- | --- | --- |
| 1A–1B | Tenant-scoped cash ledger, accounts, categories, manual Finance UI | `finance_service.py`, existing Finance routes |
| 2A | Customers, receivables, invoices and atomic invoice-payment recording | Existing Finance service and invoice/payment tables |
| 2B | Recurring expenses and project cash movement | Existing recurring services, posting identities and explicit processing script |
| 3 | Cashflow, category, account, receivables and project reporting/exports | Existing service report calculations and `finance_reports.py` |
| 4A | Read-only aggregate analysis | `finance_analyst.py` |
| 4B–4C | Signed action drafts, human confirmation, quotas and safe diagnostics | `finance_operator.py`, `finance_ai_safety.py`, existing Finance services |
| 5AB | Professional invoices and purpose-bound customer sharing | `finance_invoice_view.py` and existing routes/templates |
| 5C | Collections, aging, customer statements and manual reminders | `finance_collections.py` and existing services |
| 6A | Receipt extraction, editable review and managed expense posting | `finance_receipts.py`, shared file/PDF validators, Finance receipt service |
| 6B | Bank staging, editable review and explicit reconciliation | `finance_bank_extract.py`, `finance_bank_service.py` |
| 6C | Transient composition and safe workflow proposals | Pure `finance_assistant.py`, Assistant page and browser handoffs |

No accounting engine, locking framework, PDF parser, OCR integration, posting path,
reconciliation algorithm or persistence layer was added by the Assistant.

## Unified Assistant behavior

Finance → **AI Assistant** opens `/business/<business_id>/finance/assistant`.
The composer has text, optional attachments and explicit Auto/Ask/Record/Receipt/Bank modes.
It displays response cards with the next action instead of claiming that work was completed.

`POST .../assistant/route` accepts a strict JSON object containing only text, mode
and filename metadata. It never receives raw attachments, ledger context, account/category
choices, tokens or model results. Its response contains an allowlisted workflow and an
optional allowlisted Operator action suggestion. There is no AI intent-classifier call.
The router module has no database, provider or financial execution imports.

| Request | Safe proposal and handoff |
| --- | --- |
| Explicit Ask Finance | Embedded existing Analyst form; choose period/focus and click Analisis |
| Explicit Record Transaction | Embedded existing Operator form; review action/date, choose references, then request draft |
| Receipt attachment + explicit receipt/expense intent | Receipt card → Lanjut Review Struk → existing Phase 6A analyze endpoint |
| Bank attachment + explicit bank/statement intent | Bank card → user selects Finance account → existing Phase 6B analyze endpoint |
| One CSV in Auto | Bank proposal; actual parsing remains deterministic Phase 6B CSV parsing |
| Ambiguous PDF/image | Clarification: Struk / Pengeluaran, Mutasi Bank or Batal; no extraction or staging |
| Ambiguous text | Manual workflow choices; no paid call or financial execution |
| Unsupported type/action | Safe unsupported state; no execution |

Explicit modes override automatic intent detection; unsupported files remain unsupported.
File metadata is only a routing hint. Every original downstream endpoint validates actual
bytes and all user/business/reference permissions independently. Attached files are not
silently treated as Analyst or Operator input; the UI requires removing them or selecting
the appropriate document workflow.

Analyst and Operator forms are extracted into shared template partials and retain their
original JavaScript and endpoints. Receipt/bank handoffs are native browser multipart
submissions to the original endpoints. Server routes never call each other through HTTP.
The Assistant therefore cannot bypass an engine's allowlist, quota or confirmation gate.

## Safety boundaries

- Login, Finance beta/admin behavior, business membership and global CSRF remain unchanged.
  Both Assistant endpoints enforce Finance access. Original downstream endpoints repeat it.
- Analyst/Operator business allowlists remain authoritative, including for administrators.
  Disabled capabilities show an unavailable card; their forms are omitted.
- Analyst facts still come from Phase 3 calculations. Narrative is read-only and validated.
- Operator suggestions select no account/category/invoice ID. Users must accept the action
  and select references before the original signed draft is generated. The final original
  confirmation endpoint remains deterministic and idempotent; no Assistant confirm endpoint.
- Receipt validation, isolated PDF worker, 10-minute signed user/business-bound review,
  SHA-256 deduplication and atomic `FINANCE_RECEIPT` posting remain authoritative.
- Bank import account selection precedes staging. Staging remains REVIEW, with UNMATCHED
  rows. The Assistant never opens, matches, posts or ignores rows. Existing state/lock,
  row-hash origin, source deduplication, one-link uniqueness and candidate bounds remain.
- Only explicit posting changes ledger money. Bank MATCH links existing money without
  duplicating it. Receipt analysis/bank staging remain excluded from reports and balances.
- Managed source protections cover `FINANCE_OPERATOR`, `FINANCE_INVOICE_PAYMENT`,
  `FINANCE_RECURRING_EXPENSE`, `FINANCE_RECEIPT` and `FINANCE_BANK_IMPORT`.
  Existing managed VOID records remain linked/identified and are not recreated silently.
- Original business write locks, reference validation, ledger insert and audit commit
  boundaries are reused. Phase 6C introduces no new financial transaction boundary.
- Deterministic routing spends no AI quota. Analyst/Operator draft/receipt/bank extraction
  share existing Finance user/business quotas. Confirmations retain the separate bounded
  deterministic confirmation bucket and make no AI calls.

## Narrow hardening findings and fixes

1. **Padded managed-source conversion:** normal transaction updates checked raw input
   before source-name normalization. A padded `FINANCE_OPERATOR` or
   `FINANCE_INVOICE_PAYMENT` could bypass the unrelated-origin guard. New checks use the
   normalized source before any update. Regression coverage tests all five managed origins.
2. **Incomplete Finance cache coverage:** dashboard and other Finance pages lacked the
   full privacy headers already used by document workflows. All Finance blueprint responses
   now receive `private, no-store`, no-referrer, noindex/noarchive and frame-denial headers.
3. **Receipt multipart disk spooling:** Werkzeug could spool larger receipt uploads before
   validation. Receipt analyze now shares the bank route's request-memory stream behavior.
   Receipt byte/page limits and parser resource isolation are unchanged.

No speculative ledger/report redesign was performed. Existing Operator VOID replay still
returns the original record and never creates replacement money, as required by Phase 4C.

## Privacy, limits and UI

No migration, chat table, prompt history, conversation log, attachment archive or sensitive
browser storage was introduced. Text and selected files stay in browser memory; the router
receives only bounded text/filename metadata transiently and never echoes those fields.
Raw attachments go directly to their existing selected validator after the continuation click.
The original engines may persist normalized bank staging or confirmed ledger data as before.

No financial text/token is added to query strings. Assistant GET ignores query-state by
redirecting to its clean URL; routing rejects query parameters. Errors and diagnostics use
fixed categories, never raw exception/provider text, prompts, filenames or tokens.
Infrastructure access logging still requires operational review, especially existing signed
public invoice/statement URLs; the Assistant does not create public links.

Assistant routing: ≤2,000 text characters, ≤10 filenames, ≤255 characters per filename,
16 KiB JSON envelope. It accepts no raw multipart upload. Analyst/Operator retain their
existing 1,000-character limits; longer composer text is not silently truncated and must
be shortened in the downstream form. Bank retains its 26 MiB multipart envelope and all
Phase 6B file limits. Other routes retain their 12 MiB request envelope.

Receipt: one JPG/JPEG/PNG/WEBP/PDF, ≤5 MiB and ≤10 PDF pages.
Bank: CSV ≤2 MiB; PDF ≤10 MiB / ≤20 pages; ≤10 images, ≤5 MiB each / ≤25 MiB combined.
Existing isolated PDF worker limits remain 384 MiB address space, 5 CPU seconds and
8 seconds parent timeout; scanned/mixed PDFs reuse Anthropic document extraction.

Mobile UI uses wrapping cards, full-width fields, 48-pixel touch targets, labeled file
selection, selected-file text, status regions, keyboard focus and loading states. Routing
double-submit and file-handoff guards are tested. Pending Operator drafts block replacement
requests; confirmation retry uses the same signed draft. Clearing removes transient text
and results, and browser back/forward cache restoration reloads the transient Assistant.
No dynamic Finance content uses innerHTML, localStorage or sessionStorage.

## Schema and production configuration

**Phase 6C adds no migration.** Existing ordered Client Hub migrations through 0031 must
already be applied for the full Finance feature set. Finance-specific migration pairs:

| Migration | Purpose |
| --- | --- |
| 0028_finance_foundation_{sqlite,postgres}.sql | Ledger, accounts, categories and Finance constraints/indexes |
| 0029_finance_receivables_{sqlite,postgres}.sql | Customers, invoices, items, payments and associated constraints |
| 0030_finance_recurring_{sqlite,postgres}.sql | Recurring schedules/postings and deduplication |
| 0031_finance_bank_imports_{sqlite,postgres}.sql | Bank staging, row states, deduplication and one-link/candidate indexes |

Retain Client Hub dependencies in `requirements.txt`, particularly **Flask ≥3.1** for
request-specific upload sizing, plus requests, pypdf, Pillow, psycopg2-binary, reportlab
and the existing application server. PDF isolation requires the supported OS `resource`
limits; parsing fails closed when unavailable.

| Setting | Requirement / behavior |
| --- | --- |
| `SECRET_KEY` | Strong stable secret, at least 32 characters for Finance signing; no development default. Changing it invalidates sessions/reviews/share tokens. |
| `PUBLIC_APP_BASE_URL` | Canonical HTTPS origin, without path/query/credentials, for existing invoice/statement sharing. |
| `DATABASE_URL` | Production PostgreSQL connection; keep out of logs. Unset only for disposable/local SQLite. |
| `CLIENT_HUB_DB_PATH` | Disposable/local SQLite path when PostgreSQL is not selected. |
| `APP_ENV` or `CLIENT_HUB_ENV` | Set production for production; existing `RENDER` detection also enables production security behavior. |
| `KILAS_FINANCE_BETA` | Existing Finance client-access gate (`on`/`true`/`1`/`yes`); existing KILAS_ADMIN exception is preserved. |
| `KILAS_FINANCE_ANALYST_BUSINESS_IDS` | Explicit comma-separated positive business IDs; empty/malformed setting disables Analyst. |
| `KILAS_FINANCE_OPERATOR_BUSINESS_IDS` | Separate explicit business allowlist; empty/malformed setting disables Operator, including confirm. |
| `ANTHROPIC_API_KEY` | Existing Anthropic credential for enabled AI capabilities; no new credential. |
| `CLIENT_HUB_FINANCE_ANALYST_MODEL` | Existing Analyst/Operator model override; current code default `claude-haiku-4-5-20251001`. Confirm provider access before rollout. |
| `CLIENT_HUB_MODEL` | Existing receipt/bank model override; current code default `claude-sonnet-4-6`. Confirm image/document support and provider access before rollout. |
| `RUN_MIGRATIONS_ON_BOOT` | Existing controlled migration switch; PostgreSQL defaults off. Do not enable permanently merely for 6C. |

Preserve existing DB connect/statement/lock/idle-transaction timeouts. Deploy with debug
and Flask testing disabled, HTTPS and secure cookies. No new Assistant environment switch.

## Verification results

All provider calls mocked; Python socket connections blocked, including inherited child
Python processes. Test databases are disposable SQLite. UI tests run the actual Assistant
JavaScript in an offline Node DOM harness, with mocked fetch/native navigation.

```sh
PYTHONDONTWRITEBYTECODE=1 python client-hub/tests/run_finance_regressions.py
node --test client-hub/tests/test_finance_assistant_ui.cjs
```

| Suite | Passed | Failed / errors / skipped |
| --- | ---: | --- |
| Finance 1A | 15 | 0 / 0 / 0 |
| Finance 1B | 16 | 0 / 0 / 0 |
| Finance 2A | 25 | 0 / 0 / 0 |
| Finance 2B | 22 | 0 / 0 / 0 |
| Finance 3 | 19 | 0 / 0 / 0 |
| Finance 4A | 15 | 0 / 0 / 0 |
| Finance 4B | 35 | 0 / 0 / 0 |
| Finance 4C | 25 | 0 / 0 / 0 |
| Finance 5AB | 24 | 0 / 0 / 0 |
| Finance 5C | 30 | 0 / 0 / 0 |
| Finance 6A | 53 | 0 / 0 / 0 |
| Finance 6B | 114 | 0 / 0 / 0 |
| Finance 6C | 103 | 0 / 0 / 0 |
| Client Hub V1 | 22 | 0 / 0 / 0 |
| Production foundation | 26 | 0 / 0 / 0 |
| Client Hub batch 1 | 16 | 0 / 0 / 0 |
| Client Hub batches 2–3 | 14 | 0 / 0 / 0 |
| Client Hub UX batch | 22 | 0 / 0 / 0 |
| PostgreSQL SQL adapter | 2 | 0 / 0 / 0 |
| PostgreSQL JSON compatibility | 16 | 0 / 0 / 0 |
| **Python subtotal** | **614** | **0 / 0 / 0** |
| Assistant UI interaction harness | 12 | 0 / 0 / 0 |
| **Total** | **626** | **0 / 0 / 0** |

JavaScript syntax checks and git whitespace/scope checks also passed.
Concurrency/idempotency regression results on SQLite:

- Same Operator draft, receipt confirmation or bank row confirmation creates one record.
- Invoice payment retries stay idempotent; competing payments cannot overpay.
- Concurrent recurring UI/processing attempts retain one posting per occurrence.
- Concurrent bank upload identities return one import; two rows cannot link one transaction.
- Bank POST versus MATCH allows only one decision; review versus opening rejects stale state.
- Injected audit/row-write failures roll back ledger and reconciliation changes together.
- VOID origins retain their identity/link and do not silently recreate money.

## Known limitations and unverified release checks

- No live PostgreSQL server was available. Migration parity/SQL/JSON adapter checks passed;
  live PostgreSQL migrations, locks and concurrency were not executed.
- No real customer myBCA PDF, bank screenshot or receipt fixture was supplied. Generated
  files and mocked AI responses test validation/transport/state boundaries, not extraction accuracy.
- No live Anthropic integration or production deployment was tested.
- UI markup and JavaScript interactions were tested offline. A live browser connection was
  unavailable; mobile visual layout, camera picker and real native navigation need browser QA.
- AI can omit/misread values; editable review against the user's original remains mandatory.
  Existing bounded model output can force manual fallback for large statements.
- AI quotas remain the inherited process-local shared user/business limiter, not distributed
  across workers. Deployment capacity/memory/provider quotas need operational sizing.
- Auto routing deliberately supports a small set of clear intents; ambiguity requires choices.
  No automatic posting, matching, bank API, voice, chat history, tax/payroll or double-entry engine.
- Original files are not archived. Existing normalized-text redaction may remove long references.
- No reversal/reopen of finalized bank decisions was added; VOID/changed links need attention.
- Finance remains integer IDR cashflow reporting, not an accounting-profit or tax system.

## Controlled production rollout checklist — document only

These steps were **not executed** during this task:

1. Verify a restorable production backup and record pre-rollout schema/ledger totals.
2. Exercise the full migration chain, including pending 0031, on staging/disposable PostgreSQL.
3. Run real PostgreSQL Finance concurrency/idempotency smoke tests for payment, receipt,
   recurring posting, bank POST/MATCH and source deduplication.
4. Verify Flask ≥3.1, Python/PDF resource isolation and installed Client Hub dependencies.
5. Verify `SECRET_KEY`, HTTPS `PUBLIC_APP_BASE_URL`, production environment, secure cookies,
   debug/testing disabled, database settings and request/proxy upload size limits.
6. Verify Anthropic credentials and current access/support for the configured text/vision/PDF
   models. Confirm Finance Analyst/Operator allowlists for the intended pilot businesses.
7. In a separately authorized controlled production rollout, apply pending migrations in order,
   including 0031. Use the existing migration mechanism; do not rely on 6C to create tables.
8. Pilot one real receipt, one real myBCA PDF and one bank screenshot. Inspect every extracted
   value; verify zero ledger effect before confirmation and totals before/after a single posting.
9. Verify duplicate confirmation and matching behavior, VOID attention states, allowlist denial,
   CSRF, expired/wrong-tenant tokens and no cross-tenant account/category/invoice/import access.
10. Exercise mobile file/camera/gallery selection, long filenames, keyboard controls, loading,
    network interruption and safe same-draft retry in a real browser.
11. Inspect safe application/infrastructure logs for absence of prompts, raw files, provider
    errors, credentials and tokens. Monitor worker memory, timeouts and shared limiter behavior.

## Rollback and access-disable strategy

- Disable Analyst/Operator by clearing their business allowlists. This also blocks outstanding
  Operator confirmations; tell affected users to check ledger history before preparing new drafts.
- Disable ordinary client Finance access through the existing `KILAS_FINANCE_BETA` gate.
  This preserves the existing administrator exception; it is not a complete admin shutdown.
  A complete emergency shutdown requires an explicitly authorized operational access block.
- Assistant can be removed by reverting the Phase 6C application commit in a separate approved
  release. It has no schema migration to undo. Retain 0031 and all normalized staging/decisions;
  never drop tables, erase history or recreate managed transactions as a rollback technique.
- Rolling application code back to Phase 6B also removes the new hardening fixes; disabling
  access while investigating is preferable to exposing the identified old source-update gap.
- Keep `SECRET_KEY` stable for routine application rollback. Emergency rotation invalidates
  sessions and outstanding signed reviews/shares and requires a deliberate operational decision.

## Exact changed files

All 18 changed files are under `client-hub/`; no repository-root files were changed.

```text
client-hub/FINANCE_PHASE6C.md
client-hub/app.py
client-hub/finance_assistant.py
client-hub/finance_service.py
client-hub/routes_finance.py
client-hub/static/finance_analyst.js
client-hub/static/finance_assistant.css
client-hub/static/finance_assistant.js
client-hub/static/finance_operator.js
client-hub/templates/_finance_analyst_workspace.html
client-hub/templates/_finance_operator_workspace.html
client-hub/templates/finance_analyst.html
client-hub/templates/finance_assistant.html
client-hub/templates/finance_dashboard.html
client-hub/templates/finance_operator.html
client-hub/tests/run_finance_regressions.py
client-hub/tests/test_finance_assistant_ui.cjs
client-hub/tests/test_finance_phase6c.py
```

Phase 6A and Phase 6B remain unchanged. One new local commit is created on Phase 6B;
its SHA is reported separately (`git log -1`). No push, deployment or production migration.
