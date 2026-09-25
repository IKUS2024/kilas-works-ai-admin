# Phase 10 — pre-production verification; production untouched

**PRE-MERGE GATE NOT PASSED. DO NOT MERGE OR DEPLOY.**
**RESUME FROM STATUS FILE.**

This checkpoint supersedes the earlier incremental status text; prior checkpoints
remain in Git history. Required rollout specification: `ASTRA_PHASE10_PRODUCTION_ROLLOUT.md`.
All nine required documents were read completely. Phase 10 adds release QA/documentation
only; no production application code or accounting behavior has been changed in Phase 10.

## Current release state

- Repo: IKUS2024/kilas-works-ai-admin; feature/kilas-core-v2; PR #16 still open/draft.
- Latest implementation/test candidate: fa8a561f4bba684aadb7aa485baa76bf3f07505a.
- Main and production rollback target: **05d50a8bdf14ede2b1ec588f1fe78619f7387f0c**.
- Latest PR inspection: mergeable, base still rollback SHA; all Phase 2–10 CI on the implementation candidate SUCCESS.
- No production database writes, schema installation, environment writes, merge,
  deployment request, or production test transaction has occurred in Phase 10.
- No WhatsApp general activation. Official Meta access remains unverified.

## Boolean authorization resolved

User explicitly authorized ONLY the boolean read of RUN_MIGRATIONS_ON_BOOT.
Hub value is **false**: inspected its single Render UI row, then hid it again.
The flag was not changed. Bot has no such service-level variable. Both services have
no linked environment groups. No DATABASE_URL, API key, token, password, SECRET_KEY,
or WhatsApp/Meta credential value was opened, copied, displayed or logged.
The prior automatic-review rejection of this narrow read is resolved by that authorization.

## Production baseline / rollback

| Resource | Verified state |
| --- | --- |
| Hub srv-da7ti2psrm7s73dh9i2g | LIVE dep-daqa4e49v7es73cdvuc0 at 05d50a8bdf14ede2b1ec588f1fe78619f7387f0c |
| Bot srv-da353nm7bikc7396r430 | LIVE dep-daqa3f145ssc73916je0 at 05d50a8bdf14ede2b1ec588f1fe78619f7387f0c |
| Both services | main; auto-deploy on commit; Oregon; one instance; gunicorn app:app; pip requirements |
| Hub / bot rootDir | client-hub / repository root |
| Database dpg-da4ea1u417fc73fqv80g-a | PostgreSQL 18.4, available, basic_256mb, 1 GB, no HA |
| DB Recovery dashboard | settled page confirms 3-day point-in-time recovery; restore/export controls available |
| Rollback controls | both service deploy histories expose Rollback controls for prior artifacts |
| Hub execution path | authenticated Web Shell available; no command executed |
| Production UI | signed-in /products/start loads on old main; not V2 E2E certification |
| /healthz | browser returned ERR_BLOCKED_BY_CLIENT; endpoint remains unverified; no bypass attempted |

Latest read-only schema recheck still finds no kw_web_*, kw_core_*,
finance_workspace_corrections or finance_workspace_opening_history tables.
Earlier column/trigger inspection: no relocation_version; existing two guard_branch_identity
triggers use finance_branch_immutable(). Legacy Kilas Order history remains present.
Read-only count baseline: 12 businesses, 32 accounts, 58 Finance transactions, 9 invoices,
4 invoice payments, 2 recurring expenses, 2 historical Kilas Order requests.
Counts alone are not a full integrity proof and may change with live customer traffic.
No customer records were copied to QA. No backup/restore or deployment rollback was executed.

Read-only integrity checkpoint, 2026-09-25 03:13 UTC: ordered JSON-row MD5 fingerprints
(excluding only relocation_version). These are comparison digests, not backups or secret values.
Recapture immediately before schema application and compare after; reconcile legitimate live
traffic rather than assuming any changed aggregate is migration corruption.

