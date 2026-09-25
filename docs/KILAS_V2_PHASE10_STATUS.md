# Phase 10 — BLOCKED before release; production untouched

**PRE-MERGE GATE NOT PASSED. DO NOT MERGE OR DEPLOY.**
**RESUME FROM STATUS FILE.**

## Resumed checkpoint — boolean verified, remaining release QA in progress

- User explicitly authorized ONLY the true/false migration flag read.
- Hub `RUN_MIGRATIONS_ON_BOOT` is **false**, verified in its single Render UI row,
  then hidden again. No credential values read, copied or logged; no flag changed.
- Bot linked-environment-group section confirms no environment groups available.
  Thus neither service has inherited V2 enablement from a linked group.
- Current tested feature head: `f7b60657290e42c5b593b69a78030a94389b5051`.
- Phase 2–10 workflows on that head all SUCCESS, including Phase 7 run
  36086838228 and exact PostgreSQL 18 rehearsal run 36086838099.
- Previous narrow approval blocker is resolved. Combined authenticated browser
  release journeys, exact diff review and pilot identity remain pending.
- PRE-MERGE GATE NOT PASSED. No production mutations, merge or deploy.

## Latest checkpoint — rehearsal PASS, release BLOCKED before production

Implementation/test checkpoint: **7f4022abe660ff176b6f6acfcc16b94136708f9b**.
This later checkpoint supersedes the pending access/rehearsal statements below.

- New Phase 10 workflow **36086483153 SUCCESS**, job **107919420144**.
  Log verifies the exact seven-step sequence twice; every legacy row preserved;
  both rollback-main and candidate Finance authoritative readback PASS.
- On 7f4022a, Phase 2 36086483078, Phase 3 36086483210, Phase 4 36086483019,
  Phase 5 36086483017, Phase 6 36086483031, Phase 8 36086483020 and
  Phase 9 36086483097 SUCCESS. Phase 7 36086483080 runtime job
  107919420096 SUCCESS; finance-baseline job 107919420433 still IN PROGRESS
  at last inspection. Earlier 8091271 complete Finance baseline remains certified
  1018/39, and no application or Finance code changed in 7f4022a.
- Local py_compile and git diff --check PASS. Default invocation of the new
  rehearsal correctly refuses execution without its explicit disposable QA target.
- Render authentication succeeded through secure Google sign-in.
- Complete visible service environment key inventories inspected for both services:
  all ten listed V2 enablement/allowlist/channel variables are ABSENT at service level.
  Hub has no linked environment groups. Bot linked-group section exists; inheritance
  still requires final verification. No enablement or environment change performed.
- Hub required DATABASE_URL, SECRET_KEY and ANTHROPIC_API_KEY names are present;
  bot DATABASE_URL/ANTHROPIC_API_KEY/internal/WhatsApp credential names are present.
  Secret values were not revealed or verified.
- Hub RUN_MIGRATIONS_ON_BOOT exists but is masked.
  **Automatic approval review rejected clicking Show secret and reading this value**,
  interpreting it as disclosure contrary to the no-secret-values requirement.
  No retry or indirect workaround was attempted. Its actual boolean remains unverified.
  To proceed, obtain explicit user approval to read ONLY this non-credential migration
  flag's boolean state; do not reveal DATABASE_URL, API keys, tokens or other secrets.
- Render DB Recovery settled UI confirms **3-day point-in-time recovery**;
  initial loading text briefly said 7 days, superseded by the settled Basic-plan page.
  Restore database and Create export controls are available. No restore, export or
  database mutation was invoked. Actual restore exercise is not claimed.
- Authenticated Hub Web Shell is available. No shell command was executed.
  Hub deploy history exposes rollback controls for prior deployments at rollback SHA.
  Bot rollback UI and final recovery readiness remain pending.
- Production is still at the exact LIVE deploys and rollback SHA in the table below.
  DB/schema, flags, main, both service deploys and customer records are unchanged by this run.
- Full Phase 10 combined browser journeys/login persistence, final exact diff review,
  authorized pilot IDs and final pre-merge checkpoint are still pending.
  Existing phase browser gates do not automatically certify those missing release checks.

