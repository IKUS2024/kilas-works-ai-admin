# Phase 10 — rollback diagnosis / narrow hotfix validation in progress

**NOT COMPLETE. RESUME FROM STATUS FILE.**

## Current authoritative checkpoint — 2026-09-25 hotfix

This section supersedes every historical release-state statement below.
- Main: d2d8af60419630fd351d62654126db63a643ebee (V2 merged).
- Hub rollback LIVE: 05d50a8bdf14ede2b1ec588f1fe78619f7387f0c,
  dep-daqvhnvavr4c73f6rvvg. Bot rollback LIVE: same SHA,
  dep-daqvi3p42hec73ce9ov0. Both Render autoDeploy=no / trigger=off confirmed.
- Installed additive 0055–0061 schema and historical paid business-2 backfill retained.
  Do not rerun schema installation/backfill, reset config, or touch business-2 Finance.
- WhatsApp general stays OFF. Main has no workflow runs; hotfix PR gates pending.
- Working branch: fix/phase10-core-interpretation, based on merged main.

### Rollback cause and evidence limits

Production WEB event 4aba4dec-ca71-442f-b500-60aae1a0fbff for business 2 failed
with invalid_provider_result, attempts=1. Read-only metadata confirms one inbound,
one Customer link, zero Jobs, AI_ACTIVE/version=0. No customer text was exported.
Old code stored neither the exception category nor the model output; the precise original
model response is unrecoverable from that event. Do not claim historical byte-for-byte proof.

Controlled inference-only reproductions used pinned d2d8af6 code and the same existing
category/config/input internally in the production environment, without replaying the event
or invoking Job/Finance writes. They record ordinary simulation usage, not Finance entries.
Sanitized output shows provider_error=false, stop=end_turn, GENERIC_SERVICE, STALE config.
Responses repeatedly had a complete Markdown JSON envelope: old understanding.parse rejects
this at JSON parsing. Removing only that envelope exposed a second deterministic contract
failure: invalid corrections/ambiguous shape (old parse line 84). A sanitized shape probe
also showed BUSINESS_QUESTION carrying service/location/preferred_date_or_time fields;
all evidence quotes were exact substrings, and field names were known. Non-operational
intents with fields are correctly prohibited. This is a structured interpretation/prompt
contract failure, not demonstrated network/provider unavailability or Job validation failure.
Category fallback to GENERIC_SERVICE is valid; no category remapping or STALE-config wipe.

### Hotfix implementation gates PASS — c2455f8dcb68419e4661f4b4f7937c69b531ee9b

PR #17 is mergeable against unchanged d2d8af6, with no unresolved review threads.
Exact remote tree bf50757264540fd350ead634d2c44cc209f0e687 matches local reviewed code.
Phase 1 runs inside the Phase 2–5 regression gates. Phase 2–10 implementation runs PASS:
2=36097096240, 3=36097096264, 4=36097096269, 5=36097096306,
6=36097096256, 7=36097096228, 8=36097096227, 9=36097096238, 10=36097096252.
Finance baseline job 107951532996: 39 files / 1018 tests PASS, zero skipped.
PostgreSQL rehearsal job 107951533313 PASS; authenticated browser job 107951533025
PASS / 30 checks. Artifact 10847668876 downloaded and results/screenshots inspected;
SHA256 a87a24d3a8acd8ea095d55049969eb3ac4969c502ab946ef1164f8c084c86a24.

Pinned candidate understanding/prompt tested inference-only in the isolated diagnostic
process against the same production config/input: REQUEST with service/need/location/
preferred_date_or_time, no ambiguity, strict parse PASS, decision READY_FOR_QUOTE,
Job field validation PASS. This did NOT create a production Job or replay a WEB event.

Pre-deploy read-only verification: all nine Finance fingerprints below still match exactly
(excluding business 13; ordered JSON text joined by newline, relocation_version excluded).
Profile/services/FAQs match their recorded fingerprints; 22 additive tables still present;
business 2 retains ACTIVE ai_admin_pro 2026-09-03 -> 2026-10-03 from verified payment 4;
business 13 has no AI subscription. No reset, Finance write or new backfill was performed.

Render saved next-deploy Hub config has Core/Customers/Jobs/Playbooks/Operations/Web=true,
allowlist=2; Bridge and WhatsApp flags/channel list absent/default OFF. The running rollback
process uses its historical snapshot (V2 flags absent); that is expected and differs from
saved next-deploy configuration. No env changes are needed for the hotfix release.
Both auto-deploys stay OFF. Both live deployments remain rollback 05d50a8.