| Finance table | Rows | Digest |
| --- | ---: | --- |
| accounts | 32 | 0b9a2531aa186761a463042801e1edc8 |
| transactions | 58 | 037f2e03f84b72e80ab93abab5f55149 |
| invoices | 9 | fb5dd4d4e02582a180f423bac62121d6 |
| invoice_items | 20 | 4dc304675cd4197faed7a2c8d0cc2f1e |
| invoice_payments | 4 | 64ff1cd509319060e24d71ead988d920 |
| customers | 7 | 33c9b67a9b5da14e4be697abdebcfd95 |
| recurring_expenses | 2 | 6d6d3d0fd1bd30a5ce05c4fefc39bc5f |
| recurring_postings | 0 | d41d8cd98f00b204e9800998ecf8427e |
| budgets | 2 | 5922928e4763dc81fa4fba7e7e1f68ab |


Rollback after any critical auth/tenant/Finance/migration/duplicate-write/core-path failure:
disable affected pilot gates, restore BOTH services to the recorded pre-release artifact/SHA,
and verify login, old Finance reads/writes and logs. Preserve additive schema and historical
data; do not run a destructive down migration. Record each deploy ID/status and DB state.
PITR is recovery protection, not a claim that a restore exercise was performed.

## Regression and browser evidence

- Original runtime candidate 809127129ccfa2b251814c3115c0353606fe8f15 passed Phase 2–9.
  Phase 7 baseline job 107917097582 explicitly reports **39 files / 1018 tests PASS**.
- f7b60657290e42c5b593b69a78030a94389b5051 passed all Phase 2–10 workflows.
- 9de24ee229e2449fab955b5386c1f9c87b3f4099 Phase 10 run 36087817688 passed
  19 authenticated browser checks plus exact PostgreSQL rehearsal.
- 210d03b0dfeba657ef419c918666e510080991f7 Phase 10 run 36088135919 passed
  extended Finance account/opening/income/expense/report/export checks and the old-code
  rollback write rehearsal. Subsequent test-only changes add recurring/budget/AI/invoice QA.
- Phase 9 run 36088005579 passed 155 responsive visits / 157 screenshots at
  360, 390, 430, 820 and 1440px, with focus, overflow and JavaScript checks.
  Downloaded artifacts were inspected, including mobile, tablet and desktop Finance
  and the Phase 10 Web Inbox / authoritative Bridge readback.
- Latest expanded gate on fa8a561f4bba684aadb7aa485baa76bf3f07505a: Phase 10 run
  **36089094923 SUCCESS**, browser job **107927378713: 30 checks PASS**, migration job
  **107927378851 PASS**. Artifact 10844029520, SHA256
  ca77a9317064399dfd20ca9c3915f2ad3dfacd2da8d26b54149fb313cbdf87c1.
  All Phase 2–10 workflows on fa8a561 SUCCESS:
  Phase 2 36089094888; Phase 3 36089094877; Phase 4 36089094917;
  Phase 5 36089094896; Phase 6 36089094901; Phase 7 36089094889;
  Phase 8 36089094881; Phase 9 36089094891; Phase 10 36089094923.
  Complete Finance baseline job 107927378670 again reports 39 files / 1018 tests PASS.
  This status update is documentation-only; recheck its successor-head checks before merge.

Phase 10 browser harness uses REAL signup/password login/logout, forms, CSRF, routes,
SQLite storage and owner sessions. It does not inject sessions through persona endpoints.
Coverage includes AI/both signup intent and minimal setup, Finance activation, independent
Finance-only signup; eligible fixture Web Chat -> Inbox -> Customer/Job with repeated visitor,
missing-info followup, takeover suppression, manual reply, explicit AI resume; owner mapping,
reviewed Bridge DRAFT, existing Finance issue/payment, exact payment-form replay, authoritative
partial/outstanding readback; foreign-object denial and operator pages.
New Finance-only coverage adds opening balance, income/expense, recurring, budget,
AI draft/cancel without ledger writes, standalone invoice/payment, reports and CSV/ZIP exports.
Paid eligibility and AI-provider IO remain synthetic; this is not live-provider certification.
New signup checks and the paid-eligible chat fixture are separate scenarios.