**State: BLOCKED before PRE-MERGE GATE PASS. No merge, production schema or deploy.**
**RESUME FROM STATUS FILE.** Resolve the narrow approval block, finish the remaining
pre-production gates, then follow the authorized controlled deployment sequence.

## Initial release checkpoint
- Repository: IKUS2024/kilas-works-ai-admin; branch: feature/kilas-core-v2.
- Inspected remote feature: 809127129ccfa2b251814c3115c0353606fe8f15.
- Current remote main and verified production rollback target:
  05d50a8bdf14ede2b1ec588f1fe78619f7387f0c.
- PR #16: open, draft, mergeable; 138 commits ahead, 0 behind main;
  release comparison contains 234 changed files. Full final diff review remains pending.
- All nine required documents read completely.
- Candidate source materialized and every tracked blob checked against the complete
  non-truncated GitHub tree (756 tree entries); zero missing/mismatched blobs.
- This checkpoint adds only a disposable PostgreSQL release rehearsal, its CI
  workflow, and this status. No application or accounting behavior changes.

## Verified production state
| Resource | Verified state |
| --- | --- |
| kilas-works-client-hub / srv-da7ti2psrm7s73dh9i2g | LIVE deploy dep-daqa4e49v7es73cdvuc0 at rollback SHA |
| kilas-works-ai-admin / srv-da353nm7bikc7396r430 | LIVE deploy dep-daqa3f145ssc73916je0 at rollback SHA |
| Both services | main; autoDeploy=yes, trigger=commit; one instance; Oregon; gunicorn app:app |
| Hub rootDir / bot rootDir | client-hub / repository root |
| Database dpg-da4ea1u417fc73fqv80g-a | available; PostgreSQL 18.4; basic_256mb; 1 GB; HA disabled |
| DB/schema mutations in Phase 10 | NONE |
| Environment/flag changes in Phase 10 | NONE |
| Merge/deploy requests in Phase 10 | NONE |
| Production UI baseline | app.kilasworks.id loads signed-in product selector; not V2 E2E certification |

Read-only schema inspection: no kw_web_* or kw_core_* tables; no
finance_workspace_corrections or finance_workspace_opening_history tables;
no relocation_version columns. Finance transaction/recurring guard_branch_identity
triggers still invoke finance_branch_immutable(). Legacy Kilas Order tables remain.

Read-only count checkpoint (not a complete integrity proof; live traffic may change it):
12 businesses, 32 Finance accounts, 58 Finance transactions, 9 Finance invoices,
4 invoice payments, 2 recurring expenses, 2 historical Kilas Order requests.
No customer names, credentials or monetary values were collected for this checkpoint.

## Regression evidence on inspected feature SHA
All eight latest Phase 2–9 workflows SUCCESS:
- Phase 2: 36085735701 (includes Phase 1).
- Phase 3: 36085735703.
- Phase 4: 36085735742.
- Phase 5: 36085735741.
- Phase 6: 36085735712.
- Phase 7: 36085735822.
- Phase 8: 36085735771.
- Phase 9: 36085735699.

Phase 7 finance-baseline job 107917097582 log explicitly reports:
**PASS: 39 files / 1018 tests**.
Finance runtime job 107917097739: SQLite Bridge, PostgreSQL workspace corrections,
PostgreSQL Bridge and mobile standalone/connected/read-only gates all SUCCESS.
These are existing phase regression gates, NOT proof of every new Phase 10 requirement.
The existing browser harness uses synthetic session entry and provider stubs; full real
signup/login/logout/persistence journeys and a complete combined release E2E remain pending.

Local execution limitation: Flask/psycopg2/pikepdf not installed; requirements install
could not resolve Flask in this runtime. No local PostgreSQL server available.
Do not call local tests passing. Use isolated GitHub Actions QA, never production as a test substitute.

## Missing-schema plan — inspected, NOT yet production-approved
Order:
1. From client-hub: python -m public_chat.schema --apply (0055).
2. python -m kilas_core.customer_schema --apply (0056).
3. python -m kilas_core.job_schema --apply (0057).
4. python -m kilas_core.operation_schema --apply (0058).
5. Execute ONLY migrations/0059_finance_workspace_corrections_postgres.sql as one
   PostgreSQL transaction with bounded connection/lock/statement timeouts.
   Preserve dollar-quoted function bodies; NEVER split this file on semicolons.