This documentation checkpoint changes no runtime/test content. Wait for its PR checks before
merge/deploy. PRE-MERGE implementation GATE PASS; production verification still pending.

### Narrow candidate fix

- Accept exactly one complete ```json or unlabelled Markdown envelope, bounded by the original
  size limit; still strictly validate JSON, duplicate keys, types, keys, evidence and intents.
- Make operational quote requests vs general business questions, empty non-operational fields,
  and corrections/ambiguous arrays explicit in the extraction prompt.
- At most one fresh extraction after contract rejection; no rejected facts are accepted or
  persisted. No network-error retry. Do not retry without enough remaining event lease time
  or after takeover/version change. Truncated provider output never authorizes a Job.
- If interpretation remains unsafe, request Human Takeover through the existing tenant/gate/
  event/lease/version/channel-fenced transaction when Operations is eligible. Otherwise retain
  fail-closed behavior. Job errors remain separately diagnosed, not silently accepted.
- Closed diagnostic codes distinguish understanding, workflow, Job, provider and handover
  failures. No prompts, raw output, customer text, tokens, secrets or exception messages logged.
- No schema, accounting, entitlement, category or normalized configuration mutation.

Local synthetic tests cover category/config shape, fenced JSON, deterministic create/update,
Customer reuse, exact retry, no rejected facts, malformed/unsafe output, tenant-scoped handover,
in-flight takeover, truncation/lease budget, and sanitized Job-error logging.
Focused tests and all implementation gates above PASS. Documentation-head checks must finish
before merge. No hotfix deploy or successful production smoke yet.

Next: certify exact hotfix head in PR; update checkpoint; safely merge only after all gates
PASS; keep auto-deploy OFF; manually deploy exact certified main revision; Pm__bae Web Chat
first, then Customer/Job readback, logs and Finance fingerprints, then remaining Phase 10 QA.
Never mark COMPLETE on synthetic or inference-only results. Roll back on critical failure.

---

## Historical pre-rollback checkpoints (superseded)

# Phase 10 — PRE-MERGE GATE PASS; controlled release pending

**PRE-MERGE GATE PASS on implementation candidate c57252416bf1ceb27e7b89333f0e0d0a96fb54b6.**
**Wait for all current-head CI after this documentation checkpoint before production mutation.**
**RESUME FROM STATUS FILE.**

## Paid lifecycle repair checkpoint — supersedes prior pilot blockers

User authorizes AI/Web Chat pilot **business 2 Pm__bae**, preserving all existing data;
Finance QA writes ONLY **business 13 / branch 19**. Intended Core/Web allowlist is **2**,
not 13. Finance-only 13 remains denied AI entitlement. No logout/password access or WA sends.
Old production Finance session lock is not a pre-deploy blocker; verify its removal after V2.

Read-only billing evidence: payment 4 / invoice 4 / project 4, ai_admin_pro, VERIFIED,
invoice PAID, verified_at 2026-09-03T14:43:56.747677Z. Existing authoritative period rule
is DEFAULT_PERIOD_DAYS=30: derived period ends 2026-10-03T14:43:56.747677Z.
Pending payment 10 / invoice 10 / project 25 is NOT evidence and is not modified.
Pm__bae is APPROVED; normalized setup STALE; subscription absent; WhatsApp not connected.

Candidate repair now establishes an audited subscription during verified payment independently
of WhatsApp activation, serializes retries, preserves existing subscription periods/status,
and adds an evidence-derived mode to the existing audited backfill script. Expired historical
evidence cannot create a fresh ACTIVE period. Payment/subscription/audit updates are transactional.
Regression and exact review PASS on c57252416bf1ceb27e7b89333f0e0d0a96fb54b6.
No production subscription backfill, schema install, env change, merge or deploy yet.
Both production services/main remain 05d50a8bdf14ede2b1ec588f1fe78619f7387f0c.
Only prior authorized production mutation remains creation of QA business 13 via product UI.

## PRE-MERGE GATE PASS — 2026-09-25

All required implementation gates passed on c57252416bf1ceb27e7b89333f0e0d0a96fb54b6.
This checkpoint changes documentation only; wait for its own current-head CI before mutation.
Required env names present, secret values not inspected; seven missing schema steps verified;
rollback target/artifacts/recovery available; PR #16 mergeable, no unresolved review threads;
controlled pilot 2 authorized with real verified billing, Finance QA 13/19 only.
WhatsApp activation excluded. No unresolved dependency is required for the existing normalized
Web Chat path. The STALE owner refresh requires normal review, never bypass approved-state rules.

Next authorized sequence: recheck remote main/head/CI → apply missing seven additive schema
steps from pinned candidate → audited evidence-derived subscription backfill business 2 and
idempotent retry → stage pilot flags with Save only → normal PR #16 merge → monitor both
Render auto-deploys → real Putri-session production smoke and integrity/log/isolation checks.
On critical regression, close pilot flags and roll both services back to recorded main SHA;
retain additive schema (old-code compatibility rehearsed), do not delete customer data.
Do not mark COMPLETE until production verification succeeds under the user's QA allocation.

## Current candidate verification — c57252416bf1ceb27e7b89333f0e0d0a96fb54b6

- Narrow lifecycle implementation reviewed against the prior certified candidate; no product redesign.
  One paid invoice contributes one period even with duplicate payment rows. Existing ACTIVE/GRACE
  rows remain unchanged. Payment, invoice, project, package and entitlement commit atomically.
- Phase 10 run 36093023940 PASS: PostgreSQL job 107939254441 proves exact seven-step additive
  sequence twice, every legacy row preserved, old/new code Finance read/write compatibility,
  paid verification rollback/concurrency, historical audited CLI twice with exact periods retained.
- Authenticated browser job 107939254614 PASS: 30 checks covering new AI-only, Finance-only,
  combined path, Inbox/Customer/Job/takeover, Bridge draft and authoritative partial payment,
  duplicate submission, foreign-tenant denial, operator surfaces and session persistence.
- All five paid/historical compatibility test files PASS. Old checkout fixtures now supply required
  profiles; old dashboard payment checks now inspect supported V2 project/invoice pages.
- Phase 1 regression runs inside Phase 2. Phase 2–10 PASS; full Phase 7 baseline job 107939254711 PASS: 39 files / 1018 tests.
- Exact feature/main comparison: 246 files, 155 commits ahead, zero behind, no merge conflict.
  Prior complete feature review plus all subsequent lifecycle/test diffs reviewed; diff --check clean.
- Production read-only backfill preview through isolated candidate code returned payment_ids=[4],
  start 2026-09-03T14:43:56.747677+00:00, end 2026-10-03T14:43:56.747677+00:00;
  DRY RUN, no subscription written. Archive was created from client-hub subdirectory, so its
  application root is /tmp/kilas-phase10-11d5d4c (not an additional client-hub subdirectory).
- Main/services remain rollback SHA. V2 schema absent. No backfill or pilot flag mutation.
  Render Save only control checked with unchanged form (saved unchanged configuration, no deploy).
- Planned Hub flags after all gates: KILAS_CORE_V2_ENABLED=true,
  KILAS_CORE_V2_TEST_BUSINESS_IDS=2, KILAS_CUSTOMERS_V2_ENABLED=true,
  KILAS_JOBS_V2_ENABLED=true, KILAS_PLAYBOOKS_V2_ENABLED=true,
  KILAS_OPERATIONS_V2_ENABLED=true, KILAS_WEB_CHAT_ENABLED=true.
  Finance Bridge remains OFF for this allocation: user prohibits Finance QA writes in business 2,
  and business 13 remains Finance-only. Combined Bridge write path is certified in disposable QA;
  never bridge these two production businesses or claim production Bridge-write verification.
  WhatsApp Core OFF/no selected channels; bot V2 flags unchanged/default closed.
- Pm__bae normalized configuration exists, status STALE. Current approved/live owner setup flow
  intentionally stages changes for admin review; do not downgrade status or wipe knowledge.
  Existing normalized knowledge is accepted by Web Chat; refresh only through supported flow if
  actually required. Verify business/profile/services/FAQs remain intact after pilot smoke.
- Pm__bae pre-pilot knowledge fingerprints: profile 1 row cea326f6acf968ff501a1dfe2c8e98ab;
  services 11 rows 854ab4f096ffc6723d48ab30fb6a1ac7;
  FAQs 2 rows 5c9a9e1ebe1d865024d09dad6a139f1a.
- Production logout/login is excluded by explicit user instruction to preserve current Putri session;
  authenticated disposable login/logout coverage passed. No passwords inspected.

## Historical checkpoint — superseded by paid lifecycle authorization above

- User explicitly authorized the already authenticated Putri session; NO logout, password access,
  reset, or login was performed. UI profile plus scoped membership query confirm Putri Maudy,
  user ID 2, OWNER of existing Pm__bae business ID 2. Existing real/ambiguous business is excluded.
- All Phase 2–10 CI at 6b06f156dd7ed61b5881b334344dfeed9c0117db SUCCESS.
- Through normal production product form, created **Kilas Internal QA**, business **13**, OWNER
  user 2, Finance branch **19 (Utama)**. Finance activation/defaults created by normal product flow.
  No QA income, expense, invoice or payment has been entered yet. Package NONE, status DRAFT.
- This is the only production business-data mutation so far. No other business/ledger was modified.
- Intended explicit V2 pilot allowlist is **13 only**. AI Admin entitlement/setup still needs
  readiness verification; no entitlement or payment bypass is authorized or performed.
- Main remains 05d50a8bdf14ede2b1ec588f1fe78619f7387f0c; both recorded Render deploys remain LIVE
  at that SHA. No V2 schema, env flag, merge or deploy change. WhatsApp OFF; no live send.
- Read-only post-creation check confirms business 13 has ZERO Finance transactions, ZERO
  invoices and ZERO AI subscriptions. Only branch 19, BUSINESS workspace, exists for business 13.
- Rechecked nine existing Finance table fingerprints EXCLUDING business 13: all counts/digests
  exactly match the earlier recorded baseline. Existing Finance data is unchanged.
- BLOCKER: current production main app.py `_lock_customer_to_selected_finance` redirects this
  session's non-Finance routes after Finance was selected while inspecting the account. Both
  /products/start and the visible /dashboard link return to Finance. This is old production
  behavior; the candidate removes that lock, but is not deployed. Do not bypass/forge session
  state, logout, inspect passwords, or substitute another user to work around it.
- BLOCKER: new internal business has package NONE and no ACTIVE/GRACE AI subscription.
  public_chat.security.available explicitly requires a paid AI entitlement in addition to
  allowlisting. Current normal product flows keep newly created Finance and AI businesses in
  separate lanes; do not silently convert this Finance workspace, grant a subscription through
  SQL, fabricate verified payment, or expand the pilot to another existing business.
- The user's requested same-session internal AI/Web Chat smoke path is therefore NOT ready.
  Stop before production schema/merge/deploy under specification section 8. Identity and pilot
  selection permission are resolved; the remaining blocker is actual product/entitlement readiness.
- Both Render Live deploys rechecked after QA business creation: unchanged on rollback SHA.
  V2 schema not installed; all V2 flags still absent/default closed; RUN_MIGRATIONS_ON_BOOT false
  unchanged; WhatsApp OFF/no live send. No deployment rollback needed because none occurred.
- PRE-MERGE GATE remains pending. Earlier "production untouched" statements below describe
  the checkpoint BEFORE this explicitly authorized isolated QA business creation.

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
| Hub execution path | authenticated Web Shell; isolated candidate archive prepared; read-only backfill preview passed |
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

## Historical blockers / resume sequence — superseded by current checkpoint

1. Phase 1–9, complete Finance, expanded authenticated browser and PostgreSQL candidate gates
   PASS. Recheck final documentation-head CI before release; do not bypass a red check.
2. Pilot identity is now resolved: Putri user 2 / internal business 13 / Finance branch 19.
   Resolve the current-session product access and legitimate AI entitlement blockers above
   before claiming launch readiness. Preserve the no-logout/no-password requirement and do
   not bypass paid entitlement or mutate Pm__bae's real ledger.
3. Recheck main/PR/current CI, schema prerequisites, recovery/rollback artifacts and execution
   checkout readiness; finalize the exact missing-only production application checkpoint.
4. Only if every gate passes: record PRE-MERGE GATE PASS; apply missing additive schema; safely
   merge PR #16 without force; watch automatic deployments (no duplicates) until BOTH are LIVE
   on the merged main SHA; run actual authorized production QA and data/log/isolation checks.
5. Keep rollout internal/pilot-scoped; WhatsApp general rollout stays separately Meta-gated.
   Mark COMPLETE only after real production verification and intact existing Finance data.

**Only authorized QA business 13 has been created; schema/main/deploys/flags unchanged.
Phase 10 is NOT COMPLETE. RESUME FROM STATUS FILE.**