Earlier expanded-harness failures are not suppressed:
- incomplete synthetic AI normalized config was correctly rejected; supplied fixture config;
- account row was inside a collapsed group; test now expands the real group;
- Finance provider was initially absent; only synthetic configuration/provider HTTP is stubbed;
- Finance operator capability must explicitly be enabled in the self-service QA environment;
- disposable signing configuration is explicit; production credentials remain untouched.
Diagnostic run 36089036575 confirmed finance_ai_unavailable at the capability check.
Expanded browser run 36089094923 then passed with explicit QA-only operator enablement.

Security/reliability regression is covered across Phase 2–8 suites: tenant/direct-object denial,
CSRF, idempotency/retry, concurrent Customer/Job/Bridge operations, stale versions and transaction
rollback, subscription denial/read-only, unknown WhatsApp identity/no tenant fallback, takeover
and authoritative Finance payment status. Phase 2 includes Phase 1 regression.
No skipped tests count as a gate pass. Local py_compile and git diff --check passed.
Local Flask/psycopg2/pikepdf/PostgreSQL are unavailable; runtime results come from disposable CI.

## Exact diff review

Reviewed feature-vs-main runtime changes: app/blueprint/auth/workspace/navigation, Finance service
and route changes, public Web Chat, Core flags/customer/job/interpretation/playbook/operations,
Bridge, WhatsApp routing/readiness/takeover, schema installers and 0055–0061 SQL, templates and
shared/public UI assets. Reviewed regression assertion migrations for current money/display/scope
contracts. No production money-parser rewrite is part of V2. Phase 10 changes are confined to:

- .github/workflows/kilas-v2-phase10-qa.yml
- client-hub/tests/phase10_release_dev.py
- client-hub/tests/phase10_release_browser_qa.py
- scripts/phase10_postgres_rehearsal.py
- docs/KILAS_V2_PHASE10_STATUS.md

All 746 tracked blobs at c7898b8353beca450569ea3a0263e7825c98d0e8 matched the local materialization.
Subsequent edits are the reviewed test-only diagnostics/operator flag changes. Final comparison
at fa8a561: 150 commits ahead, 0 behind, 239 changed files; no unresolved merge conflict. Reinspect exact
final head/base/diff/checks before PRE-MERGE GATE PASS; do not trust this checkpoint after drift.

## Exact missing-schema plan — tested, NOT executed in production

Use the certified feature checkout in an isolated directory in the Hub Web Shell, verify
its exact commit before execution, and retain the existing application process checkout.
Do not print environment values or shell tracing. Existing service credentials are consumed
internally by the application connection code; never reveal or copy them.

From candidate/client-hub, the ordered sequence is:

1. python -m public_chat.schema --apply (0055)
2. python -m kilas_core.customer_schema --apply (0056)
3. python -m kilas_core.job_schema --apply (0057)
4. python -m kilas_core.operation_schema --apply (0058)
5. Execute the ENTIRE migrations/0059_finance_workspace_corrections_postgres.sql using
   psycopg2 cursor.execute in ONE connection transaction; connection timeout 10s,
   statement timeout 30s, lock timeout 5s. Never split dollar-quoted SQL on semicolons.
6. python -m kilas_core.finance_bridge_schema --apply (0060, including immutable triggers)
7. python -m kilas_core.whatsapp_schema --apply (0061)

Installer connections already have bounded connection/statement/lock/idle transaction timeouts.
0059 adds default-zero relocation_version columns and REPLACES two existing guard triggers
with audited correction-aware guards. It does not rewrite economic values. 0060 reinstalls
immutable-history triggers. Each step is transactional; stop on any failure, record the last
committed step, inspect read-only state, and never blindly replay unrelated migration history.
Read-only production prerequisite review also confirms existing Finance primary keys and
composite unique keys required by the new foreign keys.
No db.init_schema, no historical runner, no RUN_MIGRATIONS_ON_BOOT=true, no schema reset.
Re-query actual missing schema immediately before applying; do not reinstall unrelated schema.