6. python -m kilas_core.finance_bridge_schema --apply (0060, including immutable triggers).
7. python -m kilas_core.whatsapp_schema --apply (0061).

0059 is not merely new tables: it adds default-zero relocation columns and replaces
two guard triggers with audited correction-aware guards. It does not rewrite existing
row economics. Its compatibility, transaction boundary and rollback protection must
be explicitly certified. 0060 installer also reinstalls immutable-history triggers.
Do not run db.init_schema, historical migration runner, RUN_MIGRATIONS_ON_BOOT=true,
or drop/reset tables on production.

New scripts/phase10_postgres_rehearsal.py:
- accepts only explicit QA flag + empty loopback database named kilas_phase10 on PG18;
- verifies the exact rollback checkout;
- builds pre-V2 synthetic fixture from that checkout's SQL registry in the empty QA DB only;
- seeds opening balance/income/expense/invoice/partial-payment/recurring through existing services;
- executes the exact seven-step upgrade twice;
- compares all pre-existing table rows, accounting for default-zero added columns;
- checks authoritative Finance readback using BOTH old main and candidate code.
No copied production data and no production target accepted.
New workflow .github/workflows/kilas-v2-phase10-qa.yml runs that rehearsal.
Result at this checkpoint: PENDING. No exact-sequence PASS claimed.

Before production application, additionally verify schema constraints/indexes against
actual production, backup/PITR or equivalent restore protection, bounded DDL lock behavior,
authorized execution path, unchanged rollback main SHA and all final release gates.

## Rollout configuration audit
Actual production values are **UNVERIFIED**, not assumed OFF from code defaults.
The Render connector exposes env update but no env read or SQL write operation.
Browser Render dashboard is at sign-in; authenticated access is needed for env,
backup/restore and shell/execution readiness. No local Render/DB credentials available.

| Flag | Safe intended initial state, pending current-env inspection |
| --- | --- |
| KILAS_CORE_V2_ENABLED | false until certified internal pilot |
| KILAS_CORE_V2_TEST_BUSINESS_IDS | no broad IDs; explicit authorized pilot IDs only |
| KILAS_CUSTOMERS_V2_ENABLED | false initially; required true for pilot Customer path |
| KILAS_JOBS_V2_ENABLED | false initially; required true for pilot Job path |
| KILAS_PLAYBOOKS_V2_ENABLED | false initially; true only with Customer/Job prerequisites |
| KILAS_OPERATIONS_V2_ENABLED | false initially; true for certified pilot operations |
| KILAS_WEB_CHAT_ENABLED | false initially; true only with explicit Core allowlist and paid eligibility |
| KILAS_FINANCE_BRIDGE_ENABLED | false initially; true only for explicit owner-reviewed pilot mapping |
| KILAS_WHATSAPP_CORE_ENABLED | false; official Meta access unverified |
| KILAS_WHATSAPP_CORE_CHANNELS | no selected production channels |
| RUN_MIGRATIONS_ON_BOOT | false; no historical replay |

Customer and Job flags are additional authoritative dependencies omitted from the
specification's illustrative flag list. Never invent pilot business IDs.
Do not change Finance entitlements, existing secrets, or unrelated env values.
No WhatsApp activation or live provider send authorized by this checkpoint.

## Remaining gates / precise blockers
1. Observe the new exact migration rehearsal and current-head Phase 1–9 CI.
2. Full Phase 10 browser journeys/security/rollback coverage and exact release diff review.
3. Authenticated Render env inspection, DB backup/restore evidence, and authorized schema execution.
4. Identify authorized internal/pilot businesses and package personas without fabricating customer records.
5. Record concrete rollback deployment mechanism/readiness for both services. SHA is verified,
   but end-to-end rollback execution path and backup recovery are not yet certified.
6. Only then PRE-MERGE GATE PASS, missing schema, safe PR merge, both auto-deploys LIVE,
   production E2E, data integrity, logs/5xx/isolation, pilot configuration and COMPLETE.

Rollback policy: disable affected pilot gates and restore both services to recorded
rollback SHA if critical failure appears. Preserve additive schema/data; no destructive
database downgrade. Never trigger duplicate deployments or claim release completion
while any gate is pending.