Disposable PostgreSQL 18 rehearsal builds a pre-V2 synthetic baseline from exact rollback main,
then executes the seven steps twice. It compares every pre-existing row (excluding only the
new default-zero column), verifies zero relocation versions, and exercises Finance authoritative
invoice/payment readback with both old and candidate code. It also seeds NEW synthetic records
using OLD rollback code after upgrade, verifying writes/payment/recurring and preserving the
original fixtures. Latest fa8a561 run 36089094923 migration job 107927378851 PASS.
Loopback-only guard, exact /kilas_phase10 target, explicit QA flag and empty-schema checks prevent
accidental use against production. No production data was used.

## Feature flags / pilot readiness

Full Render key inventories and linked-group state inspected. All ten V2 variables below are
ABSENT in both services; no inherited groups. Authoritative defaults therefore remain closed.
Required credential NAMES are present (Hub database/session/Anthropic; bot database/Anthropic/
internal/WhatsApp); values, validity and live-provider behavior were not inspected or certified.

| Flag | Current / intended controlled state |
| --- | --- |
| KILAS_CORE_V2_ENABLED | absent/default false; enable only for certified pilot |
| KILAS_CORE_V2_TEST_BUSINESS_IDS | absent/empty; requires explicit authorized IDs |
| KILAS_CUSTOMERS_V2_ENABLED | absent/default false; required for pilot Customers |
| KILAS_JOBS_V2_ENABLED | absent/default false; required for pilot Jobs |
| KILAS_PLAYBOOKS_V2_ENABLED | absent/default false |
| KILAS_OPERATIONS_V2_ENABLED | absent/default false |
| KILAS_WEB_CHAT_ENABLED | absent/default false; allowlist + paid eligible AI required |
| KILAS_FINANCE_BRIDGE_ENABLED | absent/default false; owner-reviewed mapping required |
| KILAS_WHATSAPP_CORE_ENABLED | absent/default false; keep OFF |
| KILAS_WHATSAPP_CORE_CHANNELS | absent/empty; no selected production channel |
| RUN_MIGRATIONS_ON_BOOT | Hub false, unchanged; bot absent |

Customer flag is a module gate rather than a Core business allowlist: confirm package-scoped
visibility and use Core/Web/Job/Bridge allowlists where supported. Finance operator has separate
Finance capability gates; enabling Core does not establish Finance AI capability.
Do not change Finance entitlement or unrelated env values without a reviewed rollout need.

## Remaining release blockers / resume sequence

1. Phase 1–9, complete Finance, expanded authenticated browser and PostgreSQL candidate gates
   PASS. Recheck final documentation-head CI before release; do not bypass a red check.
2. Identify explicitly authorized internal/pilot business IDs, owner-access context and Finance
   workspace/branch for production test writes. Existing demo-named records are NOT authorization.
   This is required by specification sections 7 and 11; do not invent IDs or write in a customer
   ledger. Choose and document the exact controlled allowlist before production mutation.
3. Recheck main/PR/current CI, schema prerequisites, recovery/rollback artifacts and execution
   checkout readiness; finalize the exact missing-only production application checkpoint.
4. Only if every gate passes: record PRE-MERGE GATE PASS; apply missing additive schema; safely
   merge PR #16 without force; watch automatic deployments (no duplicates) until BOTH are LIVE
   on the merged main SHA; run actual authorized production QA and data/log/isolation checks.
5. Keep rollout internal/pilot-scoped; WhatsApp general rollout stays separately Meta-gated.
   Mark COMPLETE only after real production verification and intact existing Finance data.

**Production remains unchanged. Phase 10 is NOT COMPLETE. RESUME FROM STATUS FILE.**
